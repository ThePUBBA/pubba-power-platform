# ADR-005: Secure provider-neutral telemetry ingestion

## Flow

```text
External telemetry source
  -> source adapter
  -> FastAPI token authentication
  -> source validation
  -> normalized telemetry validation
  -> idempotency and classification guard
  -> Supabase asset_telemetry
  -> readiness and source-health services
  -> dashboard
```

Provider adapters implement `TelemetryAdapter`: `validate_source_payload()`,
`normalize()`, and `health_check()`. `GenericJsonTelemetryAdapter` is the initial
provider-neutral JSON implementation. It is not a BMS, SCADA, or OEM integration.
Future Tesla Megapack, Fluence, Wärtsilä, Powin, ESS Inc., Modbus, historian, or
aggregator adapters must live behind this interface and must map vendor fields into the
existing normalized schema.

## Authentication and deployment defaults

`POST /telemetry` and `POST /telemetry/batch` are disabled unless
`TELEMETRY_WRITES_ENABLED=true`. Enabled writes additionally require a nonempty
`TELEMETRY_WRITE_TOKEN` supplied in `X-Telemetry-Key`. Comparison is constant-time.
Supabase service-role credentials remain server-side and are never accepted or returned
by ingestion routes.

Rotate a write credential by generating a new high-entropy value, updating the secret in
the API host, restarting the API, updating the authorized sender, and revoking the old
value. Never place the value in Git, logs, URLs, or example payloads.

## Single observation

```json
{
  "asset_id": "FICTIONAL-BAT-001",
  "recorded_at": "2026-07-18T02:59:00Z",
  "state_of_charge_pct": 62.0,
  "current_power_mw": -2.5,
  "available_charge_power_mw": 7.0,
  "available_discharge_power_mw": 8.0,
  "available_energy_mwh": 24.8,
  "temperature_c": 26.0,
  "operational_status": "normal",
  "availability_status": "available",
  "telemetry_source": "fictional_scada",
  "is_simulated": false
}
```

`is_simulated` and `telemetry_source` are mandatory. Missing optional readings remain
null. Signed `current_power_mw` is preserved. Invalid SOC, naive/future timestamps,
unknown assets, and classification mixing are rejected with sanitized errors.

## Batch ingestion and idempotency

`POST /telemetry/batch` accepts `{"observations": [...]}`. The configurable limit is
`TELEMETRY_MAX_BATCH_SIZE` (default 100, hard maximum 1000). Each observation is
validated and persisted independently. Responses include counts and indexed lists for
accepted, rejected, and duplicate observations. This intentional partial-success model
keeps valid records when another record is malformed; it does not silently discard the
invalid record.

The database unique constraint on `(asset_id, recorded_at)` is authoritative. The
service also detects duplicates within one batch. Repeating a delivered observation is
safe and reported as duplicate rather than inserted again.

## Classification, audit, freshness, and health

A telemetry source cannot switch between simulated and operational classification.
Controlled tests must use a dedicated PUBBA test source and `is_simulated=true`.

Every request emits a structured application audit record containing ingestion ID,
timestamp, sources, received/accepted/rejected/duplicate counts, status, and sanitized
error codes. Authentication material and raw secrets are never logged. No additional
database audit migration is required.

Freshness thresholds are centralized:

- `TELEMETRY_FRESH_SECONDS` (default 300)
- `TELEMETRY_DELAYED_SECONDS` (default 900)
- `TELEMETRY_STALE_SECONDS` (default 3600)
- `TELEMETRY_CHART_GAP_SECONDS` (default 1800)

Source health is derived from actual receipt timestamps: receiving data, connected,
stale, error, or never received. `TELEMETRY_CONFIGURED_SOURCES` may name expected
sources, but configuration alone never produces connected status. Dashboard alerts are
informational only and do not dispatch or remediate assets.

## Controlled testing

Prefer local or staging ingestion. Production write testing is never automatic. If an
operator explicitly authorizes it, use a fictional or dedicated test asset, a dedicated
`pubba_test` source, and `is_simulated=true`; never overwrite operational telemetry.
