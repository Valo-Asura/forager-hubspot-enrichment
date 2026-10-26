"""HubSpot Webhooks package."""

from app.webhooks.companies import handle_company_webhook
from app.webhooks.contacts import handle_contact_webhook

__all__ = ["handle_company_webhook", "handle_contact_webhook"]
