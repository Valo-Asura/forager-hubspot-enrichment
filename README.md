# Forager → HubSpot

A small FastAPI service that enriches a HubSpot company with Forager data, discovers up to five current contacts by job title, and processes signed HubSpot company/contact creation webhooks.

## API

| Method | Path | Purpose | Authentication |
| --- | --- | --- | --- |
| `GET` | `/health` | Health check | None |
| `POST` | `/api/v1/enrich/company` | Enrich a company and discover contacts | `MANUAL_API_KEY` bearer token |
| `POST` | `/webhooks/hubspot` | Handle `company.creation` and `contact.creation` | HubSpot signature v3/v1 |

Interactive request schemas are at `/docs`.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Add FORAGER_API_KEY, FORAGER_ACCOUNT_ID, HUBSPOT_ACCESS_TOKEN, and MANUAL_API_KEY.
uvicorn app.main:app --reload
```

`HUBSPOT_CLIENT_SECRET` is additionally required for signed webhooks. Keep credentials in environment variables; never commit `.env`.

## Test the API

Health check:

```bash
curl -i http://localhost:8000/health
```

Enrich a company and discover up to five contacts matching `ALLOWED_JOB_TITLES`:

```bash
curl -i -X POST http://localhost:8000/api/v1/enrich/company \
  -H "Authorization: Bearer $MANUAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"domain":"example.com"}'
```

Use a test company in a test HubSpot portal. The response reports changed company fields, discovered contacts, and provider errors. Missing source data stays blank; the service does not invent contact details.

HubSpot sends signed JSON event batches to `/webhooks/hubspot`. Configure both `company.creation` and `contact.creation` subscriptions to that URL. Requests with missing or invalid signatures return `401`; verify delivery by creating a test company/contact after setting `HUBSPOT_CLIENT_SECRET`.

Run automated tests:

```bash
pytest -q
```

## Production

Production URL: <https://forager-hubspot-enrichment.vercel.app>

- `GET /health` returns `200` when the service is live.
- Set `FORAGER_API_KEY`, `FORAGER_ACCOUNT_ID`, `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_CLIENT_SECRET`, `MANUAL_API_KEY`, and `APP_ENV=production` in Vercel project settings.
- Configure HubSpot's company and contact creation webhooks to `https://forager-hubspot-enrichment.vercel.app/webhooks/hubspot`.
- The production alias above is the working URL. The older generated deployment URL ending in `4rcnjndv1` is stale and returns a platform 404.

Vercel functions keep webhook deduplication state in memory. Use a durable queue and shared store before relying on retries across function instances.

## Evaluation notes

The HubSpot portal contains clearly labeled synthetic test contacts. A live Forager search may return fewer than five genuinely new people; existing records are skipped, and unavailable email/phone/location fields remain empty. Signed webhook delivery is pending the HubSpot client secret.
