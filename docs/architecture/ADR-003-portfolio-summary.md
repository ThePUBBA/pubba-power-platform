# ADR-003: Authoritative portfolio summary

- Status: Accepted
- Date: 2026-07-14
- Metric version: 1.0

## Decision

`GET /portfolio/summary` is the backend-owned source for PUBBA Power portfolio
KPIs. The route validates inputs, the portfolio summary service owns reporting
periods and formulas, and the Supabase repository supplies portfolio-scoped
records. Presentation clients do not calculate or reconcile these metrics.

The default reporting timezone comes from the resolved `ONLY1` portfolio. A
valid IANA timezone may be supplied per request. Local calendar boundaries are
computed with `zoneinfo` and converted to UTC for comparisons, including across
daylight-saving transitions. Week periods begin Monday.

Financial and energy KPIs include only completed dispatches. The existing
legacy status `simulated` is centrally normalized as completed because those
rows are the persisted simulation-derived dispatch ledger created before the
Phase 2 status contract. Draft, scheduled, cancelled, failed, and unknown
statuses are excluded. Estimated-versus-settled distinctions remain deferred
until settlement fields and workflows are implemented.

Selected-period metrics are lifetime when `start_at` is omitted and end at the
explicit `end_at` or request generation time. Today, week, month, quarter, and
year revenue always use current local reporting-period boundaries through the
generation time. Lifetime portfolio profit is reported separately.

Data freshness is the most recent completed dispatch `updated_at` (falling back
to its completion time), or the most recent active asset `updated_at` when no
completed dispatch exists. It is null when neither source exists and is never
replaced with request time.

Empty portfolios return zeros, null timestamps, and HTTP 200. Undefined trading
return and weighted spread (zero charging cost or sold energy) are represented
as deterministic zero summary values. Missing capacity is treated as zero;
malformed persisted numerics produce a structured error rather than silent
coercion.

## Schema consequence

Dispatch records now persist purchased and sold energy and average buy and sell
prices. Existing simulation-derived rows are backfilled from their linked
simulation efficiency and ledger financials. This preserves auditable weighted
spread and throughput inputs without introducing a materialized view.

Future explicit multi-portfolio APIs can pass a selected authorized portfolio
to the same service. Repository internals may later use aggregate views without
changing this endpoint contract.
