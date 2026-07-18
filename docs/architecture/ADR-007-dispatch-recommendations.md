# ADR-007: Advisory dispatch recommendations

## Current data audit

PUBBA Power currently has live CAISO RTM prices and timestamps, configured asset power,
energy, duration, lifecycle status and monthly lease cost, recorded dispatch economics,
and optional telemetry/readiness contracts. Production has no telemetry observations.
Consequently, the platform can identify and rank market opportunities, estimate a
configured full-cycle economic case, and prepare simulation inputs. It cannot confirm
state of charge, availability, live power limits, temperature, faults, degradation cost,
or physical dispatch readiness.

Market opportunity and operational readiness are separate fields. Missing telemetry is
never inferred: it produces “Operational readiness awaiting live telemetry.” No
recommendation invokes dispatch, market transactions, simulations, or persistence.

## Deterministic recommendation method

For each active asset, the engine calculates the current-price percentile in the
observed CAISO window, current movement versus up to four preceding intervals, an
efficiency-adjusted break-even price, and historical average recorded dispatch profit.
The explainable 0–100 score is capped and consists of:

- price extremity relative to the 50th percentile: up to 55 points;
- absolute spread relative to break-even: up to 25 points;
- recent price movement magnitude: up to 10 points;
- historical signal: 10 points for positive average profit, 5 when no history exists,
  and 0 for non-positive recorded history.

Recommendation thresholds are deterministic:

- strong discharge: percentile at least 80 and spread clears the larger of $5/MWh or
  10% of break-even;
- potential discharge: percentile at least 60 and positive spread;
- strong charge: percentile at most 20 and price no higher than the observed lower
  quartile;
- potential charge: percentile at most 40;
- otherwise hold.

Retired or otherwise inactive assets, stale market data, and unavailable market data
produce “Insufficient operational data” with score zero. Rankings use market and
configuration data; inactive assets cannot become the best candidate. Later telemetry
is additive and direction-specific: a charge opportunity is actionable only with fresh
charge readiness, and a discharge opportunity only with fresh discharge readiness.
“Actionable” still means operator-reviewable, never automatically executable.

## Economics and assumptions

The configured cycle uses the lesser of asset energy or power multiplied by duration.
The observed lower-quartile price is the estimated charging price. Charging energy is
discharged energy divided by configured round-trip efficiency. Break-even discharge
price includes efficiency-adjusted charging price, configurable variable O&M, and one
day of configured monthly lease cost allocated across cycle energy. Revenue uses the
current market price. Gross profit is revenue less charging, variable operating, and
allocated lease costs.

Central assumptions are:

- `RECOMMENDATION_ROUND_TRIP_EFFICIENCY` (default 0.80)
- `RECOMMENDATION_VARIABLE_OM_PER_MWH` (default 0)
- `RECOMMENDATION_MARKET_STALE_SECONDS` (default 1200)

They are explicitly labeled configured planning assumptions, not telemetry. Results are
estimates, not guaranteed profit.

## API and operator workflow

`GET /recommendations/portfolio` returns ranked advisory opportunities.
`GET /recommendations/assets/{asset_id}` returns one detailed result. Dashboard summary
responses also include recommendations so Streamlit does not make a duplicate CAISO
request. Recommendation failure does not fail the existing dashboard summary.

The Operations Command Center shows Market Opportunities ahead of detailed charts and
separates MARKET OPPORTUNITY from OPERATIONAL READINESS. “Prepare Simulation Inputs”
copies asset, node, market, power, duration and cost assumptions into session state. The
operator must navigate to Simulations, review the inputs, and explicitly submit. No
simulation or dispatch record is created by recommendation generation or preparation.

## Recommendation history design

Persistence is deliberately deferred. Persisting on a GET request would create
unbounded, refresh-driven records before retention, cadence, linkage and operator-event
requirements are approved. A future additive `recommendation_history` migration should
use an immutable recommendation ID and include portfolio/asset IDs, generated timestamp,
market/node/price/window timestamp, score, recommendation, assumptions and scoring
version, telemetry availability/readiness snapshot, concise drivers/risks, and optional
explicit links to a later simulation and dispatch. Those links must never imply
causation without an operator-created association. The design also needs retention and
idempotency rules before migration approval. No migration is required for this phase.

## Guardrails

- No stale or missing-market recommendation.
- No fabricated SOC, availability, power limit, or telemetry.
- No inactive-asset actionability.
- CAISO, telemetry, or recommendation failure cannot crash the dashboard.
- All responses say advisory only, autonomous dispatch false, and no guaranteed profit.
- No recommendation endpoint mutates Supabase or calls simulation/dispatch persistence.
