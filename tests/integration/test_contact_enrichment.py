"""Integration tests for end-to-end contact enrichment."""

import pytest
import respx
from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.services.contacts import ContactEnrichmentService


@pytest.mark.asyncio
@respx.mock
async def test_enrich_contact_full_flow(sample_forager_person, sample_hubspot_contact):
    """Test full contact enrichment workflow: resolve, fetch from Forager, update CRM, associate."""
    # 1. HubSpot GET contact
    respx.get("https://api.hubapi.com/crm/v3/objects/contacts/cont_201").respond(
        status_code=200,
        json=sample_hubspot_contact,
    )

    # 2. Forager reverse lookup by email
    respx.post("https://api-v2.forager.ai/api/123/datastorage/person_detail_reverse_lookup/by_email/").respond(
        status_code=200,
        json=sample_forager_person,
    )

    # 3. Forager phone lookup
    respx.post("https://api-v2.forager.ai/api/123/datastorage/person_contacts_lookup/phone_numbers/").respond(
        status_code=200,
        json=[{"phone_number": "+1-555-0199"}],
    )

    # 4. Forager personal emails lookup
    respx.post("https://api-v2.forager.ai/api/123/datastorage/person_contacts_lookup/personal_emails/").respond(
        status_code=200,
        json=[{"email": "mira.personal@test.com"}],
    )

    # 5. HubSpot PATCH contact update
    patch_route = respx.patch("https://api.hubapi.com/crm/v3/objects/contacts/cont_201").respond(
        status_code=200,
        json={"id": "cont_201", "properties": {"firstname": "Mira"}},
    )

    forager_client = ForagerClient(api_key="test_key", account_id=123)
    hubspot_client = HubSpotClient(access_token="test_token")
    service = ContactEnrichmentService(forager_client=forager_client, hubspot_client=hubspot_client)

    report = await service.enrich_contact(contact_id="cont_201")

    assert report.status == "success"
    assert report.contact_id == "cont_201"
    assert report.name == "Mira Murati"
    assert "firstname" in report.properties_updated
    assert "phone" in report.properties_updated
    assert report.completeness["completeness_percentage"] > 70.0
    assert patch_route.called

    await forager_client.close()
    await hubspot_client.close()
