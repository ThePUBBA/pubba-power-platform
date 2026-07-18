# ADR-008: Recommendation history, decision audit, and outcomes

## Relationship audit

Recommendation history uses existing stable identifiers. `portfolio_id` references
`portfolios.id` (UUID), `asset_id` references the unique business identifier
`assets.asset_id` (text), `simulation_id` references `simulation_results.id` (UUID), and
`dispatch_id` references `dispatch_events.id` (UUID). External simulation and dispatch
identifiers remain intact but are not foreign keys. Names and timestamp proximity are
never used to infer links or causation.

The history record is an immutable snapshot of the recommendation, market observation,
estimated economics, assumptions, telemetry availability, readiness, explanation,
drivers, risks, and missing inputs. Only explicit simulation/dispatch links,
acknowledgement metadata, link timestamps, and `updated_at` can change. A database
trigger enforces this boundary.

## Controlled capture and versioning

The centralized recommendation engine version is `RECOMMENDATION_ENGINE_VERSION`.
Every snapshot stores it. `POST /recommendations/{asset_id}/capture` recomputes the
current recommendation, requires fresh market data and a known asset, and saves the
snapshot only after explicit authenticated operator action. `RECOMMENDATION_WRITES_ENABLED`
is false by default and `X-Recommendation-Key` is compared with the server-side
`RECOMMENDATION_WRITE_TOKEN` using constant-time comparison.

Canonical snapshot content is SHA-256 hashed. An identical asset/hash captured within
`RECOMMENDATION_CAPTURE_DEDUP_SECONDS` (default 300) returns the existing record rather
than writing a duplicate. No previous snapshot is overwritten. Dashboard and
recommendation GET requests never capture records.

## APIs and explicit decisions

- `POST /recommendations/{asset_id}/capture`
- `GET /recommendations/history`
- `GET /recommendations/history/analytics`
- `GET /recommendations/history/{recommendation_id}`
- `POST /recommendations/history/{recommendation_id}/acknowledge`
- `POST /recommendations/history/{recommendation_id}/link-simulation`
- `POST /recommendations/history/{recommendation_id}/link-dispatch`

History filters support portfolio, asset, direction, generated range, minimum score,
and presence of simulation/dispatch links. Detail reads the stored snapshot and never
recomputes it with current market data. Links accept database record UUIDs and validate
portfolio and asset ownership. Existing links cannot be silently replaced. Operator
identity is not available, so acknowledgement is attributed to the authenticated
operator workflow rather than an invented person.

## Outcome and audit semantics

Outcomes are `no_action_taken`, `simulation_only`, `dispatch_pending`,
`dispatch_completed`, or `outcome_unavailable`. Simulation records are calculated
estimates and never become realized economics. Only an explicitly linked dispatch with
`status=completed` supplies realized revenue, charging cost, profit, margin, absolute
variance, and percentage error where the estimate is nonzero. A dispatch occurring does
not establish recommendation quality or causation.

The timeline contains only timestamps backed by stored records: recommendation
generation/capture, acknowledgement, explicit links, and completed dispatch ledger
updates. It does not fabricate simulation review or operator actions. A linked
simulation comparison shows the original recommendation estimate, simulation estimate,
and difference.

Portfolio analytics always show sample size. Model accuracy remains unavailable below
10 explicitly linked completed outcomes. Even above that threshold, analytics only mark
the data ready for a separately approved calibration review; weights never change
automatically.

## Calibration foundation

Future versioned calibration may compare linked outcomes against price-extremity,
spread, momentum and historical-profit weights, efficiency, variable O&M, and an
approved degradation-cost input. Any algorithm or assumption change requires an
explicit new engine version, review, tests, and approval. Existing snapshots must never
be recomputed.

## Manual deployment

The additive migration is:

`supabase/migrations/202607180001_recommendation_history.sql`

Review it, apply it once through the Supabase SQL Editor or approved migration runner,
verify the table, foreign keys, indexes, trigger and RLS, then deploy the API. Keep
`RECOMMENDATION_WRITES_ENABLED=false` until verification is complete. Generate a
high-entropy write token in the secret manager, configure the authorized operator
workflow, test one capture and duplicate response, and only then enable audit writes.
No migration is applied by application startup or this repository change.
