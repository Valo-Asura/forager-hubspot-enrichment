"""Integration tests for FastAPI HTTP routes, health checks, and webhooks."""

import json
import time
import httpx
import pytest
from app.main import app
from tests.conftest import create_hubspot_v3_signature


@pytest.mark.asyncio
async def test_health_endpoint():
    """Test GET /health returns 200 and operational status."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["app"] == "forager-hubspot-enrichment"


@pytest.mark.asyncio
async def test_root_endpoint():
    """Test GET / returns service information."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "documentation" in data


@pytest.mark.asyncio
async def test_company_webhook_success_and_deduplication():
    """Test company.creation webhook acceptance and duplicate rejection."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = [
            {
                "eventId": 1001,
                "subscriptionId": 55,
                "portalId": 12345,
                "occurredAt": int(time.time() * 1000),
                "subscriptionType": "company.creation",
                "attemptNumber": 0,
                "objectId": 987654,
            }
        ]
        body_bytes = json.dumps(payload).encode("utf-8")
        timestamp = str(int(time.time() * 1000))
        url = "http://test/webhooks/hubspot/companies"

        secret = app.state.settings.HUBSPOT_CLIENT_SECRET or "test_secret"
        app.state.hubspot_client.client_secret = secret

        sig_v3 = create_hubspot_v3_signature(
            client_secret=secret,
            method="POST",
            url=url,
            body=body_bytes.decode("utf-8"),
            timestamp=timestamp,
        )

        headers = {
            "Content-Type": "application/json",
            "X-HubSpot-Signature-v3": sig_v3,
            "X-HubSpot-Request-Timestamp": timestamp,
        }

        # 1. First delivery -> accepted
        resp1 = await client.post("/webhooks/hubspot/companies", content=body_bytes, headers=headers)
        assert resp1.status_code == 200
        assert resp1.json()["events_dispatched"] == 1

        # 2. Duplicate delivery -> skipped
        resp2 = await client.post("/webhooks/hubspot/companies", content=body_bytes, headers=headers)
        assert resp2.status_code == 200
        assert resp2.json()["events_skipped"] == 1
        assert resp2.json()["events_dispatched"] == 0


@pytest.mark.asyncio
async def test_company_webhook_retry_attempt_is_deduplicated():
    """A HubSpot retry with an incremented attempt number is the same event."""
    payload = [{
        "eventId": 1002,
        "subscriptionId": 12,
        "portalId": 34,
        "subscriptionType": "company.creation",
        "objectId": 5678,
        "occurredAt": 1700000000000,
        "attemptNumber": 0,
    }]
    body0 = json.dumps(payload).encode()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        secret = "retry-test-secret"
        app.state.hubspot_client.client_secret = secret
        url = "http://test/webhooks/hubspot/companies"
        timestamp0 = str(int(time.time() * 1000))
        headers0 = {
            "Content-Type": "application/json",
            "X-HubSpot-Signature-v3": create_hubspot_v3_signature(
                client_secret=secret,
                method="POST",
                url=url,
                body=body0.decode(),
                timestamp=timestamp0,
            ),
            "X-HubSpot-Request-Timestamp": timestamp0,
        }
        response0 = await client.post("/webhooks/hubspot/companies", content=body0, headers=headers0)
        assert response0.status_code == 200, response0.text
        assert response0.json()["events_dispatched"] == 1, response0.text

        payload[0]["attemptNumber"] = 1
        body1 = json.dumps(payload).encode()
        timestamp1 = str(int(time.time() * 1000))
        headers1 = {
            "Content-Type": "application/json",
            "X-HubSpot-Signature-v3": create_hubspot_v3_signature(
                client_secret=secret,
                method="POST",
                url=url,
                body=body1.decode(),
                timestamp=timestamp1,
            ),
            "X-HubSpot-Request-Timestamp": timestamp1,
        }
        response1 = await client.post("/webhooks/hubspot/companies", content=body1, headers=headers1)
        assert response1.json()["events_dispatched"] == 0
        assert response1.json()["events_skipped"] == 1


@pytest.mark.asyncio
async def test_contact_webhook_signature_failure():
    """Test contact webhook rejection with 401 on forged signature."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = [
            {
                "eventId": 2001,
                "subscriptionType": "contact.creation",
                "objectId": 444,
            }
        ]
        body_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-HubSpot-Signature-v3": "forged_signature_value",
            "X-HubSpot-Request-Timestamp": str(int(time.time() * 1000)),
        }
        app.state.hubspot_client.client_secret = "real_secret"

        resp = await client.post("/webhooks/hubspot/contacts", content=body_bytes, headers=headers)
        assert resp.status_code == 401
