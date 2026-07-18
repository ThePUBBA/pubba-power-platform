# ADR-004: Battery telemetry and asset-state foundation

## Current asset audit

The existing `public.assets` table remains the source of configured asset identity and
ownership. Its production schema contains:

| Field | Purpose |
| --- | --- |
| `id` | Internal UUID primary key |
| `asset_id` | Stable external/business identifier |
| `portfolio_id` | Owning portfolio UUID |
| `asset_name`, `technology`, `location` | Operator-facing identity |
| `power_mw`, `energy_mwh`, `duration_hours` | Configured nameplate constraints |
| `lease_cost_monthly` | Configured commercial input |
| `status`, `retired_at`, `retirement_reason` | Asset lifecycle state |
| `revision` | Optimistic asset revision counter |
| `created_at`, `updated_at` | Record timestamps |

Before this phase, assets did not contain observed state of charge, current power,
charge/discharge availability, available energy, temperature, telemetry source,
telemetry freshness, or dispatch readiness. Dispatch events provide historical ledger
economics and simulations provide calculated scenarios; neither is live telemetry.

## Decision

Store observations in additive `public.asset_telemetry` rows rather than mutating the
configured asset record. One asset can have many timestamped observations. The newest
row is retrieved using the `(asset_id, recorded_at desc, id desc)` index. A unique
constraint on `(asset_id, recorded_at)` prevents duplicate observations at one instant.

Missing measurements remain null and are never converted to zero. Current power is
signed because charging and discharging direction may use opposite signs. Available
charge power, available discharge power, available energy, and SOC have nonnegative
database and application constraints. Every record identifies its source and whether it
is simulated.

Readiness is deterministic and explainable. It does not optimize, authorize, or execute
dispatch.

## Safe migration procedure

The exact SQL is
`supabase/migrations/202607170001_battery_telemetry_foundation.sql`. It creates only a
new table, constraints, indexes, and RLS state. It does not update or delete existing
asset, simulation, or dispatch records.

1. Back up production and confirm prior migrations are applied.
2. Review and run the SQL in staging.
3. Verify telemetry reads, disabled writes, and the dashboard in staging.
4. Apply the same file using the established Supabase CLI workflow or SQL editor.
5. Keep `TELEMETRY_WRITES_ENABLED=false` until authenticated ingestion is configured.

Until migration, `/dashboard/summary` returns HTTP 200 with telemetry unavailable.
Direct telemetry routes may return the existing safe Supabase error for a missing table.
