"""Forager API client implementation based on official Forager API v2 specification."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.exceptions import ForagerAPIError

logger = logging.getLogger("forager_hubspot.forager_client")


class ForagerClient:
    """Asynchronous HTTP client for the official Forager.ai API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api-v2.forager.ai",
        account_id: Optional[int] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.account_id = account_id
        self.timeout = timeout
        self.max_retries = max_retries
        self._external_client = http_client is not None
        self._http_client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
        return self._http_client

    async def close(self) -> None:
        """Close the underlying HTTP client if managed internally."""
        if not self._external_client and self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        return headers

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute an HTTP request against Forager with bounded retry logic."""
        client = await self._get_client()
        url = f"{self.base_url}{endpoint}"

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
                    headers=self._headers(),
                )

                # Rate limiting (429) backoff
                if response.status_code == 429:
                    if attempt < self.max_retries:
                        backoff = 2**attempt
                        logger.warning(
                            f"Forager 429 Rate Limit encountered on {endpoint}. Retrying in {backoff}s..."
                        )
                        await asyncio.sleep(backoff)
                        continue
                    raise ForagerAPIError(
                        message="Forager API rate limit exceeded.",
                        status_code=429,
                        response_body=response.text,
                    )

                # Server error (5xx) backoff
                if response.status_code >= 500:
                    if attempt < self.max_retries:
                        backoff = 2**attempt
                        logger.warning(
                            f"Forager {response.status_code} server error on {endpoint}. Retrying in {backoff}s..."
                        )
                        await asyncio.sleep(backoff)
                        continue
                    raise ForagerAPIError(
                        message=f"Forager API server error {response.status_code}",
                        status_code=response.status_code,
                        response_body=response.text,
                    )

                # 4xx client errors
                if response.status_code >= 400:
                    raise ForagerAPIError(
                        message=f"Forager API error {response.status_code}: {response.text}",
                        status_code=response.status_code,
                        response_body=response.text,
                    )

                # 204 No Content
                if response.status_code == 204:
                    return None

                return response.json()

            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    backoff = 2**attempt
                    logger.warning(
                        f"Forager request exception ({type(exc).__name__}) on {endpoint}. Retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise ForagerAPIError(
                    message=f"Network error connecting to Forager API: {str(exc)}",
                    details={"error": str(exc)},
                ) from exc

    async def get_account_id(self) -> int:
        """Return the configured numeric account ID required by Forager endpoints."""
        if self.account_id is not None:
            return self.account_id
        raise ForagerAPIError(
            "FORAGER_ACCOUNT_ID is required. Copy it from the Forager app's My Account page."
        )

    async def search_organization(self, domain: str) -> Optional[Dict[str, Any]]:
        """Search an organization by domain via /api/{account_id}/datastorage/organization_search/."""
        account_id = await self.get_account_id()
        endpoint = f"/api/{account_id}/datastorage/organization_search/"
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]

        payload = {
            "domains": [clean_domain],
            "page": 0,
        }
        logger.info(f"Searching Forager organization for domain: {clean_domain}")
        data = await self._request("POST", endpoint, json_data=payload)
        
        results = data.get("search_results", [])
        if results:
            logger.info(f"Found Forager organization: {results[0].get('name')}")
            return results[0]
        
        logger.info(f"No organization found in Forager for domain: {clean_domain}")
        return None

    async def search_people_by_role(
        self,
        domain: str,
        role_title: str,
        is_current: bool = True,
        page: int = 0,
    ) -> List[Dict[str, Any]]:
        """Search people at a company matching a job title role via /api/{account_id}/datastorage/person_role_search/."""
        account_id = await self.get_account_id()
        endpoint = f"/api/{account_id}/datastorage/person_role_search/"
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]

        # Forager parses role_title as a boolean text-search expression. Plain
        # multiword titles such as "Software Engineer" are rejected as an
        # incomplete expression, so send configured role labels as phrases.
        role_query = role_title.strip()
        if role_query and not (role_query.startswith('"') and role_query.endswith('"')):
            role_query = '"' + role_query.replace('"', '\\"') + '"'

        payload = {
            "organization_domains": [clean_domain],
            "role_title": role_query,
            "role_is_current": is_current,
            "page": page,
        }
        logger.info(f"Searching Forager people at {clean_domain} with role: '{role_title}'")
        data = await self._request("POST", endpoint, json_data=payload)
        return data.get("search_results", [])

    async def lookup_person_detail(
        self,
        person_id: Optional[int] = None,
        linkedin_identifier: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch full details for an individual person via /api/{account_id}/datastorage/person_detail_lookup/."""
        if not person_id and not linkedin_identifier:
            raise ValueError("Either person_id or linkedin_identifier must be provided.")

        account_id = await self.get_account_id()
        endpoint = f"/api/{account_id}/datastorage/person_detail_lookup/"

        payload: Dict[str, Any] = {}
        if person_id is not None:
            payload["person_id"] = person_id
        if linkedin_identifier:
            # Extract slug if full url passed
            slug = linkedin_identifier.rstrip("/").split("/")[-1]
            payload["linkedin_public_identifier"] = slug

        logger.info(f"Looking up person detail: {payload}")
        return await self._request("POST", endpoint, json_data=payload)

    async def reverse_lookup_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find person details by email via /api/{account_id}/datastorage/person_detail_reverse_lookup/by_email/."""
        account_id = await self.get_account_id()
        endpoint = f"/api/{account_id}/datastorage/person_detail_reverse_lookup/by_email/"

        payload = {"email": email.strip()}
        logger.info(f"Reverse looking up person by email: {email}")
        try:
            return await self._request("POST", endpoint, json_data=payload)
        except ForagerAPIError as e:
            if e.status_code == 404:
                return None
            raise

    async def lookup_phone_numbers(
        self,
        person_id: Optional[int] = None,
        linkedin_identifier: Optional[str] = None,
    ) -> List[str]:
        """Fetch verified phone numbers via /api/{account_id}/datastorage/person_contacts_lookup/phone_numbers/."""
        account_id = await self.get_account_id()
        endpoint = f"/api/{account_id}/datastorage/person_contacts_lookup/phone_numbers/"

        payload: Dict[str, Any] = {}
        if person_id is not None:
            payload["person_id"] = person_id
        if linkedin_identifier:
            slug = linkedin_identifier.rstrip("/").split("/")[-1]
            payload["linkedin_public_identifier"] = slug

        try:
            data = await self._request("POST", endpoint, json_data=payload)
            if isinstance(data, list):
                return [p.get("phone_number") for p in data if p.get("phone_number")]
            return []
        except ForagerAPIError as e:
            logger.warning(f"Could not retrieve phone numbers from Forager: {e.message}")
            return []

    async def lookup_personal_emails(
        self,
        person_id: Optional[int] = None,
        linkedin_identifier: Optional[str] = None,
    ) -> List[str]:
        """Fetch personal emails via /api/{account_id}/datastorage/person_contacts_lookup/personal_emails/."""
        account_id = await self.get_account_id()
        endpoint = f"/api/{account_id}/datastorage/person_contacts_lookup/personal_emails/"

        payload: Dict[str, Any] = {}
        if person_id is not None:
            payload["person_id"] = person_id
        if linkedin_identifier:
            slug = linkedin_identifier.rstrip("/").split("/")[-1]
            payload["linkedin_public_identifier"] = slug

        try:
            data = await self._request("POST", endpoint, json_data=payload)
            if isinstance(data, list):
                return [e.get("email") for e in data if e.get("email")]
            return []
        except ForagerAPIError as e:
            logger.warning(f"Could not retrieve personal emails from Forager: {e.message}")
            return []

    async def lookup_work_email(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        linkedin_identifier: Optional[str] = None,
    ) -> Optional[str]:
        """Look up work email via /api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/."""
        account_id = await self.get_account_id()
        endpoint = f"/api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/"
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]

        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "domain": clean_domain,
            "linkedin_public_identifier": linkedin_identifier or "",
        }

        try:
            client = await self._get_client()
            response = await client.post(
                f"{self.base_url}{endpoint}",
                json=payload,
                headers=self._headers(),
            )
            if response.status_code in (200, 202):
                res_data = response.json()
                job_id = res_data.get("job_id")
                # If immediate emails returned
                if res_data.get("emails"):
                    return res_data["emails"][0]
                # Poll job result up to 3 times
                if job_id:
                    status_url = f"/api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/{job_id}/"
                    for _ in range(3):
                        await asyncio.sleep(2)
                        job_resp = await self._request("GET", status_url)
                        emails = job_resp.get("emails", [])
                        if emails:
                            return emails[0]
            return None
        except Exception as e:
            logger.warning(f"Could not retrieve work email from Forager: {e}")
            return None
