"""Main FastAPI application entry point for Forager x HubSpot integration."""

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.config import get_settings
from app.logging_config import setup_logging
from app.schemas import CompanyEnrichmentReport, EnrichCompanyRequest, HealthResponse, HubSpotWebhookEvent
from app.services.companies import CompanyEnrichmentService
from app.services.contacts import ContactEnrichmentService
from app.services.discovery import ContactDiscoveryService
from app.webhooks import handle_hubspot_webhook

logger = logging.getLogger("forager_hubspot.main")
manual_api_bearer = HTTPBearer(auto_error=False)


def require_manual_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(manual_api_bearer),
) -> None:
    """Protect on-demand CRM writes when the app is deployed publicly."""
    settings = request.app.state.settings
    expected_key = settings.MANUAL_API_KEY

    if not expected_key:
        if settings.is_production:
            raise HTTPException(status_code=503, detail="Manual API authentication is not configured")
        return

    if credentials is None or not hmac.compare_digest(credentials.credentials, expected_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Set up logging and close shared API clients on shutdown."""
    setup_logging(application.state.settings.LOG_LEVEL)
    logger.info("Forager-HubSpot service started")
    yield
    await application.state.forager_client.close()
    await application.state.hubspot_client.close()


app = FastAPI(title="Forager-HubSpot", version="0.1.0", lifespan=lifespan)

# Keep one provider client and one service instance for the lifetime of the app.
settings = get_settings()
forager_client = ForagerClient(
    api_key=settings.FORAGER_API_KEY,
    base_url=settings.FORAGER_BASE_URL,
    account_id=settings.FORAGER_ACCOUNT_ID,
    timeout=settings.REQUEST_TIMEOUT_SECONDS,
    max_retries=settings.MAX_RETRIES,
)
hubspot_client = HubSpotClient(
    access_token=settings.HUBSPOT_ACCESS_TOKEN,
    client_secret=settings.HUBSPOT_CLIENT_SECRET,
    base_url=settings.HUBSPOT_BASE_URL,
    timeout=settings.REQUEST_TIMEOUT_SECONDS,
    max_retries=settings.MAX_RETRIES,
)
discovery_service = ContactDiscoveryService(
    forager_client,
    hubspot_client,
    allowed_titles=settings.allowed_job_titles_list,
    max_contacts=settings.MAX_CONTACTS_PER_COMPANY,
)
app.state.settings = settings
app.state.forager_client = forager_client
app.state.hubspot_client = hubspot_client
app.state.company_service = CompanyEnrichmentService(forager_client, hubspot_client, discovery_service)
app.state.contact_service = ContactEnrichmentService(forager_client, hubspot_client)

if not settings.FORAGER_API_KEY:
    logger.warning("FORAGER_API_KEY is not configured")
if not settings.HUBSPOT_ACCESS_TOKEN:
    logger.warning("HUBSPOT_ACCESS_TOKEN is not configured")
if not settings.HUBSPOT_CLIENT_SECRET:
    logger.warning("HUBSPOT_CLIENT_SECRET is not configured; webhook requests will be rejected")


@app.get("/", include_in_schema=False)
async def docs_home() -> RedirectResponse:
    """Send visitors to the API reference instead of a blank root page."""
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Service health probe endpoint."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app="forager-hubspot-enrichment",
        version="0.1.0",
        environment=settings.APP_ENV,
    )


# HubSpot webhook routes


@app.post("/webhooks/hubspot", status_code=status.HTTP_200_OK, tags=["Webhooks"])
async def webhook_unified(
    request: Request,
    events: List[HubSpotWebhookEvent],
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Handle company.creation and contact.creation subscriptions."""
    return await handle_hubspot_webhook(
        request,
        events,
        background_tasks,
        request.app.state.hubspot_client,
        request.app.state.company_service,
        request.app.state.contact_service,
    )


# Manual API routes


@app.post(
    "/api/v1/enrich/company",
    response_model=CompanyEnrichmentReport,
    tags=["Enrichment"],
    dependencies=[Depends(require_manual_api_key)],
)
async def manual_enrich_company(
    req: EnrichCompanyRequest,
    request: Request,
) -> CompanyEnrichmentReport:
    """Manually trigger enrichment for a company by ID or domain."""
    company_service: CompanyEnrichmentService = request.app.state.company_service
    return await company_service.enrich_company(
        domain=req.domain,
    )
