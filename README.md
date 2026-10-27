# Forager × HubSpot

A small FastAPI service for enriching HubSpot companies and contacts with Forager data.

## What it does

- Enriches a company and discovers up to five matching contacts.
- Handles signed HubSpot company and contact creation webhooks.
- Leaves unavailable source fields blank rather than inventing data.

## API

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/health` | Health check | Public |
| `POST` | `/api/v1/enrich/company` | Enrich a company and find contacts | `MANUAL_API_KEY` bearer token |
| `POST` | `/webhooks/hubspot` | Process company/contact events | HubSpot signature |

Interactive API docs: [`/docs`](https://forager-hubspot-enrichment.vercel.app/docs).

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

Set the Forager and HubSpot credentials in `.env`. `HUBSPOT_CLIENT_SECRET` is needed to validate live webhook signatures. Keep `.env` out of Git.

Run the test suite with:

```bash
pytest -q
```

## Live service

- API: <https://forager-hubspot-enrichment.vercel.app>
- Source: <https://github.com/Valo-Asura/forager-hubspot-enrichment>

The health check returns `200`. The last live Forager enrichment request returned `402` for insufficient credits, so the five-contact, full-field dataset still needs a successful run with available credits. Missing email, phone, or location data is left blank.

Live HubSpot webhook processing also needs `HUBSPOT_CLIENT_SECRET` configured in the Vercel project and the matching HubSpot webhook subscriptions.
