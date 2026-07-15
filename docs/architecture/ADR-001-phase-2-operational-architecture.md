# ADR-001: Phase 2 operational portfolio architecture

- Status: Accepted
- Date: 2026-07-14
- Metric version: 1.0

## Decision

Phase 2 is an operational portfolio and dispatch-intelligence layer on top of
the existing simulation engine. Supabase is the authoritative operational
datastore, and FastAPI is the sole application API. Presentation clients must
not own KPI formulas, write directly with a Supabase service-role credential,
or generate recurring reports.

The system separates market/simulation, operational portfolio, analytics,
reporting, and presentation concerns. Every dispatch is an auditable energy
transaction. Portfolio aggregates, exports, and reports must reconcile to the
dispatch ledger.

## Stable domain contracts

Asset lifecycle statuses are `draft`, `active`, `unavailable`, `maintenance`,
and `retired`. Temporary availability is not represented by retirement.

Dispatch statuses are `draft`, `scheduled`, `charging`, `holding`,
`discharging`, `completed`, `cancelled`, and `failed`.

Settlement statuses are `not_applicable`, `unsettled`, `estimated`, `settled`,
and `disputed`. Estimated, realized, and settled economics must remain
distinguishable.

## KPI definitions (metric version 1.0)

All monetary calculations use decimal arithmetic. Period boundaries use the
portfolio reporting time zone; persisted timestamps remain UTC `timestamptz`.

| KPI | Definition |
| --- | --- |
| Total portfolio profit | Sum of net profit for completed, financially settled dispatches |
| Revenue | Sum of gross revenue within the reporting period |
| Charging cost | Sum of charging cost within the reporting period |
| Purchased energy | Sum of purchased energy MWh |
| Sold energy | Sum of sold energy MWh |
| Energy throughput | Purchased energy MWh + sold energy MWh, explicitly labelled as throughput |
| Trading return | Net profit / charging cost |
| Operational ROI | Net profit / (charging cost + lease allocation + variable operating cost) |
| Initial utilization | Discharged MWh / (nameplate MW × dispatch duration hours) |
| Portfolio spread | Sum of (dispatch spread × sold MWh) / total sold MWh |

Ratios with a zero denominator are undefined and serialize as null, not zero.
The utilization response must identify `dispatch_window_proxy` until available
hours can be calculated from availability history.

Fleet capacity is always exposed separately as power MW, energy MWh, available
energy MWh, and duration hours. MW and MWh are never combined into one value.

## Units and naming

Fields use explicit suffixes: `_mw`, `_mwh`, `_per_mwh`, `_pct`, and `_at`.
Database monetary values use PostgreSQL `numeric`; identifiers use UUIDs, with
separate readable operator codes. API responses and reports include
`metric_version` whenever Phase 2 metrics are returned.

## Error contract

Existing API error responses remain compatible during additive evolution. The
target versioned error envelope is:

```json
{
  "error": {
    "code": "ASSET_NOT_FOUND",
    "message": "The requested asset does not exist.",
    "request_id": "uuid",
    "details": {}
  }
}
```

A correlation/request ID must be propagated through logs and audit records
before the versioned envelope becomes the public contract.

## Deferred decisions

Separate ADRs are required before schema implementation for operational-day
boundaries and daylight-saving behavior, dispatch source-of-truth hierarchy,
post-settlement corrections, portfolio tenancy, and reporting data cutoff.

## Consequences

Existing endpoints remain unchanged in this decision-only increment. New
portfolio calculations live in backend services or database views and are
covered by reconciliation tests. Schema changes use expand-migrate-contract
migrations, and UI replacements do not require moving business logic.

