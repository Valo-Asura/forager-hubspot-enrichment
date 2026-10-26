"""HubSpot Company Webhook handler."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set
from fastapi import BackgroundTasks, HTTPException, Request

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.exceptions import WebhookSignatureVerificationError
from app.schemas import CompanyEnrichmentReport, HubSpotWebhookEvent
from app.services.companies import CompanyEnrichmentService

logger = logging.getLogger("forager_hubspot.webhooks.companies")

# In-memory deduplication set and processing cooldown cache (TTL in seconds)
PROCESSED_EVENTS: Dict[str, float] = {}
COMPANY_UPDATE_COOLDOWN: Dict[str, float] = {}
EVENT_TTL_SECONDS = 3600  # 1 hour
COOLDOWN_SECONDS = 30     # 30 seconds to prevent recursive webhook loops


def is_duplicate_event(event_key: str) -> bool:
    """Check if event was recently processed and purge expired entries."""
    now = time.time()
    # Cleanup expired keys
    expired = [k for k, ts in PROCESSED_EVENTS.items() if now - ts > EVENT_TTL_SECONDS]
    for k in expired:
        PROCESSED_EVENTS.pop(k, None)

    if event_key in PROCESSED_EVENTS:
        return True
    PROCESSED_EVENTS[event_key] = now
    return False


def is_in_cooldown(company_id: str) -> bool:
    """Check if company was updated by our service recently (prevents recursive loops)."""
    now = time.time()
    last_processed = COMPANY_UPDATE_COOLDOWN.get(company_id)
    if last_processed and (now - last_processed < COOLDOWN_SECONDS):
        return True
    return False


def set_cooldown(company_id: str) -> None:
    """Mark company as processed recently."""
    COMPANY_UPDATE_COOLDOWN[company_id] = time.time()


async def process_company_event(
    company_id: str,
    company_service: CompanyEnrichmentService,
) -> CompanyEnrichmentReport:
    """Background task to enrich company and discover contacts."""
    logger.info(f"[Webhook Worker] Processing company.creation for ID: {company_id}")
    set_cooldown(company_id)
    try:
        report = await company_service.enrich_company(
            company_id=company_id,
            discover_contacts=True,
        )
        logger.info(
            f"[Webhook Worker] Completed company {company_id}: updated {report.properties_updated}, discovered {report.contacts_discovered_count} contacts."
        )
        return report
    except Exception as e:
        logger.error(f"[Webhook Worker] Error processing company {company_id}: {e}", exc_info=True)
        return CompanyEnrichmentReport(
            status="error",
            company_id=company_id,
            errors=[str(e)],
        )


async def handle_company_webhook(
    request: Request,
    events: List[HubSpotWebhookEvent],
    background_tasks: BackgroundTasks,
    hubspot_client: HubSpotClient,
    company_service: CompanyEnrichmentService,
) -> Dict[str, Any]:
    """Validate and dispatch HubSpot company webhook events."""
    raw_body = await request.body()
    sig_v3 = request.headers.get("X-HubSpot-Signature-v3")
    sig_v1 = request.headers.get("X-HubSpot-Signature")
    timestamp = request.headers.get("X-HubSpot-Request-Timestamp")
    full_url = str(request.url)

    # Webhook signature validation
    is_valid = hubspot_client.verify_webhook_signature(
        signature_v3=sig_v3,
        signature_v1=sig_v1,
        timestamp=timestamp,
        request_url=full_url,
        request_body=raw_body,
        http_method=request.method,
    )
    if not is_valid:
        logger.warning("HubSpot company webhook rejected due to invalid signature.")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    accepted_count = 0
    skipped_count = 0

    for event in events:
        if event.subscriptionType != "company.creation":
            skipped_count += 1
            continue

        company_id = str(event.objectId)
        event_key = f"{event.subscriptionType}_{company_id}_{event.occurredAt}_{event.attemptNumber}"

        # Duplicate delivery check
        if is_duplicate_event(event_key):
            logger.info(f"Skipping duplicate company event delivery: {event_key}")
            skipped_count += 1
            continue

        # Recursive loop protection
        if is_in_cooldown(company_id):
            logger.info(f"Skipping company {company_id} currently in update cooldown.")
            skipped_count += 1
            continue

        background_tasks.add_task(process_company_event, company_id, company_service)
        accepted_count += 1

    return {
        "status": "accepted",
        "events_received": len(events),
        "events_dispatched": accepted_count,
        "events_skipped": skipped_count,
    }
