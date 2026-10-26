"""HubSpot Contact Webhook handler."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from fastapi import BackgroundTasks, HTTPException, Request

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.exceptions import WebhookSignatureVerificationError
from app.schemas import ContactEnrichmentReport, HubSpotWebhookEvent
from app.services.contacts import ContactEnrichmentService

logger = logging.getLogger("forager_hubspot.webhooks.contacts")

# In-memory deduplication set and processing cooldown cache
PROCESSED_EVENTS: Dict[str, float] = {}
CONTACT_UPDATE_COOLDOWN: Dict[str, float] = {}
EVENT_TTL_SECONDS = 3600
COOLDOWN_SECONDS = 30


def is_duplicate_event(event_key: str) -> bool:
    """Check if contact event was recently processed."""
    now = time.time()
    expired = [k for k, ts in PROCESSED_EVENTS.items() if now - ts > EVENT_TTL_SECONDS]
    for k in expired:
        PROCESSED_EVENTS.pop(k, None)

    if event_key in PROCESSED_EVENTS:
        return True
    PROCESSED_EVENTS[event_key] = now
    return False


def is_in_cooldown(contact_id: str) -> bool:
    """Check if contact is in update cooldown."""
    now = time.time()
    last_processed = CONTACT_UPDATE_COOLDOWN.get(contact_id)
    if last_processed and (now - last_processed < COOLDOWN_SECONDS):
        return True
    return False


def set_cooldown(contact_id: str) -> None:
    """Mark contact as processed recently."""
    CONTACT_UPDATE_COOLDOWN[contact_id] = time.time()


async def process_contact_event(
    contact_id: str,
    contact_service: ContactEnrichmentService,
) -> ContactEnrichmentReport:
    """Background task to enrich contact and associate with company."""
    logger.info(f"[Webhook Worker] Processing contact.creation for ID: {contact_id}")
    set_cooldown(contact_id)
    try:
        report = await contact_service.enrich_contact(contact_id=contact_id)
        logger.info(
            f"[Webhook Worker] Completed contact {contact_id}: updated {report.properties_updated}, completeness: {report.completeness.get('completeness_percentage')}%"
        )
        return report
    except Exception as e:
        logger.error(f"[Webhook Worker] Error processing contact {contact_id}: {e}", exc_info=True)
        return ContactEnrichmentReport(
            status="error",
            contact_id=contact_id,
            errors=[str(e)],
        )


async def handle_contact_webhook(
    request: Request,
    events: List[HubSpotWebhookEvent],
    background_tasks: BackgroundTasks,
    hubspot_client: HubSpotClient,
    contact_service: ContactEnrichmentService,
) -> Dict[str, Any]:
    """Validate and dispatch HubSpot contact webhook events."""
    raw_body = await request.body()
    sig_v3 = request.headers.get("X-HubSpot-Signature-v3")
    sig_v1 = request.headers.get("X-HubSpot-Signature")
    timestamp = request.headers.get("X-HubSpot-Request-Timestamp")
    full_url = str(request.url)

    # Signature verification
    is_valid = hubspot_client.verify_webhook_signature(
        signature_v3=sig_v3,
        signature_v1=sig_v1,
        timestamp=timestamp,
        request_url=full_url,
        request_body=raw_body,
        http_method=request.method,
    )
    if not is_valid:
        logger.warning("HubSpot contact webhook rejected due to invalid signature.")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    accepted_count = 0
    skipped_count = 0

    for event in events:
        if event.subscriptionType != "contact.creation":
            skipped_count += 1
            continue

        contact_id = str(event.objectId)
        event_key = f"{event.subscriptionType}_{contact_id}_{event.occurredAt}_{event.attemptNumber}"

        if is_duplicate_event(event_key):
            logger.info(f"Skipping duplicate contact event delivery: {event_key}")
            skipped_count += 1
            continue

        if is_in_cooldown(contact_id):
            logger.info(f"Skipping contact {contact_id} currently in update cooldown.")
            skipped_count += 1
            continue

        background_tasks.add_task(process_contact_event, contact_id, contact_service)
        accepted_count += 1

    return {
        "status": "accepted",
        "events_received": len(events),
        "events_dispatched": accepted_count,
        "events_skipped": skipped_count,
    }
