"""Contact discovery and job-title filtering service."""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.config import get_settings
from app.schemas import EnrichedContact
from app.services.mapping import map_forager_person_to_contact

logger = logging.getLogger("forager_hubspot.discovery")

# Known role synonyms and title acronym expansions
ROLE_SYNONYMS = {
    "cto": ["chief technology officer", "cto", "co-founder & cto", "cofounder and cto"],
    "ceo": ["chief executive officer", "ceo", "president & ceo"],
    "cpo": ["chief product officer", "cpo"],
    "vp of engineering": [
        "vp of engineering",
        "vp engineering",
        "vice president of engineering",
        "vice president, engineering",
        "vp, engineering",
    ],
    "head of engineering": ["head of engineering", "director of engineering", "engineering director"],
    "head of product": ["head of product", "director of product", "product director"],
}


def normalize_title(title: str) -> str:
    """Normalize title for fuzzy comparison: lowercase, remove special characters."""
    if not title:
        return ""
    # Replace punctuation with space and normalize whitespace
    cleaned = re.sub(r"[^\w\s]", " ", title.lower())
    return " ".join(cleaned.split())


def matches_job_title(candidate_title: str, allowed_titles: List[str]) -> bool:
    """
    Determine if a candidate's job title satisfies the allowed filters.
    Supports case-insensitive matching, word boundary partial matches,
    and common industry acronym expansions.
    """
    if not allowed_titles:
        return True
    if not candidate_title:
        return False

    norm_candidate = normalize_title(candidate_title)

    for target in allowed_titles:
        norm_target = normalize_title(target)
        if not norm_target:
            continue

        # Direct containment check
        if norm_target in norm_candidate:
            return True

        # Check synonyms / acronyms
        for key, variations in ROLE_SYNONYMS.items():
            if norm_target in variations or norm_target == key:
                if any(var in norm_candidate for var in variations):
                    return True

        # Sub-token matching (e.g. "Software Engineer" matches "Senior Software Engineer - Platform")
        target_tokens = norm_target.split()
        if all(token in norm_candidate for token in target_tokens):
            return True

    return False


class ContactDiscoveryService:
    """Service to discover, filter, deduplicate, enrich, and associate contacts for a company."""

    def __init__(
        self,
        forager_client: ForagerClient,
        hubspot_client: HubSpotClient,
        allowed_titles: Optional[List[str]] = None,
        max_contacts: Optional[int] = None,
    ):
        settings = get_settings()
        self.forager = forager_client
        self.hubspot = hubspot_client
        self.allowed_titles = allowed_titles or settings.allowed_job_titles_list
        self.max_contacts = max_contacts or settings.MAX_CONTACTS_PER_COMPANY

    async def discover_and_sync_contacts(
        self,
        company_id: str,
        domain: str,
        company_name: Optional[str] = None,
    ) -> List[EnrichedContact]:
        """
        Discover contacts at a company matching configured job titles, enrich them,
        deduplicate them, create or update in HubSpot, and associate them with the company.
        """
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
        logger.info(
            f"Beginning contact discovery for company ID {company_id} (domain: {clean_domain}), target: {self.max_contacts} contacts."
        )

        discovered_contacts: List[EnrichedContact] = []
        seen_identifiers: Set[str] = set()

        # Step 1: Query Forager for each allowed role until max_contacts is reached
        search_roles = self.allowed_titles if self.allowed_titles else ["Engineer", "Product", "Director"]

        for role_query in search_roles:
            if len(discovered_contacts) >= self.max_contacts:
                break

            logger.info(f"Querying Forager person_role_search for domain '{clean_domain}' with role query '{role_query}'")
            try:
                results = await self.forager.search_people_by_role(
                    domain=clean_domain,
                    role_title=role_query,
                    is_current=True,
                    page=0,
                )
            except Exception as e:
                logger.warning(f"Error during person_role_search query '{role_query}': {e}")
                continue

            for res in results:
                if len(discovered_contacts) >= self.max_contacts:
                    break

                role_title = res.get("role_title") or ""
                person_info = res.get("person") or {}
                person_id = person_info.get("id")
                first_name = person_info.get("first_name") or ""
                last_name = person_info.get("last_name") or ""

                linkedin_info = person_info.get("linkedin_info") or {}
                linkedin_url = linkedin_info.get("public_profile_url") or ""
                linkedin_slug = linkedin_info.get("public_identifier") or ""

                # Verification of job title filter
                if not matches_job_title(role_title, self.allowed_titles):
                    logger.debug(f"Skipping candidate '{first_name} {last_name}' with title '{role_title}' (filter mismatch)")
                    continue

                # Deduplication key across candidates
                dedup_key = linkedin_url or linkedin_slug or f"{first_name}_{last_name}".lower()
                if dedup_key in seen_identifiers:
                    continue
                seen_identifiers.add(dedup_key)

                # Fetch contact detail / phone / email
                phone_numbers: List[str] = []
                emails: List[str] = []

                if person_id or linkedin_slug:
                    try:
                        phone_numbers = await self.forager.lookup_phone_numbers(
                            person_id=person_id,
                            linkedin_identifier=linkedin_slug,
                        )
                    except Exception as e:
                        logger.warning(f"Phone lookup failed for person {person_id}: {e}")

                    try:
                        personal_emails = await self.forager.lookup_personal_emails(
                            person_id=person_id,
                            linkedin_identifier=linkedin_slug,
                        )
                        emails.extend(personal_emails)
                    except Exception as e:
                        logger.warning(f"Personal email lookup failed for person {person_id}: {e}")

                # Work email lookup if email not yet found
                if not emails and first_name and last_name:
                    try:
                        work_email = await self.forager.lookup_work_email(
                            first_name=first_name,
                            last_name=last_name,
                            domain=clean_domain,
                            linkedin_identifier=linkedin_slug,
                        )
                        if work_email:
                            emails.append(work_email)
                    except Exception as e:
                        logger.warning(f"Work email lookup failed for {first_name} {last_name}: {e}")

                # Map to standardized contact
                org_info = {"name": company_name, "domain": clean_domain}
                contact = map_forager_person_to_contact(
                    person_data=person_info,
                    role_data=res,
                    organization_data=org_info,
                    phone_numbers=phone_numbers,
                    emails=emails,
                )

                # Step 2: Search HubSpot before creating a new contact
                hubspot_contact_id: Optional[str] = None

                # Search by email if available
                if contact.email:
                    existing_hs = await self.hubspot.search_contact_by_email(contact.email)
                    if existing_hs:
                        hubspot_contact_id = existing_hs.get("id")

                # Search by LinkedIn URL if still not found
                if not hubspot_contact_id and contact.linkedin_url:
                    existing_hs = await self.hubspot.search_contact_by_linkedin(contact.linkedin_url)
                    if existing_hs:
                        hubspot_contact_id = existing_hs.get("id")

                # Step 3: Create or update contact in HubSpot
                contact_props = contact.to_hubspot_properties()

                if hubspot_contact_id:
                    logger.info(f"Updating existing HubSpot contact ID {hubspot_contact_id}...")
                    await self.hubspot.update_contact(hubspot_contact_id, contact_props)
                    contact.id = hubspot_contact_id
                else:
                    logger.info(f"Creating new HubSpot contact for '{contact.first_name} {contact.last_name}'...")
                    created_hs = await self.hubspot.create_contact(contact_props)
                    hubspot_contact_id = created_hs.get("id")
                    contact.id = hubspot_contact_id

                # Step 4: Associate contact with the employer company in HubSpot
                if hubspot_contact_id and company_id:
                    await self.hubspot.associate_contact_to_company(
                        contact_id=hubspot_contact_id,
                        company_id=company_id,
                    )

                discovered_contacts.append(contact)

        logger.info(f"Completed discovery: synchronized {len(discovered_contacts)} contacts.")
        return discovered_contacts
