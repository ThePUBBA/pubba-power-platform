# PUBBA Power API

FastAPI service for retrieving CAISO locational marginal price (LMP) data and identifying simple historical storage arbitrage opportunities for PUBBA Power workflows.

# About PUBBA

PUBBA Power is the energy division of PUBBA, focused on electricity trading, long-duration energy storage (LDES), portfolio optimization, and grid services.

## Battery telemetry foundation

Battery telemetry is stored separately from configured asset and dispatch records. The
additive migration is
`supabase/migrations/202607170001_battery_telemetry_foundation.sql`; safe application
steps and the audited asset schema are documented in
`docs/architecture/ADR-004-battery-telemetry-foundation.md`.

Telemetry routes include the latest observation and history for one asset, the latest
observation per portfolio asset, source health, secure single-record ingestion, and
partial-success batch ingestion. Enable writes only with
`TELEMETRY_WRITES_ENABLED=true` and a secret `TELEMETRY_WRITE_TOKEN` supplied as
`X-Telemetry-Key`. Batch size and freshness thresholds use the `TELEMETRY_*`
configuration documented in `.env.example`. The provider-neutral adapter architecture,
payloads, idempotency, source health, credential rotation, and future BMS/SCADA adapter
process are documented in
`docs/architecture/ADR-005-secure-telemetry-ingestion.md`.
The audited status of the first real source, required external access, asset identity
mapping, connector boundary, and one-asset rollout procedure are documented in
`docs/architecture/ADR-006-first-telemetry-source-readiness.md`. No provider is currently
configured, and production telemetry writes remain disabled.

The development generator is separately gated by
`PUBBA_ENABLE_SIMULATED_TELEMETRY=true` and must never be enabled in production.

Dispatch recommendations are advisory, deterministic market-opportunity analysis. They
never execute dispatches, transactions, simulations, or telemetry writes. The scoring,
economics, missing operational inputs, safety behavior, API contracts, simulation
handoff, and deferred history design are documented in
`docs/architecture/ADR-007-dispatch-recommendations.md`.

## Repository

The PUBBA Power platform source is hosted at [ThePubba/pubba-power-platform](https://github.com/ThePubba/pubba-power-platform).

```bash
git clone https://github.com/ThePubba/pubba-power-platform.git
cd pubba-power-platform
```

## Overview

This API exposes HTTP endpoints for CAISO OASIS LMP lookups and a first-pass historical arbitrage analysis. It is intended to support market research, dispatch analysis, reporting, and downstream automation for energy storage workflows.

The LMP implementation uses CAISO's official OASIS `SingleZip` endpoint with `queryname=PRC_INTVL_LMP`, `resultformat=6`, and CSV data returned inside a ZIP archive.

## Endpoints

### `GET /`

Health check endpoint.

Example response:

```json
{"message":"PUBBA Power API is running"}
```

### `GET /lmp`

Fetch LMP records for a CAISO node, market run, and optional trade date.

Query parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `market` | `RTM` | CAISO market run ID. Supported values: `DAM`, `HASP`, `RTPD`, `RTM`. Legacy `LMP` is accepted as an alias for `RTM`. |
| `location` | `TH_NP15_GEN-APND` | CAISO pricing node or location code passed as the OASIS `node` parameter. |
| `date` | current Pacific date | Optional trade date in `YYYY-MM-DD` format. The API requests the full Pacific trade day. |

Example:

```bash
curl "http://localhost:8000/lmp?market=RTM&location=TH_NP15_GEN-APND&date=2025-04-01"
```

### `GET /arbitrage`

Fetch historical LMP data and estimate a simple buy-low / sell-high opportunity for an energy storage asset.

Query parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `market` | `RTM` | CAISO market run ID. |
| `location` | `TH_NP15_GEN-APND` | CAISO pricing node or location code. |
| `date` | current Pacific date | Trade date in `YYYY-MM-DD` format. |
| `duration_hours` | `8` | Storage charge/discharge window length. Must be positive. |
| `round_trip_efficiency` | `0.80` | Storage round-trip efficiency. Must be greater than `0` and less than or equal to `1`. |

Example:

```bash
curl "http://localhost:8000/arbitrage?market=RTM&location=TH_NP15_GEN-APND&date=2025-04-01&duration_hours=8&round_trip_efficiency=0.80"
```

Sample response:

```json
{
  "duration_hours": 8,
  "round_trip_efficiency": 0.8,
  "interval_hours": 1,
  "intervals_per_window": 8,
  "charging_window": {
    "start_timestamp": "2025-04-01T00:00:00+00:00",
    "end_timestamp": "2025-04-01T08:00:00+00:00",
    "average_price": 20.0,
    "prices": [
      {"timestamp": "2025-04-01T00:00:00+00:00", "price": 18.0}
    ]
  },
  "discharging_window": {
    "start_timestamp": "2025-04-01T16:00:00+00:00",
    "end_timestamp": "2025-04-02T00:00:00+00:00",
    "average_price": 80.0,
    "prices": [
      {"timestamp": "2025-04-01T16:00:00+00:00", "price": 78.0}
    ]
  },
  "average_charging_price": 20.0,
  "average_discharging_price": 80.0,
  "gross_price_spread": 60.0,
  "efficiency_adjusted_spread": 44.0,
  "estimated_gross_margin_per_mwh_discharged": 55.0
}
```

### `POST /simulate` (Retool)

Run a storage simulation from a JSON request. This is the preferred endpoint for the PUBBA Power Retool dashboard. It calls the same simulation and arbitrage functions as the legacy GET endpoint.

```bash
curl -X POST "http://localhost:8000/simulate" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: retool-simulation-2025-04-01-bat-001" \
  -d '{
    "location": "TH_NP15_GEN-APND",
    "market": "RTM",
    "date": "2025-04-01",
    "power_mw": 10,
    "duration_hours": 4,
    "round_trip_efficiency": 0.8,
    "cycles": 2,
    "storage_fee_per_mwh": 5,
    "variable_om_per_mwh": 2
  }'
```

Sample response:

```json
{
  "power_mw": 10,
  "duration_hours": 4,
  "round_trip_efficiency": 0.8,
  "cycles": 2,
  "storage_fee_per_mwh": 5,
  "variable_om_per_mwh": 2,
  "energy_capacity_mwh": 40,
  "charging_energy_required_mwh": 100,
  "discharged_energy_mwh": 80,
  "charging_cost": 1500,
  "discharge_revenue": 7200,
  "gross_arbitrage_margin": 5700,
  "storage_lease_cost": 400,
  "variable_operating_cost": 160,
  "estimated_net_margin": 5140,
  "net_margin_per_mw": 514,
  "net_margin_per_mwh_discharged": 64.25,
  "arbitrage": {"duration_hours": 4, "round_trip_efficiency": 0.8},
  "charging_window": {"start_timestamp": "2025-04-01T02:00:00+00:00", "end_timestamp": "2025-04-01T06:00:00+00:00", "average_price": 15, "prices": []},
  "discharging_window": {"start_timestamp": "2025-04-01T08:00:00+00:00", "end_timestamp": "2025-04-01T12:00:00+00:00", "average_price": 90, "prices": []},
  "assumptions": {},
  "persistence": {
    "status": "saved",
    "simulation_id": "123e4567-e89b-52d3-a456-426614174000",
    "dispatch_id": null,
    "error_code": null,
    "message": "Simulation saved; no asset_id was supplied"
  }
}
```

The live response includes the complete nested `arbitrage`, window price points, and formula assumptions. Pydantic request validation requires positive power, duration, efficiency, and cycles; efficiency cannot exceed `1`; and per-MWh fees cannot be negative.

Validation and upstream failures use a stable JSON envelope:

```json
{
  "error_code": "validation_error",
  "message": "Input should be greater than 0",
  "field": "power_mw"
}
```

CAISO failures include `"upstream_service": "CAISO OASIS"`.

### `GET /simulate` (backward compatible)

Fetch historical LMP data, reuse the arbitrage window selection, and estimate dollar revenue for a leased storage asset. This is a historical simulation using posted LMPs; it is not a forecast, live dispatch signal, or trading recommendation.

Query parameters:

| Parameter | Default | Description |
| --- | --- | --- |
| `power_mw` | required | Storage power rating in MW. Must be positive. |
| `market` | `RTM` | CAISO market run ID. |
| `location` | `TH_NP15_GEN-APND` | CAISO pricing node or location code. |
| `date` | current Pacific date | Trade date in `YYYY-MM-DD` format. |
| `duration_hours` | `8` | Storage duration. Must be positive. |
| `round_trip_efficiency` | `0.80` | Storage round-trip efficiency. Must be greater than `0` and less than or equal to `1`. |
| `cycles` | `1` | Number of equivalent full cycles to simulate. Must be positive. |
| `storage_fee_per_mwh` | `0` | Lease or tolling fee in dollars per MWh discharged. Must be non-negative. |
| `variable_om_per_mwh` | `0` | Variable operating cost in dollars per MWh discharged. Must be non-negative. |

Example:

```bash
curl "http://localhost:8000/simulate?market=RTM&location=TH_NP15_GEN-APND&date=2025-04-01&power_mw=10&duration_hours=8&round_trip_efficiency=0.80&cycles=1&storage_fee_per_mwh=5&variable_om_per_mwh=2"
```

Sample response:

```json
{
  "power_mw": 10,
  "duration_hours": 8,
  "round_trip_efficiency": 0.8,
  "cycles": 1,
  "storage_fee_per_mwh": 5,
  "variable_om_per_mwh": 2,
  "energy_capacity_mwh": 80,
  "charging_energy_required_mwh": 100,
  "discharged_energy_mwh": 80,
  "charging_cost": 2000,
  "discharge_revenue": 6400,
  "gross_arbitrage_margin": 4400,
  "storage_lease_cost": 400,
  "variable_operating_cost": 160,
  "estimated_net_margin": 3840,
  "net_margin_per_mw": 384,
  "net_margin_per_mwh_discharged": 48,
  "charging_window": {
    "start_timestamp": "2025-04-01T00:00:00+00:00",
    "end_timestamp": "2025-04-01T08:00:00+00:00",
    "average_price": 20.0
  },
  "discharging_window": {
    "start_timestamp": "2025-04-01T16:00:00+00:00",
    "end_timestamp": "2025-04-02T00:00:00+00:00",
    "average_price": 80.0
  }
}
```

Returned price fields are dollars per MWh. Returned margin, revenue, cost, and fee fields are dollars unless the field name explicitly says `per_mw` or `per_mwh`.

### `GET /health`

Use this endpoint for uptime checks and Retool resource validation.

```bash
curl "http://localhost:8000/health"
```

```json
{
  "status": "ok",
  "service_name": "PUBBA Power API",
  "api_version": "1.0.0",
  "current_utc_timestamp": "2026-07-12T20:00:00Z",
  "supabase_connectivity_status": "connected"
}
```

## Retool REST API Resource Setup

1. In Retool, create a REST API resource and set its base URL to the deployed API URL, without an endpoint path.
2. Do not add authentication headers; this API does not currently implement authentication.
3. Test the resource with `GET /health`.
4. Create a POST query for `/simulate`, select a JSON body, and map Retool component values to the request fields shown above.
5. Display successful query data directly; for failures, read `error_code`, `message`, and `field` or `upstream_service` from the response body.

The existing Retool simulation and asset-performance queries remain compatible with `POST /simulate` and `GET /portfolio/assets`. Use `/assets` for asset management, `/dispatch-events` for the ledger, `/reports/*` for period reporting, and `/dispatch-events/export.csv` for downloads. No Retool frontend changes are included here.

For browser-based Retool requests, add the exact Retool origin to `ALLOWED_ORIGINS` in the API deployment environment. Retool-hosted origins commonly follow `https://YOUR-ORG.retool.com`; custom Retool domains must be listed explicitly.

## CORS Configuration

`ALLOWED_ORIGINS` is a comma-separated allowlist. It has no wildcard default and CORS middleware is disabled when the variable is empty.

```bash
ALLOWED_ORIGINS=https://pubbapower.com,https://www.pubbapower.com,https://app.pubbapower.com,https://your-org.retool.com
```

Whitespace and empty comma-separated entries are ignored. Copy `.env.example` as a deployment reference, but configure the actual value through the hosting provider. Origins must include the scheme and must not include a trailing path. Never use wildcard CORS with credentials. Never put secrets in `.env.example` or commit a populated `.env` file.

## Supabase PostgreSQL Ledger

Supabase PostgreSQL is the only production system of record. The API never reads from or writes to Airtable. Configure both required variables in Render:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

Keep the service-role key in Render's secret manager. It must never be sent to Retool, logged, committed, or placed in browser code. Missing configuration produces a degraded health status and structured request-time errors.

Apply [`supabase/migrations/202607130001_supabase_system_of_record.sql`](supabase/migrations/202607130001_supabase_system_of_record.sql) before deploying the API. The migration defines:

- `assets`, keyed by UUID with a unique business `asset_id`.
- `simulation_results`, keyed by UUID with a unique `external_simulation_id`; its text `asset_id` foreign key preserves the live relationship to `assets.asset_id`.
- `dispatch_events`, keyed by UUID with a unique deterministic `dispatch_id`, a text `asset_id` foreign key to `assets.asset_id`, and a UUID `simulation_id` foreign key to `simulation_results.id`.
- Numeric ledger columns, UTC timestamps, stable query indexes, and an `updated_at` trigger for assets.
- Row-level security on all ledger tables; the Render backend uses the service role, while browser clients receive no database credentials.

After applying the migration, run the read-only verification script:

```bash
python scripts/verify_supabase_migration.py
```

It validates required tables and columns, counts assets/simulations/dispatches, and reports orphaned dispatches or duplicate dispatch IDs without deleting data.

### Simulation persistence and idempotency

Every successful `POST /simulate` attempts to insert a `simulation_results` record. If the optional business `asset_id` exists, the API links the simulation to that asset and atomically upserts one `dispatch_events` record using `dispatch:<simulation_uuid>` as the unique dispatch ID. Missing assets never create fake records.

Clients may send an `Idempotency-Key` header. Reusing a key with the same request reuses the same simulation UUID and dispatch; reusing it for different input returns an idempotency conflict in the persistence result. Without the header, the API derives a stable key from the complete request and calculated result, so an identical HTTP retry cannot create another dispatch.

Persistence status is included in the POST response. A completed calculation still returns when Supabase persistence fails, but `persistence.status`, `error_code`, and `message` clearly report whether the simulation or dispatch write failed. Failures are also logged without credentials.

Example request with an asset link:

```json
{
  "location": "TH_NP15_GEN-APND",
  "market": "RTM",
  "date": "2025-07-18",
  "power_mw": 10,
  "duration_hours": 4,
  "round_trip_efficiency": 0.85,
  "cycles": 1,
  "storage_fee_per_mwh": 5,
  "variable_om_per_mwh": 2,
  "asset_id": "BAT-001"
}
```

### `GET /portfolio/summary`

Returns the authoritative portfolio-scoped executive summary. Optional
timezone-aware `start_at`, `end_at`, and IANA `timezone` parameters control the
selected summary period. Current day, week, month, quarter, and year revenue
uses the portfolio reporting timezone. Financial and energy values include
completed dispatches and centrally normalized legacy simulation-derived rows.

```json
{
  "portfolio": {
    "id": "uuid",
    "code": "ONLY1",
    "name": "PUBBA Power",
    "default_market": "CAISO",
    "reporting_timezone": "America/Los_Angeles",
    "currency_code": "USD"
  },
  "financial": {
    "gross_revenue": "10000.00",
    "charging_cost": "4000.00",
    "net_profit": "5000.00",
    "total_portfolio_profit": "25000.00",
    "trading_return": "1.25",
    "weighted_average_spread_per_mwh": "42.17"
  },
  "operations": {
    "total_dispatches": 8,
    "purchased_energy_mwh": "100.00",
    "sold_energy_mwh": "80.00",
    "energy_throughput_mwh": "180.00",
    "last_dispatch_at": "2026-07-14T18:00:00Z"
  }
}
```

The full response also includes current-period revenue, active fleet capacity,
metric version, generation time, and operational data freshness. Empty
portfolios return a successful zero-valued response.

## PUBBA Power Operations Console

The Streamlit dashboard provides persistent `Overview` and `Simulations`
navigation. Overview displays the backend summary as financial, current-period
revenue, operations, and fleet KPI cards. It supports lifetime and custom date
ranges, timezone-aware timestamps, manual refresh, loading feedback, empty
states, and safe operator-facing errors.

Streamlit performs presentation formatting only. It does not access Supabase,
aggregate dispatches, or calculate profit, return, spread, or revenue periods.
The Simulations page calls the existing `POST /simulate` workflow.

Configure the backend location without embedding a production URL:

```bash
export PUBBA_POWER_API_BASE_URL=http://localhost:8000
```

The dashboard prefers `PUBBA_POWER_API_BASE_URL` and falls back to the existing `ONLY1_API_BASE_URL` compatibility variable. No implicit localhost URL is used; local development must configure one of these variables explicitly.

After applying the portfolio migrations and starting FastAPI, run:

```bash
streamlit run dashboard/app.py
```

Custom ranges require an IANA reporting timezone and send inclusive,
timezone-aware start and end timestamps. Values use portfolio currency, MW,
MWh, currency/MWh, and the backend trading-return ratio formatted as a
percentage. A valid portfolio with no active assets or completed dispatches is
shown as an empty operational state rather than an error.

Required migrations, in order:

1. `202607140001_portfolio_schema_foundation.sql`
2. `202607140002_portfolio_summary_inputs.sql`
3. `202607150001_pubba_power_branding.sql`

### `GET /portfolio/assets`

Returns one performance object for every Supabase asset, including assets with no dispatch history. Metrics are calculated from paginated `dispatch_events` rows linked by the existing business `asset_id` foreign key.

```json
[
  {
    "asset_id": "BAT-001",
    "asset_name": "North Battery",
    "technology": "LFP",
    "status": "Active",
    "power_mw": 10,
    "energy_mwh": 40,
    "location": "NP15",
    "total_dispatches": 2,
    "total_revenue": 2000,
    "total_charging_cost": 650,
    "total_profit": 1150,
    "average_profit_per_dispatch": 575,
    "last_dispatch_time": "2025-07-19T19:00:00Z"
  }
]
```

`last_dispatch_time` is the latest valid `discharge_end` timestamp, or `null`. Malformed numeric values contribute `0` to read-time aggregates and are logged safely.

### Asset management

- `GET /assets?limit=100&offset=0`
- `GET /assets/{asset_id}`
- `POST /assets`
- `PATCH /assets/{asset_id}`

Duplicate business asset IDs return a structured `409 duplicate_asset`; missing assets return `404 missing_asset`.

### Dispatch ledger and exports

`GET /dispatch-events` accepts `start_date`, `end_date`, `asset_id`, `market`, `location`, `status`, `limit`, and `offset`. Results use stable `dispatch_timestamp,id` ordering.

`GET /dispatch-events/export.csv` accepts the same business filters and exports every matching row as CSV. Retool can use this endpoint for daily, weekly, monthly, quarterly, or yearly downloads.

### Reports

These endpoints aggregate authoritative Supabase dispatch rows and return period boundaries, dispatch count, energy MWh, charging cost, discharge revenue, storage cost, and net profit:

- `GET /reports/daily`
- `GET /reports/weekly`
- `GET /reports/monthly`
- `GET /reports/quarterly`
- `GET /reports/yearly`

All accept optional `start_date` and `end_date`. No cached P&L table is used.

## OpenAPI Documentation

With the API running, use interactive Swagger documentation at `http://localhost:8000/docs` or the raw OpenAPI schema at `http://localhost:8000/openapi.json`. The POST request model, response schema, constraints, and health response are published there and can be used to verify Retool payloads.

## Security Notes

- CORS restricts browser origins; it is not authentication or authorization.
- This API is intentionally unauthenticated. Deploy it behind an appropriate private network, gateway, or access control before exposing sensitive workflows publicly.
- Do not place secrets, API keys, credentials, or Retool tokens in request bodies, source control, `.env.example`, or client-side Retool JavaScript.
- Never expose `SUPABASE_SERVICE_ROLE_KEY` to Retool or any browser client.
- Treat simulation output as historical analysis, not a live dispatch or trading instruction.

## Formula Assumptions

- The service selects the lowest average contiguous charging window and the highest average non-overlapping contiguous discharging window.
- `gross_price_spread = average_discharging_price - average_charging_price` in dollars per MWh.
- `efficiency_adjusted_spread = average_discharging_price * round_trip_efficiency - average_charging_price` in dollars per MWh charged.
- `estimated_gross_margin_per_mwh_discharged = average_discharging_price - average_charging_price / round_trip_efficiency`
- `energy_capacity_mwh = power_mw * duration_hours`
- `discharged_energy_mwh = energy_capacity_mwh * cycles`
- `charging_energy_required_mwh = discharged_energy_mwh / round_trip_efficiency`
- `charging_cost = charging_energy_required_mwh * average_charging_price`
- `discharge_revenue = discharged_energy_mwh * average_discharging_price`
- `gross_arbitrage_margin = discharge_revenue - charging_cost`; this is a dollar margin, not the price spread.
- `storage_lease_cost = discharged_energy_mwh * storage_fee_per_mwh`; storage fees are charged on MWh discharged.
- `variable_operating_cost = discharged_energy_mwh * variable_om_per_mwh`; variable O&M is charged on MWh discharged.
- `estimated_net_margin = gross_arbitrage_margin - storage_lease_cost - variable_operating_cost`
- `net_margin_per_mw = estimated_net_margin / power_mw`
- `net_margin_per_mwh_discharged = estimated_net_margin / discharged_energy_mwh`
- `cycles` scales discharged energy, charging energy, discharge revenue, charging cost, storage lease cost, and variable operating cost.
- Prices are treated as dollars per MWh and can be negative when CAISO publishes negative LMPs.
- This is an energy-price-only screen, not a full dispatch optimization.

## CAISO Data Limitations

- OASIS can return no data for invalid nodes, unavailable trade dates, market outages, or delayed postings.
- OASIS requests for large node groups are subject to tighter date-window limits. This API currently requests one explicit node at a time.
- CAISO may return error XML or text inside the ZIP instead of a CSV. The API treats that as an upstream data error and returns HTTP `502`.
- HTTP failures, timeouts, malformed ZIP files, malformed CSV files, and invalid timestamps are surfaced as structured FastAPI errors.
- Date input is interpreted as a Pacific trade date, then sent to OASIS using UTC-formatted `startdatetime` and `enddatetime` values.

## Arbitrage Limitations

- No database.
- No frontend.
- No authentication.
- No second ISO.
- No live trading.
- No battery degradation model.
- No state-of-charge constraints beyond selecting non-overlapping charge and discharge windows.
- No ancillary services, capacity, congestion hedging, demand charges, or operating costs.
- No charge/discharge ramping constraints, outage modeling, reserve holdback, or real-time dispatch controls.

## Local Development

Supported Python versions:

- Python 3.11
- Python 3.12

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install production dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install development and test dependencies:

```bash
pip install -r requirements-dev.txt
```

Run tests:

```bash
python -m pytest -q
```

Run the API:

```bash
uvicorn main:app --reload
```

Open the interactive API docs at:

```text
http://localhost:8000/docs
```

## Production Verification Checklist

The intended public domain architecture is `pubbapower.com` for the marketing site, `app.pubbapower.com` for the Operations Console, and `api.pubbapower.com` for FastAPI. These URLs should not be treated as active until DNS, hosting, and TLS verification are complete. See [PUBBA Power domain deployment](docs/deployment/pubba-power-domains.md) for configuration, manual DNS steps, verification, and rollback.

- Confirm the deployed Git SHA matches the latest `main` commit and the working tree is clean before release.
- Confirm Render uses Python 3.12 (matching `.python-version`), installs `requirements.txt`, and starts Uvicorn with `uvicorn main:app --host 0.0.0.0 --port $PORT` or an equivalent command.
- Apply the committed Supabase migration and run `python scripts/verify_supabase_migration.py` before switching production traffic.
- Remove all legacy Airtable credentials, table-name settings, and archive flags from Render.
- Add `SUPABASE_URL` and secret `SUPABASE_SERVICE_ROLE_KEY` to Render, then redeploy.
- Confirm `GET /health` reports `supabase_connectivity_status: connected` and `status: ok`; confirm `GET /` returns HTTP 200.
- Run a dated `POST /simulate` with a known CAISO node and confirm HTTP 200, plausible output, `persistence.status: saved`, and linked Supabase simulation/dispatch rows.
- Confirm Retool's REST resource base URL points to the current Render service and its simulation query sends JSON to `POST /simulate`.
- Confirm asset CRUD, dispatch filters, reports, CSV export, and `GET /portfolio/assets` return Supabase-backed data.
- Confirm CAISO rate limits return a structured 502 response identifying `CAISO OASIS`, while Supabase failures remain visible without suppressing a completed calculation or exposing the service-role key.
- Confirm the latest GitHub Actions run passes on Python 3.11 and 3.12.

## License

MIT License. See `LICENSE` for details.
