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

### `GET /simulate`

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
