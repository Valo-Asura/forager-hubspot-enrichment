"""Unit tests for Forager and HubSpot API clients with mocked HTTP calls."""

import httpx
import pytest
import respx
from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.exceptions import ForagerAPIError, HubSpotAPIError


@pytest.mark.asyncio
async def test_forager_get_account_id_cached():
    """Test using pre-configured account ID without extra API call."""
    client = ForagerClient(api_key="test_key", account_id=456)
    account_id = await client.get_account_id()
    assert account_id == 456


@pytest.mark.asyncio
async def test_forager_account_id_required():
    """Do not call an undocumented endpoint to infer the Forager account ID."""
    client = ForagerClient(api_key="test_key")
    with pytest.raises(ForagerAPIError, match="FORAGER_ACCOUNT_ID is required"):
        await client.get_account_id()
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_forager_search_organization_success(sample_forager_org):
    """Test searching organization by domain via Forager client."""
    respx.post("https://api-v2.forager.ai/api/123/datastorage/organization_search/").respond(
        status_code=200,
        json={"search_results": [sample_forager_org], "total_search_results": 1},
    )

    client = ForagerClient(api_key="test_key", account_id=123)
    result = await client.search_organization("openai.com")
    assert result is not None
    assert result["name"] == "OpenAI"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_hubspot_get_company(sample_hubspot_company):
    """Test fetching company by ID from HubSpot."""
    respx.get("https://api.hubapi.com/crm/v3/objects/companies/comp_101").respond(
        status_code=200,
        json=sample_hubspot_company,
    )

    client = HubSpotClient(access_token="test_token")
    company = await client.get_company("comp_101")
    assert company["id"] == "comp_101"
    assert company["properties"]["name"] == "OpenAI"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_hubspot_association_v4_success():
    """Test creating contact to company association in HubSpot CRM."""
    respx.put("https://api.hubapi.com/crm/v4/objects/contacts/cont_1/associations/companies/comp_1").respond(
        status_code=200,
        json={"results": [{"fromObjectId": "cont_1", "toObjectId": "comp_1"}]},
    )

    client = HubSpotClient(access_token="test_token")
    # Should complete without error
    await client.associate_contact_to_company("cont_1", "comp_1")
    await client.close()
