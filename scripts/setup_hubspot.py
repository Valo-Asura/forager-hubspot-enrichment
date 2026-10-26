"""Script to inspect and prepare HubSpot CRM properties for company and contact enrichment."""

import asyncio
import os
import sys
from typing import Any, Dict, List
import httpx
from dotenv import load_dotenv

load_dotenv()

HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
HUBSPOT_BASE_URL = os.getenv("HUBSPOT_BASE_URL", "https://api.hubapi.com")

if not HUBSPOT_ACCESS_TOKEN:
    print("[ERROR] HUBSPOT_ACCESS_TOKEN environment variable is missing.")
    print("Please set HUBSPOT_ACCESS_TOKEN in .env before running setup.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}


async def inspect_properties(object_type: str, required_properties: List[str]) -> Dict[str, bool]:
    """Inspect existing properties on HubSpot object type."""
    url = f"{HUBSPOT_BASE_URL}/crm/v3/properties/{object_type}"
    print(f"\n[INFO] Checking properties for {object_type}...")

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            print(f"[ERROR] Failed to fetch properties for {object_type}: {resp.status_code} - {resp.text}")
            return {}

        data = resp.json()
        existing_names = {prop["name"] for prop in data.get("results", [])}

        results = {}
        for req_prop in required_properties:
            exists = req_prop in existing_names
            status_icon = "✓" if exists else "✗"
            print(f"  {status_icon} Property '{req_prop}': {'Exists' if exists else 'Missing'}")
            results[req_prop] = exists

        return results


async def main():
    print("=" * 60)
    print("HubSpot CRM Schema Pre-flight & Setup Verification")
    print("=" * 60)

    company_props = [
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
    ]

    contact_props = [
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
    ]

    comp_status = await inspect_properties("companies", company_props)
    cont_status = await inspect_properties("contacts", contact_props)

    missing_company = [k for k, v in comp_status.items() if not v]
    missing_contact = [k for k, v in cont_status.items() if not v]

    print("\n" + "=" * 60)
    print("Verification Summary:")
    print(f"Company properties checked: {len(company_props)}, Missing: {len(missing_company)}")
    print(f"Contact properties checked: {len(contact_props)}, Missing: {len(missing_contact)}")

    if not missing_company and not missing_contact:
        print("\n[SUCCESS] All required standard CRM properties exist in HubSpot.")
    else:
        print("\n[NOTE] Some properties are not present by default. Custom properties can be created in HubSpot UI.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
