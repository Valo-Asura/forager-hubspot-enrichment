"""Company enrichment business service."""

import logging
from typing import Any, Dict, List, Optional
from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.exceptions import RecordNotFoundError
from app.schemas import CompanyEnrichmentReport, EnrichedCompany
from app.services.discovery import ContactDiscoveryService
from app.services.mapping import map_forager_organization_to_company

logger = logging.getLogger("forager_hubspot.companies")


class CompanyEnrichmentService:
    """Orchestrates company resolution, Forager enrichment, HubSpot update, and contact discovery."""

    def __init__(
        self,
        forager_client: ForagerClient,
        hubspot_client: HubSpotClient,
        discovery_service: Optional[ContactDiscoveryService] = None,
    ):
        self.forager = forager_client
        self.hubspot = hubspot_client
        self.discovery = discovery_service or ContactDiscoveryService(forager_client, hubspot_client)

    async def enrich_company(
        self,
        company_id: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> CompanyEnrichmentReport:
        """
        Enrich a HubSpot company using Forager data and optionally discover contacts.
        """
        if not company_id and not domain:
            raise ValueError("Either company_id or domain must be provided.")

        errors: List[str] = []
        hubspot_company: Optional[Dict[str, Any]] = None
        target_company_id = company_id

        # 1. Resolve company in HubSpot
        if target_company_id:
            try:
                hubspot_company = await self.hubspot.get_company(target_company_id)
            except Exception as e:
                logger.error(f"Failed to fetch HubSpot company {target_company_id}: {e}")
                errors.append(f"HubSpot fetch error: {str(e)}")

        if not hubspot_company and domain:
            hubspot_company = await self.hubspot.search_company_by_domain(domain)
            if hubspot_company:
                target_company_id = hubspot_company.get("id")

        existing_props = hubspot_company.get("properties", {}) if hubspot_company else {}
        target_domain = domain or existing_props.get("domain") or existing_props.get("website")

        if not target_domain:
            msg = f"Cannot enrich company {target_company_id}: domain is missing in HubSpot record."
            logger.warning(msg)
            return CompanyEnrichmentReport(
                status="failed",
                company_id=target_company_id or "unknown",
                errors=[msg],
            )

        clean_domain = target_domain.lower().replace("https://", "").replace("http://", "").split("/")[0]

        # 2. Query Forager for company enrichment
        forager_org: Optional[Dict[str, Any]] = None
        try:
            forager_org = await self.forager.search_organization(clean_domain)
        except Exception as e:
            logger.error(f"Forager organization search failed for {clean_domain}: {e}")
            errors.append(f"Forager API error: {str(e)}")

        updated_props: List[str] = []
        company_name = existing_props.get("name")

        if forager_org:
            enriched_company: EnrichedCompany = map_forager_organization_to_company(
                forager_org=forager_org,
                existing_hubspot_props=existing_props,
            )
            company_name = enriched_company.name or company_name
            props_to_update = enriched_company.to_hubspot_properties()

            # 3. Update company in HubSpot
            if target_company_id and props_to_update:
                try:
                    await self.hubspot.update_company(target_company_id, props_to_update)
                    updated_props = list(props_to_update.keys())
                    logger.info(f"Updated company {target_company_id} with properties: {updated_props}")
                except Exception as e:
                    logger.error(f"Failed to update HubSpot company {target_company_id}: {e}")
                    errors.append(f"HubSpot update error: {str(e)}")
            elif not target_company_id and props_to_update:
                # If company didn't exist in HubSpot, create it
                try:
                    created = await self.hubspot.create_company(props_to_update)
                    target_company_id = created.get("id")
                    updated_props = list(props_to_update.keys())
                    logger.info(f"Created new company {target_company_id} with properties: {updated_props}")
                except Exception as e:
                    logger.error(f"Failed to create HubSpot company: {e}")
                    errors.append(f"HubSpot create error: {str(e)}")
        else:
            errors.append(f"No enrichment profile found in Forager for domain {clean_domain}")

        # 4. Discover and associate contacts if requested
        discovered_count = 0
        if target_company_id:
            try:
                contacts = await self.discovery.discover_and_sync_contacts(
                    company_id=target_company_id,
                    domain=clean_domain,
                    company_name=company_name,
                )
                discovered_count = len(contacts)
            except Exception as e:
                logger.error(f"Contact discovery failed for company {target_company_id}: {e}")
                errors.append(f"Discovery error: {str(e)}")

        return CompanyEnrichmentReport(
            status="success" if not errors or updated_props else "partial",
            company_id=target_company_id or "unknown",
            company_name=company_name,
            domain=clean_domain,
            properties_updated=updated_props,
            contacts_discovered_count=discovered_count,
            contacts_enriched_count=discovered_count,
            errors=errors,
        )
