"""Unit tests for field mapping, normalization, and completeness reporting."""

import pytest
from app.services.mapping import (
    map_forager_organization_to_company,
    map_forager_person_to_contact,
    parse_location,
)


def test_parse_location_from_osm():
    """Test extracting city, state, country from osm_locations."""
    loc = {
        "name": "Full Location String",
        "osm_locations": [
            {"name": "Seattle", "place_type": "city"},
            {"name": "Washington", "place_type": "state"},
            {"name": "United States", "place_type": "country"},
        ],
    }
    city, state, country = parse_location(loc)
    assert city == "Seattle"
    assert state == "Washington"
    assert country == "United States"


def test_parse_location_from_string():
    """Test fallback parsing of location from comma-separated string."""
    loc = {"name": "Austin, Texas, United States"}
    city, state, country = parse_location(loc)
    assert city == "Austin"
    assert state == "Texas"
    assert country == "United States"


def test_map_forager_org_full(sample_forager_org):
    """Test full mapping of Forager organization to HubSpot company properties."""
    company = map_forager_organization_to_company(sample_forager_org)
    assert company.name == "OpenAI"
    assert company.domain == "openai.com"
    assert company.website == "https://openai.com"
    assert company.revenue == 3700000000
    assert company.employee_count == 1500
    assert company.linkedin_url == "https://www.linkedin.com/company/openai"
    assert company.city == "San Francisco"
    assert company.state == "California"
    assert company.country == "United States"

    props = company.to_hubspot_properties()
    assert props["name"] == "OpenAI"
    assert props["annualrevenue"] == "3700000000"
    assert props["numberofemployees"] == "1500"
    assert props["linkedin_company_page"] == "https://www.linkedin.com/company/openai"


def test_map_forager_org_preserves_existing():
    """Test that missing Forager fields do not overwrite existing HubSpot data."""
    sparse_forager = {
        "id": 1,
        "name": "New Company Name",
        "domain": "test.com",
    }
    existing_props = {
        "annualrevenue": "5000000",
        "numberofemployees": "50",
        "city": "Boston",
        "state": "MA",
        "country": "USA",
    }
    company = map_forager_organization_to_company(sparse_forager, existing_props)
    assert company.name == "New Company Name"
    assert company.revenue == 5000000
    assert company.employee_count == 50
    assert company.city == "Boston"


def test_map_forager_person_full(sample_forager_person):
    """Test mapping of person details with contact info and employer details."""
    org = {"name": "OpenAI", "domain": "openai.com"}
    phones = ["+1-555-0199"]
    emails = ["mira@openai.com"]

    contact = map_forager_person_to_contact(
        person_data=sample_forager_person,
        role_data=sample_forager_person["roles"][0],
        organization_data=org,
        phone_numbers=phones,
        emails=emails,
    )

    assert contact.first_name == "Mira"
    assert contact.last_name == "Murati"
    assert contact.email == "mira@openai.com"
    assert contact.phone == "+1-555-0199"
    assert contact.job_title == "Chief Technology Officer"
    assert contact.company_name == "OpenAI"
    assert contact.company_domain == "openai.com"
    assert contact.linkedin_url == "https://www.linkedin.com/in/miramurati"
    assert contact.city == "San Francisco"
    assert contact.state == "California"
    assert contact.country == "United States"

    # Completeness
    comp = contact.calculate_completeness()
    assert comp["completeness_percentage"] >= 90.0
    assert "email" in comp["populated_fields"]
    assert "phone" in comp["populated_fields"]


def test_map_forager_person_missing_contact_info(sample_forager_person):
    """Test mapping when email and phone are unavailable from provider."""
    contact = map_forager_person_to_contact(
        person_data=sample_forager_person,
        phone_numbers=[],
        emails=[],
    )
    assert contact.email is None
    assert contact.phone is None

    comp = contact.calculate_completeness()
    assert "email" in comp["missing_fields"]
    assert "phone" in comp["missing_fields"]
    assert comp["populated_count"] < comp["total_fields"]
