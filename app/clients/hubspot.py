"""HubSpot API client implementing CRM v3/v4 endpoints and official webhook signature verification."""

import asyncio
import base64
import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from app.exceptions import HubSpotAPIError, WebhookSignatureVerificationError

logger = logging.getLogger("forager_hubspot.hubspot_client")

# Standard company properties requested from HubSpot
COMPANY_DEFAULT_PROPERTIES = [
    "name",
    "domain",
    "website",
    "description",
    "annualrevenue",
    "numberofemployees",
    "linkedin_company_page",
    "city",
    "state",
    "country",
    "createdate",
    "hs_lastmodifieddate",
]

# Standard contact properties requested from HubSpot
CONTACT_DEFAULT_PROPERTIES = [
    "firstname",
    "lastname",
    "email",
    "phone",
    "jobtitle",
    "company",
    "hs_linkedin_url",
    "city",
    "state",
    "country",
    "associatedcompanyid",
    "createdate",
    "hs_lastmodifieddate",
]


class HubSpotClient:
    """Asynchronous HTTP client for HubSpot CRM API v3/v4."""

    def __init__(
        self,
        access_token: str,
        client_secret: str = "",
        base_url: str = "https://api.hubapi.com",
        timeout: float = 30.0,
        max_retries: int = 3,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.access_token = access_token
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
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
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute an HTTP request against HubSpot with bounded retry logic."""
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
                    retry_after = int(response.headers.get("Retry-After", 2**attempt))
                    if attempt < self.max_retries:
                        logger.warning(
                            f"HubSpot 429 Rate Limit encountered. Retrying in {retry_after}s..."
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    raise HubSpotAPIError(
                        message="HubSpot API rate limit exceeded.",
                        status_code=429,
                        response_body=response.text,
                    )

                # Server error (5xx) backoff
                if response.status_code >= 500:
                    if attempt < self.max_retries:
                        backoff = 2**attempt
                        logger.warning(
                            f"HubSpot {response.status_code} error on {endpoint}. Retrying in {backoff}s..."
                        )
                        await asyncio.sleep(backoff)
                        continue
                    raise HubSpotAPIError(
                        message=f"HubSpot API server error {response.status_code}",
                        status_code=response.status_code,
                        response_body=response.text,
                    )

                # 4xx client errors
                if response.status_code >= 400:
                    raise HubSpotAPIError(
                        message=f"HubSpot API error {response.status_code}: {response.text}",
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
                        f"HubSpot request exception ({type(exc).__name__}) on {endpoint}. Retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise HubSpotAPIError(
                    message=f"Network error connecting to HubSpot API: {str(exc)}",
                    details={"error": str(exc)},
                ) from exc

    # =========================================================================
    # Company APIs
    # =========================================================================

    async def get_company(
        self,
        company_id: str,
        properties: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Fetch a single company record by ID."""
        props = properties or COMPANY_DEFAULT_PROPERTIES
        params = {"properties": ",".join(props)}
        logger.info(f"Fetching HubSpot company ID: {company_id}")
        return await self._request("GET", f"/crm/v3/objects/companies/{company_id}", params=params)

    async def search_company_by_domain(self, domain: str) -> Optional[Dict[str, Any]]:
        """Search a company by domain in HubSpot."""
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "domain",
                            "operator": "EQ",
                            "value": clean_domain,
                        }
                    ]
                }
            ],
            "properties": COMPANY_DEFAULT_PROPERTIES,
            "limit": 1,
        }
        logger.info(f"Searching HubSpot company by domain: {clean_domain}")
        data = await self._request("POST", "/crm/v3/objects/companies/search", json_data=payload)
        results = data.get("results", [])
        return results[0] if results else None

    async def create_company(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new company in HubSpot CRM."""
        payload = {"properties": properties}
        logger.info(f"Creating HubSpot company with name: {properties.get('name')}")
        return await self._request("POST", "/crm/v3/objects/companies", json_data=payload)

    async def update_company(self, company_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Update properties on an existing company in HubSpot CRM."""
        payload = {"properties": properties}
        logger.info(f"Updating HubSpot company ID {company_id} with {len(properties)} properties")
        return await self._request("PATCH", f"/crm/v3/objects/companies/{company_id}", json_data=payload)

    # =========================================================================
    # Contact APIs
    # =========================================================================

    async def get_contact(
        self,
        contact_id: str,
        properties: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Fetch a single contact record by ID."""
        props = properties or CONTACT_DEFAULT_PROPERTIES
        params = {"properties": ",".join(props)}
        logger.info(f"Fetching HubSpot contact ID: {contact_id}")
        return await self._request("GET", f"/crm/v3/objects/contacts/{contact_id}", params=params)

    async def search_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Search a contact by email in HubSpot."""
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "email",
                            "operator": "EQ",
                            "value": email.strip().lower(),
                        }
                    ]
                }
            ],
            "properties": CONTACT_DEFAULT_PROPERTIES,
            "limit": 1,
        }
        logger.info(f"Searching HubSpot contact by email: {email}")
        data = await self._request("POST", "/crm/v3/objects/contacts/search", json_data=payload)
        results = data.get("results", [])
        return results[0] if results else None

    async def search_contact_by_linkedin(self, linkedin_url: str) -> Optional[Dict[str, Any]]:
        """Search a contact by LinkedIn URL in HubSpot."""
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "hs_linkedin_url",
                            "operator": "EQ",
                            "value": linkedin_url.strip(),
                        }
                    ]
                }
            ],
            "properties": CONTACT_DEFAULT_PROPERTIES,
            "limit": 1,
        }
        try:
            data = await self._request("POST", "/crm/v3/objects/contacts/search", json_data=payload)
            results = data.get("results", [])
            return results[0] if results else None
        except HubSpotAPIError:
            # If hs_linkedin_url is not indexed for search in portal, ignore and return None
            return None

    async def create_contact(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new contact in HubSpot CRM."""
        payload = {"properties": properties}
        logger.info(
            f"Creating HubSpot contact: {properties.get('firstname')} {properties.get('lastname')} ({properties.get('email')})"
        )
        return await self._request("POST", "/crm/v3/objects/contacts", json_data=payload)

    async def update_contact(self, contact_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Update properties on an existing contact in HubSpot CRM."""
        payload = {"properties": properties}
        logger.info(f"Updating HubSpot contact ID {contact_id} with {len(properties)} properties")
        return await self._request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", json_data=payload)

    # =========================================================================
    # Associations APIs
    # =========================================================================

    async def associate_contact_to_company(self, contact_id: str, company_id: str) -> None:
        """Associate a contact with a company using HubSpot CRM v4 Associations API."""
        endpoint = f"/crm/v4/objects/contacts/{contact_id}/associations/companies/{company_id}"
        # Association type 1 = Primary Contact to Company association in HubSpot CRM
        payload = [
            {
                "associationCategory": "HUBSPOT_DEFINED",
                "associationTypeId": 1,
            }
        ]
        logger.info(f"Associating contact {contact_id} to company {company_id}...")
        try:
            await self._request("PUT", endpoint, json_data=payload)
            logger.info(f"Associated contact {contact_id} to company {company_id} successfully.")
        except HubSpotAPIError as e:
            # Fallback to legacy v3 association endpoint if needed
            logger.warning(f"v4 association failed ({e.status_code}), attempting v3 association...")
            v3_endpoint = f"/crm/v3/objects/contacts/{contact_id}/associations/companies/{company_id}/contact_to_company"
            await self._request("PUT", v3_endpoint)

    async def get_company_contacts(self, company_id: str) -> List[Dict[str, Any]]:
        """Retrieve contacts associated with a company."""
        endpoint = f"/crm/v4/objects/companies/{company_id}/associations/contacts"
        try:
            data = await self._request("GET", endpoint)
            return data.get("results", [])
        except HubSpotAPIError as e:
            logger.warning(f"Could not retrieve associated contacts for company {company_id}: {e}")
            return []

    # =========================================================================
    # Webhook Signature Verification
    # =========================================================================

    def verify_webhook_signature(
        self,
        signature_v3: Optional[str] = None,
        signature_v1: Optional[str] = None,
        timestamp: Optional[str] = None,
        request_url: str = "",
        request_body: bytes = b"",
        http_method: str = "POST",
    ) -> bool:
        """
        Validate HubSpot webhook signatures using official documentation.
        Supports both v3 (SHA-256 HMAC with timestamp) and v1/v2 fallback.
        """
        if not self.client_secret:
            logger.warning("HUBSPOT_CLIENT_SECRET not configured. Skipping signature verification.")
            return True

        # Check v3 signature (Current official standard)
        if signature_v3 and timestamp:
            try:
                # Check timestamp freshness: reject if > 5 minutes (300,000 ms) old
                now_ms = int(time.time() * 1000)
                req_ts = int(timestamp)
                if abs(now_ms - req_ts) > 300000:
                    logger.warning(f"Webhook rejected: timestamp {req_ts} expired compared to {now_ms}")
                    return False

                # Source string: method + request_url + request_body + timestamp
                # Note: request_url should be the full decoded URL that HubSpot requested
                body_str = request_body.decode("utf-8", errors="replace")
                source_string = f"{http_method.upper()}{request_url}{body_str}{timestamp}"

                computed_hash = hmac.new(
                    key=self.client_secret.encode("utf-8"),
                    msg=source_string.encode("utf-8"),
                    digestmod=hashlib.sha256,
                ).digest()
                expected_signature = base64.b64encode(computed_hash).decode("utf-8")

                if hmac.compare_digest(signature_v3, expected_signature):
                    return True
                logger.warning("HubSpot v3 signature mismatch.")
            except Exception as exc:
                logger.error(f"Error computing v3 webhook signature: {exc}")

        # Fallback to v1 signature
        if signature_v1:
            try:
                body_str = request_body.decode("utf-8", errors="replace")
                source = f"{self.client_secret}{body_str}"
                expected_v1 = hashlib.sha256(source.encode("utf-8")).hexdigest()
                if hmac.compare_digest(signature_v1, expected_v1):
                    return True
                logger.warning("HubSpot v1 signature mismatch.")
            except Exception as exc:
                logger.error(f"Error computing v1 webhook signature: {exc}")

        return False
