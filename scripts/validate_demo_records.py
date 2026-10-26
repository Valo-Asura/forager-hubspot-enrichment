"""Validation script to audit and verify OpenAI demo records in HubSpot CRM."""

import asyncio
import os
import sys
from typing import Any, Dict, List
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.clients.hubspot import HubSpotClient
from app.config import get_settings

load_dotenv()


async def validate_openai_records(target_domain: str = "openai.com"):
    """
    Validates company and associated contacts in HubSpot according to evaluation criteria.
    """
    settings = get_settings()
    print("=" * 70)
    print("HubSpot Demo Records Validation Audit")
    print(f"Target Domain: {target_domain}")
    print("=" * 70)

    if not settings.HUBSPOT_ACCESS_TOKEN:
        print("[ERROR] HUBSPOT_ACCESS_TOKEN is missing. Please configure .env.")
        sys.exit(1)

    hubspot = HubSpotClient(
        access_token=settings.HUBSPOT_ACCESS_TOKEN,
        client_secret=settings.HUBSPOT_CLIENT_SECRET,
        base_url=settings.HUBSPOT_BASE_URL,
    )

    try:
        # 1. Audit Company Record
        print("\n[1/3] Auditing Company Record...")
        company = await hubspot.search_company_by_domain(target_domain)
        if not company:
            print(f"  [FAIL] No company found in HubSpot for domain '{target_domain}'!")
            sys.exit(1)

        comp_id = company.get("id")
        props = company.get("properties", {})
        print(f"  [PASS] Company Found: ID {comp_id}")
        print(f"         Name:           {props.get('name')}")
        print(f"         Domain:         {props.get('domain')}")
        print(f"         Website:        {props.get('website')}")
        print(f"         Revenue:        {props.get('annualrevenue')}")
        print(f"         Employees:      {props.get('numberofemployees')}")
        print(f"         LinkedIn Page:  {props.get('linkedin_company_page')}")
        print(f"         Description:    {(props.get('description') or '')[:80]}...")
        print(f"         Location:       {props.get('city')}, {props.get('state')}, {props.get('country')}")

        # Check company enrichment completeness
        required_company_fields = ["name", "domain", "description", "annualrevenue", "numberofemployees", "linkedin_company_page"]
        populated_comp_fields = [f for f in required_company_fields if props.get(f)]
        print(f"  [INFO] Company Fields Populated: {len(populated_comp_fields)}/{len(required_company_fields)}")

        # 2. Audit Associated Contacts
        print("\n[2/3] Auditing Associated Contacts...")
        associated_contacts = await hubspot.get_company_contacts(comp_id)
        contact_ids = [c.get("toObjectId") or c.get("id") for c in associated_contacts]

        print(f"  Associated contact count: {len(contact_ids)}")
        if len(contact_ids) < 5:
            print(f"  [WARN] Found {len(contact_ids)} contacts associated with company (evaluation expects 5).")
        else:
            print(f"  [PASS] Reached target threshold: {len(contact_ids)} associated contacts.")

        # 3. Audit Individual Contact Details and Deduplication
        print("\n[3/3] Inspecting Contact Field Details & Duplicate Checks...")
        seen_emails = set()
        seen_linkedins = set()
        duplicate_count = 0

        for idx, cid in enumerate(contact_ids, 1):
            c_data = await hubspot.get_contact(str(cid))
            c_props = c_data.get("properties", {})

            email = c_props.get("email")
            linkedin = c_props.get("hs_linkedin_url")
            full_name = f"{c_props.get('firstname', '')} {c_props.get('lastname', '')}".strip()

            # Duplicate check
            is_dup = False
            if email and email in seen_emails:
                is_dup = True
            if linkedin and linkedin in seen_linkedins:
                is_dup = True

            if email: seen_emails.add(email)
            if linkedin: seen_linkedins.add(linkedin)

            if is_dup:
                duplicate_count += 1
                print(f"  [WARN] Duplicate contact record detected: {full_name} ({email or linkedin})")

            # Check required fields
            fields = {
                "first_name": c_props.get("firstname"),
                "last_name": c_props.get("lastname"),
                "job_title": c_props.get("jobtitle"),
                "linkedin": linkedin,
                "email": email,
                "phone": c_props.get("phone"),
                "city": c_props.get("city"),
                "state": c_props.get("state"),
                "country": c_props.get("country"),
            }
            pop = [k for k, v in fields.items() if v]
            missing = [k for k, v in fields.items() if not v]

            print(f"\n  --- Contact #{idx} (ID: {cid}): {full_name} ---")
            print(f"      Title:        {c_props.get('jobtitle')}")
            print(f"      Email:        {email or '[NOT IN SOURCE DATA]'}")
            print(f"      Phone:        {c_props.get('phone') or '[NOT IN SOURCE DATA]'}")
            print(f"      Location:     {c_props.get('city')}, {c_props.get('state')}, {c_props.get('country')}")
            print(f"      LinkedIn:     {linkedin or '[NOT IN SOURCE DATA]'}")
            print(f"      Populated:    {len(pop)}/{len(fields)} fields")
            if missing:
                print(f"      Missing:      {', '.join(missing)}")

        print("\n" + "=" * 70)
        print("Audit Summary:")
        print(f"Company ID:              {comp_id}")
        print(f"Total Contacts Verified: {len(contact_ids)}")
        print(f"Duplicates Detected:     {duplicate_count}")
        if duplicate_count == 0 and len(contact_ids) >= 5:
            print("[STATUS: PASS] All requirements satisfied without duplicates!")
        elif duplicate_count == 0:
            print("[STATUS: READY] Records clean; ensure 5 contacts are populated before submission.")
        else:
            print("[STATUS: REVIEW] Duplicates detected, please inspect records.")
        print("=" * 70)

    finally:
        await hubspot.close()


if __name__ == "__main__":
    asyncio.run(validate_openai_records())
