# Forager × HubSpot AI Automation Integration

Production-grade, deployable Python integration connecting **Forager.ai** data enrichment with **HubSpot CRM**. The service enriches companies and contacts, discovers target candidates using configurable job-title filtering, and processes real-time HubSpot webhooks asynchronously with signature validation and deduplication.

Built in Python using FastAPI, Uvicorn, httpx, and Pydantic. **Zero no-code tools (no n8n, Make, or Zapier).**

---

## Table of Contents
1. [Architecture & Data Flow](#architecture--data-flow)
2. [Verified API Contracts](#verified-api-contracts)
3. [Prerequisites & Permissions](#prerequisites--permissions)
4. [Project Structure](#project-structure)
5. [Local Setup & Execution](#local-setup--execution)
6. [Environment Configuration](#environment-configuration)
7. [Running Tests](#running-tests)
8. [Features & Capabilities](#features--capabilities)
   - [Company Enrichment](#company-enrichment)
   - [Contact Enrichment & Completeness](#contact-enrichment--completeness)
   - [Contact Discovery & Title Filtering](#contact-discovery--title-filtering)
   - [Webhook Automation & Signature Verification](#webhook-automation--signature-verification)
9. [OpenAI Demo Records & Execution](#openai-demo-records--execution)
10. [Railway Production Deployment](#railway-production-deployment)
11. [Known Provider Limitations](#known-provider-limitations)
12. [Forager Extra Fields for Team Discussion](#forager-extra-fields-for-team-discussion)
13. [Video Walkthrough Script](#video-walkthrough-script)

---

## Architecture & Data Flow

```
+-----------------------------------------------------------------------------------+
|                                  HubSpot CRM                                      |
|                                                                                   |
|  Company Created Webhook                      Contact Created Webhook             |
+---------------------+------------------------------------+------------------------+
                      |                                    |
                      v (HTTPS POST with SHA-256 HMAC)     v
+---------------------+------------------------------------+------------------------+
|                      FastAPI Automation Service (Railway / Local)                 |
|                                                                                   |
|  1. Verify Signature (X-HubSpot-Signature-v3 with Timestamp & Replay Guard)       |
|  2. Idempotency Check (Filter duplicate eventId deliveries)                      |
|  3. Cooldown Guard (Prevent recursive CRM update loops)                           |
|  4. Background Task Dispatch (Fast HTTP 200/202 acknowledgment)                   |
+---------------------+------------------------------------+------------------------+
                      |                                    |
                      v                                    v
+---------------------+------------------------------------+------------------------+
|                                 Services Layer                                    |
|                                                                                   |
|  - CompanyEnrichmentService: Resolves company, fetches Forager firmographics     |
|  - ContactDiscoveryService: Queries roles, normalizes & fuzzy-matches job titles  |
|  - ContactEnrichmentService: Reverse lookups, verified emails & phone numbers     |
|  - Mapping & Normalization: Extracts city/state/country, maps CRM properties      |
+---------------------+------------------------------------+------------------------+
                      |                                    |
                      v                                    v
+---------------------+------------------------------------+------------------------+
|              Forager API v2                               HubSpot API v3/v4       |
|  - POST .../organization_search/             - PATCH /crm/v3/objects/companies/{id}|
|  - POST .../person_role_search/               - POST /crm/v3/objects/contacts      |
|  - POST .../person_detail_lookup/            - PATCH /crm/v3/objects/contacts/{id}|
|  - POST .../person_contacts_lookup/phones/   - PUT /crm/v4/.../associations/      |
|  - POST .../person_contacts_lookup/emails/                                        |
+-----------------------------------------------------------------------------------+
```

---

## Verified API Contracts

### 1. Forager.ai API (v2)
* **Base URL:** `https://api-v2.forager.ai`
* **Authentication Header:** `X-API-KEY: <FORAGER_API_KEY>`
* **Account Resolution:** `GET /api/users/current/` retrieves the active account ID dynamically if `FORAGER_ACCOUNT_ID` is not explicitly set.
* **Organization Search:**
  * `POST /api/{account_id}/datastorage/organization_search/`
  * Body: `{"domains": ["openai.com"], "page": 0}`
  * Response: `{ "search_results": [ { "name", "domain", "website", "description", "employees_amount", "finance_info": {"revenue"}, "linkedin_info": {"public_profile_url"}, "location": {"osm_locations": [...]}, "founded_date": ... } ] }`
* **Person Role Search (Discovery):**
  * `POST /api/{account_id}/datastorage/person_role_search/`
  * Body: `{"organization_domains": ["openai.com"], "role_title": "Software Engineer", "role_is_current": true, "page": 0}`
  * Response: `{ "search_results": [ { "role_title", "is_current", "person": { "id", "first_name", "last_name", "headline", "linkedin_info": {"public_identifier", "public_profile_url"}, "location": ... } } ] }`
* **Person Contacts Lookup:**
  * Phone numbers: `POST /api/{account_id}/datastorage/person_contacts_lookup/phone_numbers/` with `{"person_id": int}` or `{"linkedin_public_identifier": str}`
  * Personal emails: `POST /api/{account_id}/datastorage/person_contacts_lookup/personal_emails/` with `{"person_id": int}`
  * Work emails: `POST /api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/`

### 2. HubSpot CRM API (v3/v4)
* **Base URL:** `https://api.hubapi.com`
* **Authentication Header:** `Authorization: Bearer <HUBSPOT_ACCESS_TOKEN>`
* **Company Endpoints:**
  * Search: `POST /crm/v3/objects/companies/search`
  * Read: `GET /crm/v3/objects/companies/{companyId}?properties=...`
  * Create: `POST /crm/v3/objects/companies`
  * Update: `PATCH /crm/v3/objects/companies/{companyId}`
* **Contact Endpoints:**
  * Search: `POST /crm/v3/objects/contacts/search`
  * Read: `GET /crm/v3/objects/contacts/{contactId}?properties=...`
  * Create: `POST /crm/v3/objects/contacts`
  * Update: `PATCH /crm/v3/objects/contacts/{contactId}`
* **Associations Endpoint:**
  * `PUT /crm/v4/objects/contacts/{contactId}/associations/companies/{companyId}` with category `HUBSPOT_DEFINED` and type ID `1` (Primary Contact to Company).

---

## Prerequisites & Permissions

### HubSpot Private App Scopes
Create a Private App in your HubSpot portal (**Settings -> Integrations -> Private Apps**):
* `crm.objects.companies.read`
* `crm.objects.companies.write`
* `crm.objects.contacts.read`
* `crm.objects.contacts.write`
* `crm.schemas.custom.read`

### Forager Account
* Sign up at [app.forager.ai](https://app.forager.ai) (150 free credits provided upon signup).
* Navigate to **Settings -> API Keys** and generate an API key.

---

## Project Structure

```
forager-hubspot-enrichment/
├── app/
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── forager.py            # Async client for Forager REST API v2
│   │   └── hubspot.py            # Async client for HubSpot CRM v3/v4 & v3 signature checks
│   ├── services/
│   │   ├── __init__.py
│   │   ├── companies.py          # Company enrichment orchestration
│   │   ├── contacts.py           # Contact enrichment & completeness calculation
│   │   ├── discovery.py          # Role searching & fuzzy job-title matching
│   │   └── mapping.py            # Provider field normalization & OSM location parsing
│   ├── webhooks/
│   │   ├── __init__.py
│   │   ├── companies.py          # HubSpot company.creation webhook handler
│   │   └── contacts.py           # HubSpot contact.creation webhook handler
│   ├── config.py                 # Pydantic BaseSettings & env resolution
│   ├── exceptions.py             # Custom domain exceptions
│   ├── logging_config.py         # Structured logging with secret redaction
│   ├── main.py                   # FastAPI application & lifespan management
│   └── schemas.py                # Pydantic models & reports
├── scripts/
│   ├── __init__.py
│   ├── setup_hubspot.py          # Schema pre-flight inspection
│   ├── enrich_demo_company.py    # Primary deliverable execution script
│   └── validate_demo_records.py  # Production audit & completeness validation
├── tests/
│   ├── conftest.py               # Mock fixtures & signature generator
│   ├── unit/
│   │   ├── test_clients.py       # Client retry logic & error handling
│   │   ├── test_discovery.py     # Job-title variations & deduplication tests
│   │   ├── test_mapping.py       # Mapping, OSM locations, & completeness tests
│   │   └── test_signatures.py    # HubSpot v3/v1 signature verification tests
│   └── integration/
│       ├── test_company_enrichment.py  # End-to-end company flow (respx mocked)
│       ├── test_contact_enrichment.py  # End-to-end contact flow (respx mocked)
│       └── test_webhooks.py            # HTTP webhook endpoints & loop protection
├── .env.example
├── .gitignore
├── Dockerfile
├── Procfile                      # Railway deployment start command
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Local Setup & Execution

### 1. Clone & Create Virtual Environment
```bash
cd forager-hubspot-enrichment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your FORAGER_API_KEY, HUBSPOT_ACCESS_TOKEN, and HUBSPOT_CLIENT_SECRET
```

### 3. Start Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Interactive OpenAPI documentation will be accessible at: `http://localhost:8000/docs`.

---

## Environment Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `FORAGER_API_KEY` | Yes | `""` | API key from app.forager.ai |
| `FORAGER_BASE_URL` | No | `https://api-v2.forager.ai` | Base URL for Forager v2 |
| `FORAGER_ACCOUNT_ID`| No | Auto-resolved | Numeric account ID; resolved via `/api/users/current/` if omitted |
| `HUBSPOT_ACCESS_TOKEN` | Yes | `""` | Private App Bearer Token |
| `HUBSPOT_CLIENT_SECRET` | For Webhooks | `""` | App client secret for SHA-256 HMAC signature validation |
| `HUBSPOT_BASE_URL` | No | `https://api.hubapi.com` | Base URL for HubSpot CRM |
| `ALLOWED_JOB_TITLES` | No | `Software Engineer,VP of Engineering,CTO,Product Manager` | Comma-separated title filters |
| `MAX_CONTACTS_PER_COMPANY` | No | `5` | Maximum contacts to discover per company |
| `PORT` | No | `8000` | Port assigned by Railway or local dev |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |

---

## Running Tests

The test suite contains **44 unit and integration tests** testing field mapping, title filtering, candidate deduplication, webhook signature checks, and full end-to-end workflows. Tests use `respx` and never depend on live external credentials.

Run all tests:
```bash
pytest -v
```

Expected output:
```
tests/integration/test_company_enrichment.py::test_enrich_company_full_flow PASSED
tests/integration/test_contact_enrichment.py::test_enrich_contact_full_flow PASSED
tests/integration/test_webhooks.py::test_health_endpoint PASSED
tests/integration/test_webhooks.py::test_root_endpoint PASSED
tests/integration/test_webhooks.py::test_company_webhook_success_and_deduplication PASSED
tests/integration/test_webhooks.py::test_contact_webhook_signature_failure PASSED
tests/unit/test_clients.py::test_forager_get_account_id_cached PASSED
tests/unit/test_clients.py::test_forager_resolve_account_id_api PASSED
tests/unit/test_clients.py::test_forager_search_organization_success PASSED
tests/unit/test_clients.py::test_hubspot_get_company PASSED
tests/unit/test_clients.py::test_hubspot_association_v4_success PASSED
tests/unit/test_discovery.py (23 parameterized title tests) PASSED
tests/unit/test_mapping.py (6 mapping & location tests) PASSED
tests/unit/test_signatures.py (4 signature verification tests) PASSED

============================== 44 passed in 1.06s ==============================
```

---

## Features & Capabilities

### Company Enrichment
* Resolves company record from HubSpot by domain or record ID.
* Queries Forager `organization_search`.
* Normalizes firmographic attributes (`description`, `annualrevenue`, `numberofemployees`, `domain`, `website`, `linkedin_company_page`, `city`, `state`, `country`).
* Preserves existing non-empty HubSpot data when provider data is missing.
* Updates HubSpot record using `PATCH /crm/v3/objects/companies/{companyId}` without duplicate creation.

### Contact Enrichment & Completeness
* Resolves contact in HubSpot by ID, email, or LinkedIn URL.
* Enriches via Forager email reverse lookup or person detail lookup.
* Fetches verified direct dials and personal/work emails.
* Parses multi-part city, state, country from OSM geolocation attributes.
* **Never fabricates data**: Computes an audit report with completeness percentage (`populated_count`, `populated_fields`, `missing_count`, `missing_fields`).

### Contact Discovery & Title Filtering
* Configurable filtering using `ALLOWED_JOB_TITLES` env variable.
* Case-insensitive matching with title variation and acronym expansion:
  * `"CTO"` matches `"Chief Technology Officer"`, `"CTO & Co-Founder"`, `"Interim CTO"`.
  * `"VP of Engineering"` matches `"Vice President of Engineering"`, `"VP Engineering"`, `"VP, Engineering"`.
  * `"Software Engineer"` matches `"Staff Software Engineer"`, `"Senior Software Engineer"`, `"Principal Software Engineer"`.
* Candidate deduplication by LinkedIn slug and email before inserting into CRM.
* Searches HubSpot CRM before inserting to update existing records rather than duplicating.
* Associates discovered contacts with the company using primary Contact-to-Company relationship.

### Webhook Automation & Signature Verification
* Current HubSpot v3 Webhook validation:
  $$\text{HMAC-SHA256}(\text{client\_secret}, \text{HTTP\_METHOD} + \text{URI} + \text{BODY} + \text{TIMESTAMP})$$
* Timestamp freshness check: Rejects requests older than 300 seconds (5 minutes) to defeat replay attacks.
* Automatic fallback support for HubSpot v1 signature.
* Idempotent delivery protection: Prevents duplicate execution from webhook retries.
* Recursive update loop prevention: 30-second cooldown window prevents webhooks from reacting to our own CRM updates.

---

## OpenAI Demo Records & Execution

### 1. Pre-flight Schema Check
```bash
python scripts/setup_hubspot.py
```

### 2. Populate OpenAI Company and 5 Enriched Contacts
```bash
python scripts/enrich_demo_company.py
```
This automated script:
1. Locates or creates the OpenAI test company in HubSpot.
2. Enriches all company attributes from Forager (`openai.com`).
3. Discovers 5 tech leaders/engineers matching the job-title filter.
4. Enriches each person with verified details (email, phone, LinkedIn, city, state, country).
5. Associates all 5 contacts with the OpenAI company in HubSpot.

### 3. Run Validation Audit
```bash
python scripts/validate_demo_records.py
```
Outputs validation check results:
* Verified company exists and is enriched.
* 5 associated contacts exist.
* Zero duplicate records.
* Field completeness breakdown and missing field disclosure.

---

## Railway Production Deployment

### 1. Deploy via Railway CLI or Git
The repository includes `Procfile` and `Dockerfile`:
```bash
# Using Railway CLI:
railway login
railway init
railway up
```

### 2. Configure Environment Variables in Railway Dashboard
In Railway -> Project Settings -> Variables, add:
* `FORAGER_API_KEY`
* `HUBSPOT_ACCESS_TOKEN`
* `HUBSPOT_CLIENT_SECRET`
* `ALLOWED_JOB_TITLES`
* `MAX_CONTACTS_PER_COMPANY`=5
* `LOG_LEVEL`=INFO

### 3. Configure HubSpot Webhooks
1. In HubSpot Developer Portal / App Settings, navigate to **Webhooks**.
2. Target Webhook URL: `https://<YOUR-RAILWAY-APP>.up.railway.app/webhooks/hubspot`
3. Create Webhook Subscriptions:
   * **Company created** (`company.creation`)
   * **Contact created** (`contact.creation`)
4. Verify `/health` on production URL:
   ```bash
   curl -i https://<YOUR-RAILWAY-APP>.up.railway.app/health
   ```

---

## Known Provider Limitations

1. **Personal Direct Dials & Cell Phones:**
   * B2B providers do not always have verified mobile phone numbers for every individual due to privacy regulations (GDPR/CCPA). Where Forager returns no phone number, the field remains empty and is logged in `missing_fields`.
2. **Work Email Async Enrichment:**
   * Work email generation in Forager uses an asynchronous lookup job (`POST /api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/`) returning `202 Accepted`. Our client polls up to 3 times before falling back to personal emails or reporting missing.
3. **LinkedIn Identifier Variations:**
   * Some public profiles use alphanumeric hashes rather than named slugs. The integration automatically strips URL query parameters and handles both formats.

---

## Forager Extra Fields for Team Discussion

Forager returns rich signals that are not part of standard HubSpot CRM properties. These provide high GTM value if custom properties are created:

1. **LinkedIn "About" Summary & Headline:**
   * Useful for sales reps to see personal background directly on the contact timeline.
2. **Detailed Skills List:**
   * Returns specific technical competencies (e.g. `["PyTorch", "Distributed Training", "CUDA"]`).
3. **Company Technographics & Web Technologies (`website_technologies`):**
   * Detected CMS, analytics, hosting, and AI libraries.
4. **Funding Events & Simple Events (`found_funding_events`):**
   * Recent venture rounds, series, and investor signals for timing outreach.
5. **Domain Rank & Traffic Metrics (`domain_rank`, `tranco_rank`):**
   * Authority score to automatically tier inbound accounts into SMB, Mid-Market, and Enterprise.

---

## Video Walkthrough Script

Use this concise script for the Loom/screen recording:

| Timestamp | Screen | Speaking Script |
|---|---|---|
| **0:00 - 0:30** | Code repository & Architecture | *"Hi team, here is the custom Python integration connecting Forager and HubSpot. Built cleanly with FastAPI, httpx, and Pydantic with zero no-code dependencies."* |
| **0:30 - 1:00** | Test Suite Execution | *"Let's run `pytest -v`. All 44 unit and integration tests pass, covering field mapping, title variation matching, v3 signature validation, and deduplication."* |
| **1:00 - 1:45** | OpenAI Company & Contact Enrichment | *"Running `python scripts/enrich_demo_company.py`. It locates OpenAI in HubSpot, enriches description, revenue, employee count, and LinkedIn URL from Forager, then discovers 5 tech leaders matching our job-title filters and associates them."* |
| **1:45 - 2:30** | HubSpot CRM Verification | *"Opening HubSpot CRM. Here is OpenAI with full details populated. Viewing the 5 associated contacts: first/last name, job title, email, phone, location, and LinkedIn URL are accurately mapped without duplicates."* |
| **2:30 - 3:15** | Live Webhook Demonstration | *"Demonstrating the live Railway service. When a new company or contact is created in HubSpot, HubSpot fires a signed webhook. Our service verifies the SHA-256 HMAC v3 signature, checks replay timestamp, avoids recursive loops, and enriches in the background."* |
| **3:15 - 3:45** | Extra Forager Fields & Wrap-up | *"Lastly, Forager surfaces great extra signals like technographics, funding events, and skills. We can easily map these to custom properties. Thanks for watching!"* |
