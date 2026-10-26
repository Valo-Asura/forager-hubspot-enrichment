"""Field mapping and data normalization between Forager and HubSpot."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from app.schemas import EnrichedCompany, EnrichedContact

logger = logging.getLogger("forager_hubspot.mapping")


def parse_location(location_data: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract (city, state, country) from Forager InnerLocation / OSMLocation structure.
    Forager location dict can have 'name' (e.g. 'San Francisco, California, United States')
    or 'osm_locations' list of {name, place_type}.
    """
    if not location_data:
        return None, None, None

    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    # Try osm_locations if available
    osm_locations = location_data.get("osm_locations", [])
    if isinstance(osm_locations, list):
        for osm in osm_locations:
            place_type = (osm.get("place_type") or "").lower()
            name = osm.get("name")
            if place_type in ("city", "town", "municipality") and not city:
                city = name
            elif place_type in ("state", "province", "region") and not state:
                state = name
            elif place_type in ("country", "nation") and not country:
                country = name

    # Fallback to parsing string 'name'
    if not (city and country):
        loc_str = location_data.get("name", "")
        if loc_str and isinstance(loc_str, str):
            parts = [p.strip() for p in loc_str.split(",") if p.strip()]
            if len(parts) == 1:
                country = parts[0]
            elif len(parts) == 2:
                city = parts[0]
                country = parts[1]
            elif len(parts) >= 3:
                city = parts[0]
                state = parts[1]
                country = parts[-1]

    return city, state, country


def map_forager_organization_to_company(
    forager_org: Dict[str, Any],
    existing_hubspot_props: Optional[Dict[str, Any]] = None,
) -> EnrichedCompany:
    """
    Map raw Forager Organization data into standardized EnrichedCompany.
    Preserves existing HubSpot properties if Forager data is absent.
    """
    existing = existing_hubspot_props or {}

    name = forager_org.get("name") or forager_org.get("legal_name") or existing.get("name")
    domain = forager_org.get("domain") or existing.get("domain")
    website = forager_org.get("website") or existing.get("website")
    description = forager_org.get("description") or existing.get("description")

    # Financial and headcount
    finance_info = forager_org.get("finance_info") or {}
    revenue = finance_info.get("revenue")
    if revenue is None and existing.get("annualrevenue"):
        try:
            revenue = int(float(existing["annualrevenue"]))
        except (ValueError, TypeError):
            pass

    employee_count = forager_org.get("employees_amount")
    if employee_count is None and existing.get("numberofemployees"):
        try:
            employee_count = int(float(existing["numberofemployees"]))
        except (ValueError, TypeError):
            pass

    employee_range = forager_org.get("employees_range")

    # LinkedIn info
    linkedin_info = forager_org.get("linkedin_info") or {}
    linkedin_url = linkedin_info.get("public_profile_url") or existing.get("linkedin_company_page")
    if not linkedin_url and linkedin_info.get("public_identifier"):
        linkedin_url = f"https://www.linkedin.com/company/{linkedin_info['public_identifier']}"

    # Location
    city, state, country = parse_location(forager_org.get("location"))
    if not city:
        city = existing.get("city")
    if not state:
        state = existing.get("state")
    if not country:
        country = existing.get("country")

    # Extra details
    extra_details = {
        "forager_id": forager_org.get("id"),
        "operating_status": forager_org.get("operating_status"),
        "founded_date": forager_org.get("founded_date"),
        "domain_rank": forager_org.get("domain_rank"),
        "keywords": [k.get("name") for k in forager_org.get("keywords", []) if isinstance(k, dict)],
    }

    return EnrichedCompany(
        name=name,
        domain=domain,
        website=website,
        description=description,
        revenue=revenue,
        employee_count=employee_count,
        employee_range=employee_range,
        linkedin_url=linkedin_url,
        founded_date=forager_org.get("founded_date"),
        city=city,
        state=state,
        country=country,
        extra_details=extra_details,
    )


def map_forager_person_to_contact(
    person_data: Dict[str, Any],
    role_data: Optional[Dict[str, Any]] = None,
    organization_data: Optional[Dict[str, Any]] = None,
    phone_numbers: Optional[List[str]] = None,
    emails: Optional[List[str]] = None,
    existing_hubspot_props: Optional[Dict[str, Any]] = None,
) -> EnrichedContact:
    """
    Map Forager Person record and supplementary role/contact info into EnrichedContact.
    Preserves existing HubSpot properties where source data is missing.
    """
    existing = existing_hubspot_props or {}
    role = role_data or {}
    org = organization_data or {}

    # Names
    first_name = (
        person_data.get("first_name")
        or (person_data.get("full_name", "").split()[0] if person_data.get("full_name") else None)
        or existing.get("firstname")
    )
    last_name = (
        person_data.get("last_name")
        or (" ".join(person_data.get("full_name", "").split()[1:]) if person_data.get("full_name") and len(person_data.get("full_name", "").split()) > 1 else None)
        or existing.get("lastname")
    )

    # Job title
    job_title = (
        role.get("role_title")
        or person_data.get("headline")
        or existing.get("jobtitle")
    )

    # Person LinkedIn URL
    linkedin_info = person_data.get("linkedin_info") or {}
    linkedin_url = (
        linkedin_info.get("public_profile_url")
        or (f"https://www.linkedin.com/in/{linkedin_info['public_identifier']}" if linkedin_info.get("public_identifier") else None)
        or existing.get("hs_linkedin_url")
    )

    # Employer Company Info
    company_name = (
        org.get("name")
        or org.get("legal_name")
        or role.get("organization", {}).get("name")
        or existing.get("company")
    )
    company_domain = (
        org.get("domain")
        or org.get("website")
        or role.get("organization", {}).get("domain")
    )
    if company_domain:
        company_domain = company_domain.lower().replace("https://", "").replace("http://", "").split("/")[0]

    org_linkedin_info = org.get("linkedin_info") or {}
    company_linkedin_url = (
        org_linkedin_info.get("public_profile_url")
        or (f"https://www.linkedin.com/company/{org_linkedin_info['public_identifier']}" if org_linkedin_info.get("public_identifier") else None)
    )

    # Email resolution
    email: Optional[str] = None
    if emails:
        email = emails[0]
    elif person_data.get("emails"):
        first_email_obj = person_data["emails"][0]
        email = first_email_obj.get("email") if isinstance(first_email_obj, dict) else first_email_obj
    if not email:
        email = existing.get("email")

    # Phone resolution
    phone: Optional[str] = None
    if phone_numbers:
        phone = phone_numbers[0]
    elif person_data.get("phone_numbers"):
        first_phone_obj = person_data["phone_numbers"][0]
        phone = first_phone_obj.get("phone_number") if isinstance(first_phone_obj, dict) else first_phone_obj
    if not phone:
        phone = existing.get("phone")

    # Location resolution
    city, state, country = parse_location(person_data.get("location"))
    if not city:
        city = existing.get("city")
    if not state:
        state = existing.get("state")
    if not country:
        country = existing.get("country")

    # Extra nice-to-have details
    skills = [s.get("name") for s in person_data.get("skills", []) if isinstance(s, dict) and s.get("name")]
    headline = person_data.get("headline")
    summary_about = person_data.get("description")
    photo_url = person_data.get("photo")

    extra_details = {
        "forager_person_id": person_data.get("id"),
        "headline": headline,
        "summary_about": summary_about,
        "skills": skills,
        "photo_url": photo_url,
        "educations_count": len(person_data.get("educations", [])),
        "certifications_count": len(person_data.get("certifications", [])),
    }

    return EnrichedContact(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        job_title=job_title,
        linkedin_url=linkedin_url,
        company_name=company_name,
        company_domain=company_domain,
        company_linkedin_url=company_linkedin_url,
        city=city,
        state=state,
        country=country,
        headline=headline,
        summary_about=summary_about,
        skills=skills,
        photo_url=photo_url,
        extra_details=extra_details,
    )
