"""Pytest fixtures and mock data for unit and integration testing."""

import base64
import hashlib
import hmac
import time
from typing import Any, AsyncGenerator, Dict, List
import httpx
import pytest
import pytest_asyncio
import respx

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.config import Settings
from app.main import app
from app.services.companies import CompanyEnrichmentService
from app.services.contacts import ContactEnrichmentService
from app.services.discovery import ContactDiscoveryService


@pytest.fixture
def mock_settings() -> Settings:
    """Fixture providing testing settings."""
    return Settings(
        FORAGER_API_KEY="test_forager_key",
        FORAGER_BASE_URL="https://api-v2.forager.ai",
        FORAGER_ACCOUNT_ID=12345,
        HUBSPOT_ACCESS_TOKEN="test_hubspot_token",
        HUBSPOT_CLIENT_SECRET="test_client_secret",
        HUBSPOT_BASE_URL="https://api.hubapi.com",
        ALLOWED_JOB_TITLES="Software Engineer,VP of Engineering,CTO,Product Manager",
        MAX_CONTACTS_PER_COMPANY=5,
        APP_ENV="test",
        LOG_LEVEL="DEBUG",
    )


@pytest.fixture
def sample_forager_org() -> Dict[str, Any]:
    """Sample raw Forager organization search result for OpenAI."""
    return {
        "id": 99991,
        "name": "OpenAI",
        "legal_name": "OpenAI, Inc.",
        "domain": "openai.com",
        "website": "https://openai.com",
        "description": "OpenAI is an AI research and deployment company dedicated to ensuring artificial general intelligence benefits all of humanity.",
        "founded_date": "2015-12-11",
        "operating_status": "active",
        "employees_amount": 1500,
        "employees_range": "1001-5000",
        "domain_rank": 85,
        "finance_info": {
            "revenue": 3700000000
        },
        "linkedin_info": {
            "public_identifier": "openai",
            "public_profile_url": "https://www.linkedin.com/company/openai"
        },
        "location": {
            "name": "San Francisco, California, United States",
            "osm_locations": [
                {"name": "San Francisco", "place_type": "city"},
                {"name": "California", "place_type": "state"},
                {"name": "United States", "place_type": "country"}
            ]
        },
        "keywords": [{"name": "Artificial Intelligence"}, {"name": "Machine Learning"}, {"name": "NLP"}]
    }


@pytest.fixture
def sample_forager_person() -> Dict[str, Any]:
    """Sample raw Forager person detail lookup result."""
    return {
        "id": 8881,
        "first_name": "Mira",
        "last_name": "Murati",
        "full_name": "Mira Murati",
        "headline": "Former CTO at OpenAI",
        "description": "Experienced technology leader focused on generative models and safety systems.",
        "gender": "female",
        "photo": "https://media.licdn.com/dms/image/v2/test.jpg",
        "linkedin_info": {
            "public_identifier": "miramurati",
            "public_profile_url": "https://www.linkedin.com/in/miramurati"
        },
        "location": {
            "name": "San Francisco, California, United States",
            "osm_locations": [
                {"name": "San Francisco", "place_type": "city"},
                {"name": "California", "place_type": "state"},
                {"name": "United States", "place_type": "country"}
            ]
        },
        "skills": [{"name": "Deep Learning"}, {"name": "Product Strategy"}, {"name": "Engineering Leadership"}],
        "roles": [
            {
                "role_title": "Chief Technology Officer",
                "is_current": True,
                "organization": {"name": "OpenAI", "domain": "openai.com"}
            }
        ]
    }


@pytest.fixture
def sample_hubspot_company() -> Dict[str, Any]:
    """Sample HubSpot CRM company object."""
    return {
        "id": "comp_101",
        "properties": {
            "name": "OpenAI",
            "domain": "openai.com",
            "website": "https://openai.com",
            "annualrevenue": None,
            "numberofemployees": None,
            "city": None,
            "state": None,
            "country": None,
            "linkedin_company_page": None,
        }
    }


@pytest.fixture
def sample_hubspot_contact() -> Dict[str, Any]:
    """Sample HubSpot CRM contact object."""
    return {
        "id": "cont_201",
        "properties": {
            "firstname": "Mira",
            "lastname": "Murati",
            "email": "mira@openai.com",
            "phone": None,
            "jobtitle": None,
            "company": "OpenAI",
            "hs_linkedin_url": "https://www.linkedin.com/in/miramurati",
            "city": None,
            "state": None,
            "country": None,
            "associatedcompanyid": "comp_101",
        }
    }


def create_hubspot_v3_signature(
    client_secret: str,
    method: str,
    url: str,
    body: str,
    timestamp: str,
) -> str:
    """Helper to compute valid HubSpot v3 signature for tests."""
    source_string = f"{method.upper()}{url}{body}{timestamp}"
    computed_hash = hmac.new(
        key=client_secret.encode("utf-8"),
        msg=source_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(computed_hash).decode("utf-8")
