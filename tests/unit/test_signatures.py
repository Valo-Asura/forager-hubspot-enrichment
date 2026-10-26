"""Unit tests for HubSpot webhook signature validation (v3 and v1)."""

import hashlib
import time
import pytest
from app.clients.hubspot import HubSpotClient
from tests.conftest import create_hubspot_v3_signature


def test_verify_webhook_signature_v3_valid():
    """Test successful verification with valid HubSpot v3 signature."""
    client = HubSpotClient(access_token="test", client_secret="my_secret_key")
    url = "https://my-app.railway.app/webhooks/hubspot/companies"
    body = b'[{"objectId": 123, "subscriptionType": "company.creation"}]'
    timestamp = str(int(time.time() * 1000))

    valid_sig = create_hubspot_v3_signature(
        client_secret="my_secret_key",
        method="POST",
        url=url,
        body=body.decode("utf-8"),
        timestamp=timestamp,
    )

    is_valid = client.verify_webhook_signature(
        signature_v3=valid_sig,
        timestamp=timestamp,
        request_url=url,
        request_body=body,
        http_method="POST",
    )
    assert is_valid is True


def test_verify_webhook_signature_v3_tampered_body():
    """Test rejection when payload body has been tampered with."""
    client = HubSpotClient(access_token="test", client_secret="my_secret_key")
    url = "https://my-app.railway.app/webhooks/hubspot/companies"
    body = b'[{"objectId": 123}]'
    timestamp = str(int(time.time() * 1000))

    valid_sig = create_hubspot_v3_signature(
        client_secret="my_secret_key",
        method="POST",
        url=url,
        body=body.decode("utf-8"),
        timestamp=timestamp,
    )

    tampered_body = b'[{"objectId": 999}]'
    is_valid = client.verify_webhook_signature(
        signature_v3=valid_sig,
        timestamp=timestamp,
        request_url=url,
        request_body=tampered_body,
        http_method="POST",
    )
    assert is_valid is False


def test_verify_webhook_signature_v3_expired_timestamp():
    """Test rejection when timestamp is older than 5 minutes (300,000 ms)."""
    client = HubSpotClient(access_token="test", client_secret="my_secret_key")
    url = "https://my-app.railway.app/webhooks/hubspot/companies"
    body = b'[{"objectId": 123}]'
    old_timestamp = str(int((time.time() - 400) * 1000))  # 400 seconds ago

    sig = create_hubspot_v3_signature(
        client_secret="my_secret_key",
        method="POST",
        url=url,
        body=body.decode("utf-8"),
        timestamp=old_timestamp,
    )

    is_valid = client.verify_webhook_signature(
        signature_v3=sig,
        timestamp=old_timestamp,
        request_url=url,
        request_body=body,
        http_method="POST",
    )
    assert is_valid is False


def test_verify_webhook_signature_v1_valid():
    """Test fallback verification with v1 SHA-256 signature."""
    client = HubSpotClient(access_token="test", client_secret="my_secret_key")
    body = b'[{"objectId": 123}]'
    source = f"my_secret_key{body.decode('utf-8')}"
    v1_sig = hashlib.sha256(source.encode("utf-8")).hexdigest()

    is_valid = client.verify_webhook_signature(
        signature_v1=v1_sig,
        request_body=body,
    )
    assert is_valid is True


def test_verify_webhook_signature_rejects_when_client_secret_missing():
    client = HubSpotClient(access_token="test-token", client_secret="")
    assert client.verify_webhook_signature(
        signature_v1="anything",
        request_body=b"[]",
    ) is False
