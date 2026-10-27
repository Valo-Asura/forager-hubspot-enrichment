"""Integration tests for end-to-end company enrichment and discovery."""

import pytest
import respx
from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.services.companies import CompanyEnrichmentService
from app.services.discovery import ContactDiscoveryService


@pytest.mark.asyncio
@respx.mock
async def test_enrich_company_full_flow(sample_forager_org, sample_hubspot_company):
    """Test full workflow: resolve company, enrich from Forager, update HubSpot, discover contacts."""
    # 1. HubSpot GET company
    respx.get("https://api.hubapi.com/crm/v3/objects/companies/comp_101").respond(
        status_code=200,
        json=sample_hubspot_company,
    )

    # 2. Forager organization search
    respx.post("https://api-v2.forager.ai/api/123/datastorage/organization_search/").respond(
        status_code=200,
        json={"search_results": [sample_forager_org], "total_search_results": 1},
    )

    # 3. HubSpot PATCH company update
    patch_route = respx.patch("https://api.hubapi.com/crm/v3/objects/companies/comp_101").respond(
        status_code=200,
        json={"id": "comp_101", "properties": {"name": "OpenAI", "annualrevenue": "3700000000"}},
    )

    # 4. Forager person role search (5 people)
    mock_candidates = []
    for i in range(1, 6):
        mock_candidates.append(
            {
                "id": 100 + i,
                "role_title": f"Staff Software Engineer {i}",
                "person": {
                    "id": 200 + i,
                    "first_name": f"Engineer{i}",
                    "last_name": "Test",
                    "full_name": f"Engineer{i} Test",
                    "headline": f"Staff Software Engineer at OpenAI",
                    "linkedin_info": {
                        "public_identifier": f"engineer-{i}",
                        "public_profile_url": f"https://www.linkedin.com/in/engineer-{i}",
                    },
                    "location": {"name": "San Francisco, CA, USA"},
                },
            }
        )

    respx.post("https://api-v2.forager.ai/api/123/datastorage/person_role_search/").respond(
        status_code=200,
        json={"search_results": mock_candidates, "total_search_results": 5},
    )

    # 5. Forager phone / email lookups
    respx.post("https://api-v2.forager.ai/api/123/datastorage/person_contacts_lookup/phone_numbers/").respond(
        status_code=200,
        json=[{"phone_number": "+1-555-0100"}],
    )
    respx.post("https://api-v2.forager.ai/api/123/datastorage/person_contacts_lookup/personal_emails/").respond(
        status_code=200,
        json=[{"email": "engineer@test.com"}],
    )

    # 6. HubSpot search contact by email (returns None -> create new)
    respx.post("https://api.hubapi.com/crm/v3/objects/contacts/search").respond(
        status_code=200,
        json={"results": []},
    )

    # 7. HubSpot create contact
    respx.post("https://api.hubapi.com/crm/v3/objects/contacts").respond(
        status_code=201,
        json={"id": "new_contact_id", "properties": {"firstname": "Engineer"}},
    )

    # 8. HubSpot association v4
    respx.put(
        url__regex=r"https://api\.hubapi\.com/crm/v4/objects/contacts/.*/associations/companies/comp_101"
    ).respond(status_code=200, json={})

    # Execute service
    forager_client = ForagerClient(api_key="test_key", account_id=123)
    hubspot_client = HubSpotClient(access_token="test_token")
    discovery_service = ContactDiscoveryService(
        forager_client=forager_client,
        hubspot_client=hubspot_client,
        allowed_titles=["Software Engineer"],
        max_contacts=5,
    )
    service = CompanyEnrichmentService(
        forager_client=forager_client,
        hubspot_client=hubspot_client,
        discovery_service=discovery_service,
    )

    report = await service.enrich_company(company_id="comp_101")

    assert report.status == "success"
    assert report.company_id == "comp_101"
    assert report.company_name == "OpenAI"
    assert "annualrevenue" in report.properties_updated
    assert report.contacts_discovered_count == 5
    assert patch_route.called
    await forager_client.close()
    await hubspot_client.close()
