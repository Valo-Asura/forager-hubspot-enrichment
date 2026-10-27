"""Signed HubSpot webhook dispatch with basic retry and loop protection."""

import logging
import time
from typing import Any, Dict, List

from fastapi import BackgroundTasks, HTTPException, Request

from app.clients.hubspot import HubSpotClient
from app.schemas import HubSpotWebhookEvent
from app.services.companies import CompanyEnrichmentService
from app.services.contacts import ContactEnrichmentService

logger = logging.getLogger("forager_hubspot.webhooks")

EVENT_TTL_SECONDS = 3600
COOLDOWN_SECONDS = 30
processed_events: Dict[str, float] = {}
recent_records: Dict[str, float] = {}


def _was_processed(event: HubSpotWebhookEvent) -> bool:
    """Return true for a retry or a recently updated CRM record."""
    now = time.time()
    for key, timestamp in list(processed_events.items()):
        if now - timestamp > EVENT_TTL_SECONDS:
            processed_events.pop(key, None)
    for key, timestamp in list(recent_records.items()):
        if now - timestamp > COOLDOWN_SECONDS:
            recent_records.pop(key, None)

    event_id = event.eventId
    event_key = (
        f"{event.portalId}:{event.subscriptionId}:{event_id}"
        if event_id is not None
        else f"{event.subscriptionType}:{event.objectId}:{event.occurredAt}"
    )
    record_key = f"{event.subscriptionType}:{event.objectId}"
    if event_key in processed_events or record_key in recent_records:
        return True

    processed_events[event_key] = now
    recent_records[record_key] = now
    return False


async def handle_hubspot_webhook(
    request: Request,
    events: List[HubSpotWebhookEvent],
    background_tasks: BackgroundTasks,
    hubspot: HubSpotClient,
    companies: CompanyEnrichmentService,
    contacts: ContactEnrichmentService,
) -> Dict[str, Any]:
    """Verify one HubSpot delivery, then dispatch company/contact events."""
    valid = hubspot.verify_webhook_signature(
        signature_v3=request.headers.get("X-HubSpot-Signature-v3"),
        signature_v1=request.headers.get("X-HubSpot-Signature"),
        timestamp=request.headers.get("X-HubSpot-Request-Timestamp"),
        request_url=str(request.url),
        request_body=await request.body(),
        http_method=request.method,
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    accepted = 0
    skipped = 0
    for event in events:
        if event.subscriptionType not in {"company.creation", "contact.creation"}:
            skipped += 1
            continue
        if _was_processed(event):
            skipped += 1
            continue

        record_id = str(event.objectId)
        if event.subscriptionType == "company.creation":
            background_tasks.add_task(companies.enrich_company, company_id=record_id)
        else:
            background_tasks.add_task(contacts.enrich_contact, contact_id=record_id)
        accepted += 1

    logger.info("HubSpot webhook accepted=%s skipped=%s", accepted, skipped)
    return {
        "status": "accepted",
        "events_received": len(events),
        "events_dispatched": accepted,
        "events_skipped": skipped,
    }
