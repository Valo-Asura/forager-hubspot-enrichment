"""Script to enrich the OpenAI demo company and discover 5 enriched contacts in HubSpot."""

import asyncio
import json
import os
import sys
from typing import Optional
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.config import get_settings
from app.services.companies import CompanyEnrichmentService
from app.services.discovery import ContactDiscoveryService

load_dotenv()


async def run_openai_demo_enrichment(target_domain: str = "openai.com", max_contacts: int = 5):
    """
    Executes the full primary evaluation flow for the OpenAI demo company and 5 contacts.
    """
    settings = get_settings()
    print("=" * 70)
    print("Forager x HubSpot: Primary Deliverable Automation")
    print(f"Target Company Domain: {target_domain}")
    print(f"Target Enriched Contacts: {max_contacts}")
    print("=" * 70)

    if not settings.FORAGER_API_KEY:
        print("[ERROR] FORAGER_API_KEY is not set in environment or .env file.")
        print("Please configure your Forager API key to execute live enrichment.")
        sys.exit(1)

    if not settings.HUBSPOT_ACCESS_TOKEN:
        print("[ERROR] HUBSPOT_ACCESS_TOKEN is not set in environment or .env file.")
        print("Please configure your HubSpot Private App token to execute live enrichment.")
        sys.exit(1)

    # Initialize clients
    forager = ForagerClient(
        api_key=settings.FORAGER_API_KEY,
        base_url=settings.FORAGER_BASE_URL,
        account_id=settings.FORAGER_ACCOUNT_ID,
    )
    hubspot = HubSpotClient(
        access_token=settings.HUBSPOT_ACCESS_TOKEN,
        client_secret=settings.HUBSPOT_CLIENT_SECRET,
        base_url=settings.HUBSPOT_BASE_URL,
    )

    discovery = ContactDiscoveryService(
        forager_client=forager,
        hubspot_client=hubspot,
        allowed_titles=settings.allowed_job_titles_list,
        max_contacts=max_contacts,
    )
    company_service = CompanyEnrichmentService(
        forager_client=forager,
        hubspot_client=hubspot,
        discovery_service=discovery,
    )

    try:
        # Step 1: Search or create the OpenAI company in HubSpot
        print(f"\n[1/4] Checking existing HubSpot record for domain '{target_domain}'...")
        existing_company = await hubspot.search_company_by_domain(target_domain)
        company_id: Optional[str] = None

        if existing_company:
            company_id = existing_company.get("id")
            print(f"  -> Found existing HubSpot company record: ID {company_id} ('{existing_company.get('properties', {}).get('name')}')")
        else:
            print(f"  -> No existing record found. Initializing company placeholder for '{target_domain}'...")
            initial_props = {
                "name": "OpenAI",
                "domain": target_domain,
            }
            created_comp = await hubspot.create_company(initial_props)
            company_id = created_comp.get("id")
            print(f"  -> Created company record in HubSpot: ID {company_id}")

        # Step 2: Enrich Company via Forager
        print(f"\n[2/4] Enriching company '{target_domain}' from Forager API...")
        report = await company_service.enrich_company(
            company_id=company_id,
            domain=target_domain,
            discover_contacts=False,  # We will discover contacts explicitly below
        )
        print(f"  -> Company Enrichment Status: {report.status}")
        print(f"  -> Properties Updated: {report.properties_updated}")
        if report.errors:
            print(f"  -> Warnings/Errors: {report.errors}")

        # Step 3: Discover and enrich 5 contacts
        print(f"\n[3/4] Discovering up to {max_contacts} contacts matching job-title filters...")
        print(f"  -> Configured Filters: {settings.allowed_job_titles_list}")
        contacts = await discovery.discover_and_sync_contacts(
            company_id=company_id,
            domain=target_domain,
            company_name=report.company_name or "OpenAI",
        )
        print(f"  -> Successfully discovered and synchronized: {len(contacts)} contacts.")

        # Step 4: Display contact details and completeness breakdown
        print("\n[4/4] Contact Completeness & Field Breakdown:")
        for idx, c in enumerate(contacts, 1):
            comp = c.calculate_completeness()
            print(f"\n  --- Contact #{idx}: {c.first_name} {c.last_name} ---")
            print(f"      ID:               {c.id}")
            print(f"      Title:            {c.job_title}")
            print(f"      Email:            {c.email or '[NOT PROVIDED BY SOURCE]'}")
            print(f"      Phone:            {c.phone or '[NOT PROVIDED BY SOURCE]'}")
            print(f"      Location:         {c.city or 'N/A'}, {c.state or 'N/A'}, {c.country or 'N/A'}")
            print(f"      LinkedIn:         {c.linkedin_url or 'N/A'}")
            print(f"      Employer:         {c.company_name} ({c.company_domain})")
            print(f"      Employer LinkedIn:{c.company_linkedin_url or 'N/A'}")
            print(f"      Completeness:     {comp['completeness_percentage']}% ({comp['populated_count']}/{comp['total_fields']} fields)")
            if comp['missing_fields']:
                print(f"      Missing Fields:   {', '.join(comp['missing_fields'])}")

        print("\n" + "=" * 70)
        print("Enrichment run complete. Run scripts/validate_demo_records.py to verify.")
        print("=" * 70)

    finally:
        await forager.close()
        await hubspot.close()


if __name__ == "__main__":
    asyncio.run(run_openai_demo_enrichment())
