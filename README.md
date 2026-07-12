# Only1 LMP API

FastAPI service for retrieving CAISO locational marginal price (LMP) data and identifying simple historical storage arbitrage opportunities for Only1 Power workflows.

## Overview

This API exposes HTTP endpoints for CAISO OASIS LMP lookups and a first-pass historical arbitrage analysis. It is intended to support market research, dispatch analysis, reporting, and downstream automation for energy storage workflows.

The LMP implementation uses CAISO's official OASIS `SingleZip` endpoint with `queryname=PRC_INTVL_LMP`, `resultformat=6`, and CSV data returned inside a ZIP archive.

## Endpoints

### `GET /`

Health check endpoint.

Example response:

```json
{"message":"Only1 LMP API is running"}
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

Run a storage simulation from a JSON request. This is the preferred endpoint for the Only1 Power Retool dashboard. It calls the same simulation and arbitrage functions as the legacy GET endpoint.

```bash
curl -X POST "http://localhost:8000/simulate" \
  -H "Content-Type: application/json" \
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
  "assumptions": {}
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
  "service_name": "Only1 LMP API",
  "api_version": "1.0.0",
  "current_utc_timestamp": "2026-07-12T20:00:00Z"
}
```

## Retool REST API Resource Setup

1. In Retool, create a REST API resource and set its base URL to the deployed API URL, without an endpoint path.
2. Do not add authentication headers; this API does not currently implement authentication.
3. Test the resource with `GET /health`.
4. Create a POST query for `/simulate`, select a JSON body, and map Retool component values to the request fields shown above.
5. Display successful query data directly; for failures, read `error_code`, `message`, and `field` or `upstream_service` from the response body.

For browser-based Retool requests, add the exact Retool origin to `ALLOWED_ORIGINS` in the API deployment environment. Retool-hosted origins commonly follow `https://YOUR-ORG.retool.com`; custom Retool domains must be listed explicitly.

## CORS Configuration

`ALLOWED_ORIGINS` is a comma-separated allowlist. It has no wildcard default and CORS middleware is disabled when the variable is empty.

```bash
ALLOWED_ORIGINS=https://your-org.retool.com,https://dashboard.only1power.com
```

Copy `.env.example` as a deployment reference, but configure the actual value through the hosting provider. Origins must include the scheme and must not include a trailing path. Never put secrets in `.env.example` or commit a populated `.env` file.

## Optional Airtable Simulation Archive

Successful `POST /simulate` requests can create one Airtable record for reporting and historical analysis. Airtable is optional: when its configuration is missing, no write is attempted. If a configured Airtable request fails, the API logs the error and still returns the completed simulation response.

Create an Airtable personal access token with `data.records:write` scope and access to the target base, then configure these deployment environment variables:

```bash
AIRTABLE_API_KEY=pat_your_personal_access_token
AIRTABLE_BASE_ID=app_your_base_id
AIRTABLE_TABLE_NAME=Simulation Archive
```

The target table must contain fields matching these names:

- `timestamp`
- `location`
- `market`
- `date`
- `power_mw`
- `duration_hours`
- `round_trip_efficiency`
- `cycles`
- `charging_cost`
- `discharge_revenue`
- `gross_arbitrage_margin`
- `estimated_net_margin`
- `charging_window_start`
- `charging_window_end`
- `discharging_window_start`
- `discharging_window_end`

Use date/time-compatible Airtable fields for `timestamp` and the four window fields, numeric fields for power, duration, efficiency, cycles, costs, revenue, and margins, and text or select fields for location and market. The table name is URL-encoded by the service, so spaces are supported.

Keep the personal access token in the deployment provider's secret manager. Do not expose it in Retool, commit it to Git, or add it to `.env.example`.

## OpenAPI Documentation

With the API running, use interactive Swagger documentation at `http://localhost:8000/docs` or the raw OpenAPI schema at `http://localhost:8000/openapi.json`. The POST request model, response schema, constraints, and health response are published there and can be used to verify Retool payloads.

## Security Notes

- CORS restricts browser origins; it is not authentication or authorization.
- This API is intentionally unauthenticated. Deploy it behind an appropriate private network, gateway, or access control before exposing sensitive workflows publicly.
- Do not place secrets, API keys, credentials, or Retool tokens in request bodies, source control, `.env.example`, or client-side Retool JavaScript.
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

## License

MIT License. See `LICENSE` for details.
