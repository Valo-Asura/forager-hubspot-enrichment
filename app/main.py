"""Main FastAPI application entry point for Forager x HubSpot integration."""

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.config import Settings, get_settings
from app.logging_config import setup_logging
from app.schemas import (
    CompanyEnrichmentReport,
    ContactEnrichmentReport,
    DiscoverContactsRequest,
    EnrichCompanyRequest,
    EnrichContactRequest,
    HealthResponse,
    HubSpotWebhookEvent,
)
from app.services.companies import CompanyEnrichmentService
from app.services.contacts import ContactEnrichmentService
from app.services.discovery import ContactDiscoveryService
from app.webhooks.companies import handle_company_webhook
from app.webhooks.contacts import handle_contact_webhook

logger = logging.getLogger("forager_hubspot.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown hooks."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    logger.info(f"Starting Forager x HubSpot Integration Service (env: {settings.APP_ENV})")

    # Initialize shared clients
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
        forager_client=forager_client,
        hubspot_client=hubspot_client,
        allowed_titles=settings.allowed_job_titles_list,
        max_contacts=settings.MAX_CONTACTS_PER_COMPANY,
    )
    company_service = CompanyEnrichmentService(
        forager_client=forager_client,
        hubspot_client=hubspot_client,
        discovery_service=discovery_service,
    )
    contact_service = ContactEnrichmentService(
        forager_client=forager_client,
        hubspot_client=hubspot_client,
    )

    # Attach to app state for route dependency access
    app.state.settings = settings
    app.state.forager_client = forager_client
    app.state.hubspot_client = hubspot_client
    app.state.discovery_service = discovery_service
    app.state.company_service = company_service
    app.state.contact_service = contact_service

    if not settings.FORAGER_API_KEY:
        logger.warning("FORAGER_API_KEY is not configured. Live Forager calls will fail.")
    if not settings.HUBSPOT_ACCESS_TOKEN:
        logger.warning("HUBSPOT_ACCESS_TOKEN is not configured. Live HubSpot calls will fail.")
    if not settings.HUBSPOT_CLIENT_SECRET:
        logger.warning("HUBSPOT_CLIENT_SECRET is not configured. Webhook signature checks will be skipped.")

    yield

    # Clean shutdown
    logger.info("Shutting down Forager x HubSpot Integration Service...")
    await forager_client.close()
    await hubspot_client.close()


app = FastAPI(
    title="Forager x HubSpot AI Automation Service",
    description="Production-grade integration service for Forager data enrichment and HubSpot CRM automation.",
    version="0.1.0",
    lifespan=lifespan,
)

# Initialize state objects so they are immediately accessible in tests and requests
_initial_settings = get_settings()
_initial_forager = ForagerClient(
    api_key=_initial_settings.FORAGER_API_KEY,
    base_url=_initial_settings.FORAGER_BASE_URL,
    account_id=_initial_settings.FORAGER_ACCOUNT_ID,
)
_initial_hubspot = HubSpotClient(
    access_token=_initial_settings.HUBSPOT_ACCESS_TOKEN,
    client_secret=_initial_settings.HUBSPOT_CLIENT_SECRET,
    base_url=_initial_settings.HUBSPOT_BASE_URL,
)
_initial_discovery = ContactDiscoveryService(
    forager_client=_initial_forager,
    hubspot_client=_initial_hubspot,
    allowed_titles=_initial_settings.allowed_job_titles_list,
    max_contacts=_initial_settings.MAX_CONTACTS_PER_COMPANY,
)
_initial_company = CompanyEnrichmentService(
    forager_client=_initial_forager,
    hubspot_client=_initial_hubspot,
    discovery_service=_initial_discovery,
)
_initial_contact = ContactEnrichmentService(
    forager_client=_initial_forager,
    hubspot_client=_initial_hubspot,
)

app.state.settings = _initial_settings
app.state.forager_client = _initial_forager
app.state.hubspot_client = _initial_hubspot
app.state.discovery_service = _initial_discovery
app.state.company_service = _initial_company
app.state.contact_service = _initial_contact


@app.get("/", tags=["Info"])
async def root() -> Dict[str, Any]:
    """Root endpoint providing service metadata."""
    return {
        "service": "Forager x HubSpot AI Automation Service",
        "status": "operational",
        "documentation": "/docs",
        "health": "/health",
    }


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


# =============================================================================
# HubSpot Webhook Routes
# =============================================================================


@app.post("/webhooks/hubspot/companies", status_code=status.HTTP_200_OK, tags=["Webhooks"])
async def webhook_companies(
    request: Request,
    events: List[HubSpotWebhookEvent],
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Webhook listener for HubSpot company.creation events."""
    return await handle_company_webhook(
        request=request,
        events=events,
        background_tasks=background_tasks,
        hubspot_client=request.app.state.hubspot_client,
        company_service=request.app.state.company_service,
    )


@app.post("/webhooks/hubspot/contacts", status_code=status.HTTP_200_OK, tags=["Webhooks"])
async def webhook_contacts(
    request: Request,
    events: List[HubSpotWebhookEvent],
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Webhook listener for HubSpot contact.creation events."""
    return await handle_contact_webhook(
        request=request,
        events=events,
        background_tasks=background_tasks,
        hubspot_client=request.app.state.hubspot_client,
        contact_service=request.app.state.contact_service,
    )


@app.post("/webhooks/hubspot", status_code=status.HTTP_200_OK, tags=["Webhooks"])
async def webhook_unified(
    request: Request,
    events: List[HubSpotWebhookEvent],
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """
    Unified webhook endpoint that routes multiple subscription types
    (company.creation, contact.creation) dispatched to a single endpoint.
    """
    company_events = [e for e in events if e.subscriptionType == "company.creation"]
    contact_events = [e for e in events if e.subscriptionType == "contact.creation"]

    results: Dict[str, Any] = {"total_events": len(events)}

    if company_events:
        comp_res = await handle_company_webhook(
            request=request,
            events=company_events,
            background_tasks=background_tasks,
            hubspot_client=request.app.state.hubspot_client,
            company_service=request.app.state.company_service,
        )
        results["companies"] = comp_res

    if contact_events:
        cont_res = await handle_contact_webhook(
            request=request,
            events=contact_events,
            background_tasks=background_tasks,
            hubspot_client=request.app.state.hubspot_client,
            contact_service=request.app.state.contact_service,
        )
        results["contacts"] = cont_res

    return results


# =============================================================================
# Manual / On-Demand API Routes
# =============================================================================


@app.post("/api/v1/enrich/company", response_model=CompanyEnrichmentReport, tags=["Enrichment"])
async def manual_enrich_company(
    req: EnrichCompanyRequest,
    request: Request,
) -> CompanyEnrichmentReport:
    """Manually trigger enrichment for a company by ID or domain."""
    company_service: CompanyEnrichmentService = request.app.state.company_service
    return await company_service.enrich_company(
        company_id=req.company_id,
        domain=req.domain,
        discover_contacts=req.discover_contacts,
    )


@app.post("/api/v1/enrich/contact", response_model=ContactEnrichmentReport, tags=["Enrichment"])
async def manual_enrich_contact(
    req: EnrichContactRequest,
    request: Request,
) -> ContactEnrichmentReport:
    """Manually trigger enrichment for an individual contact by ID, email, or LinkedIn."""
    contact_service: ContactEnrichmentService = request.app.state.contact_service
    return await contact_service.enrich_contact(
        contact_id=req.contact_id,
        email=req.email,
        linkedin_url=req.linkedin_url,
    )


@app.post("/api/v1/discover/contacts", tags=["Discovery"])
async def manual_discover_contacts(
    req: DiscoverContactsRequest,
    request: Request,
) -> Dict[str, Any]:
    """Manually discover contacts for a company domain matching allowed job titles."""
    discovery_service: ContactDiscoveryService = request.app.state.discovery_service
    if req.job_titles:
        discovery_service.allowed_titles = req.job_titles
    if req.limit:
        discovery_service.max_contacts = req.limit

    contacts = await discovery_service.discover_and_sync_contacts(
        company_id=req.company_id or "",
        domain=req.domain,
    )
    return {
        "status": "success",
        "domain": req.domain,
        "discovered_count": len(contacts),
        "contacts": [c.model_dump() for c in contacts],
    }
