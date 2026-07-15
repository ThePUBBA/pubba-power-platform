# ADR-002: Explicit portfolio ownership

- Status: Accepted
- Date: 2026-07-14

## Decision

Every asset, simulation result, and dispatch event belongs to a portfolio. The
initial production portfolio is resolved by the stable code `ONLY1`; application
code never embeds its generated UUID. Supabase remains the authority for the
portfolio identity and ownership relationships.

Clients are not yet required to send `portfolio_id`. The repository resolves
the default portfolio before asset, simulation, or dispatch writes and fails
with `missing_default_portfolio` if the seed is absent. This preserves current
API request and response models while establishing ownership for all new data.

Explicit portfolio selectors and portfolio-scoped authorization will be added
with a versioned multi-portfolio API. At that point, repository reads and
business identifiers can become portfolio-scoped without forcing current
clients to change prematurely.

## Migration and rollback

The migration expands the three operational tables with nullable ownership,
idempotently seeds `ONLY1`, backfills every null owner, adds guarded foreign
keys and indexes, and only then makes ownership non-null. Known legacy asset
status values are normalized to the Phase 2 contract; unknown values stop the
migration at constraint validation rather than being silently changed.

Rollback should first deploy application code that no longer writes
`portfolio_id`, then remove non-null constraints and foreign keys. Ownership
columns and the portfolio row should be retained for recovery. Dropping them is
intentionally not part of rollback because it would silently destroy ownership
history.

