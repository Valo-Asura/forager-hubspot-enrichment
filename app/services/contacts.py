"""Contact enrichment business service."""

import logging
from typing import Any, Dict, List, Optional
from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.schemas import ContactEnrichmentReport, EnrichedContact
from app.services.mapping import map_forager_person_to_contact

logger = logging.getLogger("forager_hubspot.contacts")


class ContactEnrichmentService:
    """Orchestrates contact resolution, Forager enrichment, HubSpot update, and company association."""

    def __init__(
        self,
        forager_client: ForagerClient,
        hubspot_client: HubSpotClient,
    ):
        self.forager = forager_client
        self.hubspot = hubspot_client

    async def enrich_contact(
        self,
        contact_id: Optional[str] = None,
        email: Optional[str] = None,
        linkedin_url: Optional[str] = None,
    ) -> ContactEnrichmentReport:
        """
        Enrich a HubSpot contact using Forager data and associate with company.
        """
        if not contact_id and not email and not linkedin_url:
            raise ValueError("At least one identifier (contact_id, email, or linkedin_url) must be provided.")

        errors: List[str] = []
        hubspot_contact: Optional[Dict[str, Any]] = None
        target_contact_id = contact_id

        # 1. Resolve contact in HubSpot
        if target_contact_id:
            try:
                hubspot_contact = await self.hubspot.get_contact(target_contact_id)
            except Exception as e:
                logger.error(f"Failed to fetch HubSpot contact {target_contact_id}: {e}")
                errors.append(f"HubSpot fetch error: {str(e)}")

        if not hubspot_contact and email:
            hubspot_contact = await self.hubspot.search_contact_by_email(email)
            if hubspot_contact:
                target_contact_id = hubspot_contact.get("id")

        if not hubspot_contact and linkedin_url:
            hubspot_contact = await self.hubspot.search_contact_by_linkedin(linkedin_url)
            if hubspot_contact:
                target_contact_id = hubspot_contact.get("id")

        existing_props = hubspot_contact.get("properties", {}) if hubspot_contact else {}

        target_email = email or existing_props.get("email")
        target_linkedin = linkedin_url or existing_props.get("hs_linkedin_url")

        # 2. Query Forager
        person_detail: Optional[Dict[str, Any]] = None

        # Try reverse lookup by email
        if target_email:
            try:
                person_detail = await self.forager.reverse_lookup_by_email(target_email)
            except Exception as e:
                logger.warning(f"Forager reverse lookup by email failed: {e}")

        # Try lookup by LinkedIn identifier if email lookup yielded no result
        if not person_detail and target_linkedin:
            try:
                slug = target_linkedin.rstrip("/").split("/")[-1]
                person_detail = await self.forager.lookup_person_detail(linkedin_identifier=slug)
            except Exception as e:
                logger.warning(f"Forager person detail lookup by LinkedIn slug failed: {e}")

        if not person_detail:
            msg = f"No profile found in Forager for contact (email: {target_email}, linkedin: {target_linkedin})"
            logger.warning(msg)
            errors.append(msg)
            return ContactEnrichmentReport(
                status="failed",
                contact_id=target_contact_id or "unknown",
                email=target_email,
                errors=errors,
            )

        person_id = person_detail.get("id")
        linkedin_slug = (person_detail.get("linkedin_info") or {}).get("public_identifier")

        # 3. Retrieve phone numbers & emails if not already present
        phone_numbers: List[str] = []
        emails: List[str] = [target_email] if target_email else []

        try:
            phone_numbers = await self.forager.lookup_phone_numbers(
                person_id=person_id,
                linkedin_identifier=linkedin_slug,
            )
        except Exception as e:
            logger.warning(f"Phone lookup failed: {e}")

        try:
            personal_emails = await self.forager.lookup_personal_emails(
                person_id=person_id,
                linkedin_identifier=linkedin_slug,
            )
            for pe in personal_emails:
                if pe not in emails:
                    emails.append(pe)
        except Exception as e:
            logger.warning(f"Personal email lookup failed: {e}")

        # 4. Map to standardized contact
        enriched: EnrichedContact = map_forager_person_to_contact(
            person_data=person_detail,
            phone_numbers=phone_numbers,
            emails=emails,
            existing_hubspot_props=existing_props,
        )

        props_to_update = enriched.to_hubspot_properties()
        updated_props: List[str] = []

        # 5. Update or create in HubSpot
        if target_contact_id and props_to_update:
            try:
                await self.hubspot.update_contact(target_contact_id, props_to_update)
                updated_props = list(props_to_update.keys())
                logger.info(f"Updated HubSpot contact {target_contact_id} with properties: {updated_props}")
            except Exception as e:
                logger.error(f"Failed to update HubSpot contact {target_contact_id}: {e}")
                errors.append(f"HubSpot update error: {str(e)}")
        elif not target_contact_id and props_to_update:
            try:
                created = await self.hubspot.create_contact(props_to_update)
                target_contact_id = created.get("id")
                updated_props = list(props_to_update.keys())
                logger.info(f"Created HubSpot contact {target_contact_id} with properties: {updated_props}")
            except Exception as e:
                logger.error(f"Failed to create HubSpot contact: {e}")
                errors.append(f"HubSpot create error: {str(e)}")

        # 6. Associate with company in HubSpot if domain or name is available
        associated_company_id: Optional[str] = existing_props.get("associatedcompanyid")
        if not associated_company_id and enriched.company_domain and target_contact_id:
            try:
                company_match = await self.hubspot.search_company_by_domain(enriched.company_domain)
                if company_match:
                    comp_id = company_match.get("id")
                    await self.hubspot.associate_contact_to_company(
                        contact_id=target_contact_id,
                        company_id=comp_id,
                    )
                    associated_company_id = comp_id
                    logger.info(f"Associated contact {target_contact_id} with company {comp_id}")
            except Exception as e:
                logger.warning(f"Failed to associate contact {target_contact_id} with company: {e}")

        completeness_report = enriched.calculate_completeness()

        return ContactEnrichmentReport(
            status="success" if not errors or updated_props else "partial",
            contact_id=target_contact_id or "unknown",
            name=f"{enriched.first_name or ''} {enriched.last_name or ''}".strip(),
            email=enriched.email,
            job_title=enriched.job_title,
            company_associated_id=associated_company_id,
            properties_updated=updated_props,
            completeness=completeness_report,
            errors=errors,
        )
