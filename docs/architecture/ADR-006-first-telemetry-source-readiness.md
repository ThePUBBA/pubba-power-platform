# ADR-006: First telemetry source integration readiness

## Decision

No real battery telemetry source is selected or implemented yet. The repository and
local deployment configuration contain no BMS, SCADA, OEM, partner sandbox, MQTT,
Modbus, historian, SFTP, CSV-feed, or webhook credentials or documentation. CAISO is a
real market-data integration, not an asset telemetry source. Inventing a vendor payload,
authentication scheme, or transport would create a false integration and is prohibited.

PUBBA Power therefore remains integration-ready but provider-neutral. Production
telemetry writes remain disabled. This phase adds the identity, connector, health, and
traceability contracts needed to implement the first documented provider safely.

## External access required before selecting a source

The operator or provider must supply all of the following through an approved secure
channel:

- provider name and authoritative API/feed documentation;
- sandbox or read-only endpoint and authentication/credential-rotation procedure;
- documented polling, webhook, file, MQTT, or gateway transport;
- rate limits, timeout guidance, and retry semantics;
- representative sanitized payloads and schema/version behavior;
- vendor site ID and asset ID for exactly one pilot asset;
- confirmed PUBBA `asset_id` and `portfolio_id` mapping;
- signed power convention, units, timestamps/timezone, and operational status values;
- provider support contact and outage/error behavior.

Secrets must be stored in the deployment secret manager. They must never appear in
Git, logs, URLs, documentation examples, dashboard code, or test fixtures.

## Integration-ready contracts

`TelemetrySourceConnector` is the transport boundary. A provider implementation must
perform a real, authenticated `health_check()` and implement only the transport the
provider supports. Polling, webhook, message, and file behavior must not be guessed.

`AssetIdentityMap` resolves this exact tuple:

```text
(source_name, vendor_site_id, vendor_asset_id)
  -> (PUBBA asset_id, portfolio_id)
```

Asset names are never used as identity. Unmapped identities raise a normalized
validation error and cannot create assets. Initial mappings can be supplied in the
server-only `TELEMETRY_ASSET_MAPPINGS_JSON` deployment value. If fleet scale or operator
workflows later require database-backed mapping, add a reviewed additive migration; do
not modify migration history or apply it automatically.

Source runtime health records actual successful connection checks and sanitized error
categories. Database telemetry receipt remains the authority for last-received and
freshness. A configured source alone remains `never_received`; an actual successful
connection with no telemetry is `connected`; recent telemetry is `receiving_data`;
subsequent states are `delayed`, `stale`, or `error`.

Each ingestion cycle records request and ingestion timestamps, source names, received,
normalized, accepted, rejected and duplicate counts, duration, status, and sanitized
error codes. Raw payloads and authorization material are not logged or stored.

## First provider implementation procedure

1. Review the provider documentation and sanitized sample payloads.
2. Select one documented transport and isolate it behind `TelemetrySourceConnector`.
3. Implement a source-specific `TelemetryAdapter` with a unique, stable source name.
4. Read credentials only from provider-specific server environment variables.
5. Resolve the pilot source/site/asset tuple through `AssetIdentityMap`.
6. Preserve source timestamps, units, signed power, and explicit operational
   `is_simulated=false` classification.
7. Add mocked tests for authentication failure, timeout, rate limiting, schema drift,
   optional fields, mapping, duplicates, ordering, future timestamps, source health,
   source outage, storage outage, and the one-asset path.
8. Validate locally, in staging, and against a production read-only provider endpoint.
9. Keep `TELEMETRY_WRITES_ENABLED=false` until authentication, health, mapping,
   normalization, idempotency, staleness, dashboard rendering, and secret hygiene pass.
10. Enable one pilot asset only with explicit operator approval. Expand to a second asset
    only after its history, readiness, summary, and dashboard values are verified.

Credential rotation is provider-specific: create the replacement credential, deploy it
server-side, validate a real health check, switch the source, and revoke the old
credential. Never log either value. A second provider gets its own connector, adapter,
source name, credentials, mappings, fixtures, and rollout review; provider logic must not
be added to core ingestion.

## Current limitation

Runtime connection state is process-local and intentionally contains no credentials or
raw payloads. Before horizontally scaling a real poller or webhook receiver, select a
shared operational state/metrics system based on deployment requirements. No polling
schedule, retry policy, webhook signature scheme, or file tracker exists because no
provider transport has been documented.
