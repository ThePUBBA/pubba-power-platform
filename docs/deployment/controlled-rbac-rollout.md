# Controlled production RBAC rollout

This runbook prepares PUBBA Power for acceptance testing without changing production
data or enabling recommendation writes, autonomous dispatch, or authentication
enforcement. Production values and evidence must be verified by an authorized owner;
repository defaults are fail-closed but do not prove deployed environment values.

## Authorization architecture

1. Streamlit authenticates with Google OIDC and forwards only
   `st.user.tokens["id"]` as a bearer credential.
2. FastAPI validates signature, issuer, audience, expiry, issued-at, and signed `sub`.
3. FastAPI looks up the exact signed `sub` in `operators.auth_subject`; email, display
   name, browser headers, and client role claims do not authorize access.
4. Unknown, inactive, and invalid-role operator profiles fail closed.
5. The database global role supplies the backend permission set. When portfolio RBAC
   is enabled, an active `operator_portfolio_access` row is also required for every
   non-Admin portfolio request. Its optional `role_override` can reduce effective
   permissions. Admin remains active-status constrained but has global portfolio access.
6. Transactional RPCs enforce the effective portfolio role again in PostgreSQL and
   atomically couple supported business changes to sanitized audit events.

## Implemented permission matrix

All authenticated active roles may use existing read and simulation surfaces unless a
route is specifically protected below. This is a legacy compatibility boundary, not a
claim that all reads are portfolio-isolated.

| Capability | Viewer | Operator | Approver | Admin |
|---|---:|---:|---:|---:|
| Recommendation/history read | Yes | Yes | Yes | Yes |
| Run/read simulations | Yes | Yes | Yes | Yes |
| Capture recommendation | No | Yes | Yes | Yes |
| Acknowledge recommendation | No | Yes | Yes | Yes |
| Link/review simulation | No | Yes | Yes | Yes |
| Approve or reject | No | No | Yes | Yes |
| Link dispatch evidence | No | No | Yes | Yes |
| Create/update assets | No | No | No | Yes |
| Read operator directory | No | No | No | Yes |
| Create/update operators | No | No | No | Yes |
| Manage portfolio assignments | No | No | No | Yes |
| Autonomous dispatch/control | No | No | No | No |

Recommendation mutations additionally require both
`RECOMMENDATION_WRITES_ENABLED=true` and
`OPERATOR_RBAC_STORAGE_ENABLED=true`. Assignment administration additionally requires
transactional auditing. No role can bypass these gates.

## Portfolio model

`operators` stores the unique stable `auth_subject`, informational profile fields,
global role, and active/inactive status. `operator_portfolio_access` has one unique row
per operator and portfolio, an active flag, optional non-Admin role override, creator,
and timestamps. Non-Admins receive only active assignments. A single assignment becomes
the default portfolio; multiple assignments require explicit selection; no assignment
returns a non-disclosing 404. Unauthorized portfolio reads and writes return 404 before
downstream linked-object lookup. Admin can list and access multiple portfolios globally.

The API applies auth-mode evaluation to every user-facing read, export, market,
telemetry, and simulation route. In `enforce` mode these routes require an active,
provisioned operator; `off` and `shadow` preserve the documented compatibility behavior.
The root and infrastructure health routes remain public, and machine telemetry ingestion
continues to use its separate write flag and token. Portfolio scoping currently applies
to dashboard/portfolio summaries, recommendations/history, simulations, and dispatch-list
reads. Full portfolio isolation for the remaining authenticated global reads is a later
rollout phase and is not implied by operator-level authentication.

## Feature flags

| Flag | False/off behavior | Enabled behavior | Rollout rule |
|---|---|---|---|
| `OPERATOR_AUTH_MODE` | `off`: protected reads remain compatible; operator endpoints/writes still authenticate. `shadow`: credentials are evaluated and denials logged as `would_deny`, but reads continue. | `enforce`: protected reads require a valid active provisioned operator. | Do not enable automatically. |
| `OPERATOR_RBAC_STORAGE_ENABLED` | Operator workflow writes fail with 503; approval/audit enrichment is not loaded. | Enables approval/audit storage and Admin profile changes. | Enable only after role acceptance. |
| `OPERATOR_PORTFOLIO_RBAC_ENABLED` | Global roles and legacy portfolio behavior apply. | Non-Admins require active assignments and effective portfolio roles; Admin is global. | Enable after assignment and denial tests. |
| `OPERATOR_TRANSACTIONAL_AUDIT_ENABLED` | Supported writes use legacy business-write plus audit-write paths. | Supported mutations use audited PostgreSQL RPCs; RPC failure has no legacy fallback. | Enable only in an approved acceptance portfolio first. |
| `RECOMMENDATION_WRITES_ENABLED` | All recommendation mutations fail closed. | Mutations may proceed only with every other identity, role, portfolio, and storage gate satisfied. | Keep false throughout this rollout. |

## Required rollout sequence

Each phase requires a named owner, maintenance window, safe evidence, acceptance signoff,
and tested rollback. Do not create fake production identities; use approved workforce
identities and a non-critical acceptance portfolio.

1. **Phase A — Admin-only production verification:** verify login/logout, `/operators/me`,
   active Admin role, global portfolio list, health, and sanitized logs. Keep all feature
   flags unchanged and recommendation writes false.
2. **Phase B — Viewer acceptance:** provision an approved Viewer and verify assigned
   reads; capture, acknowledgement, approval, dispatch link, operator management, and
   unassigned portfolio access must fail.
3. **Phase C — Operator acceptance:** verify assigned reads, simulation use, and UI
   availability; role denial must still precede disabled write gates for disallowed
   approval/dispatch actions. Do not enable writes.
4. **Phase D — Approver acceptance:** verify assigned read/UI permissions and denial
   outside assignments. Do not create approval records while writes are disabled.
5. **Phase E — Portfolio assignments:** assign approved identities to a non-critical
   acceptance portfolio; verify single-default, multiple-selection, inactive assignment,
   and reducing role override behavior.
6. **Phase F — Cross-portfolio denial:** directly call read and write APIs for a second
   unassigned portfolio; require non-disclosing 404/403 results and no downstream object
   disclosure or audit/business mutation.
7. **Phase G — RBAC storage:** set only `OPERATOR_RBAC_STORAGE_ENABLED=true`; verify known,
   unknown, inactive, invalid-role, Admin management, and audit-enrichment behavior.
8. **Phase H — Portfolio RBAC:** set only `OPERATOR_PORTFOLIO_RBAC_ENABLED=true` in
   addition; repeat every assigned/unassigned and role-override case.
9. **Phase I — Transactional audit:** set
   `OPERATOR_TRANSACTIONAL_AUDIT_ENABLED=true` first in an isolated acceptance
   environment. Recommendation writes remain false in production. Under separate
   approval, prove one atomic success and forced business/audit failures with unchanged
   before/after counts.
10. **Phase J — Shadow observation:** set `OPERATOR_AUTH_MODE=shadow`; observe at least
    one agreed operating window, investigate every `would_deny`, verify no tokens or
    claims in logs, and confirm no business writes.
11. **Phase K — Enforce go/no-go:** hold a signed review. Enforce remains a no-go until
    all phases pass, rollback is rehearsed, monitoring/on-call ownership exists, and the
    legacy read/simulation authorization boundary is explicitly resolved.

Rollback order is recommendation writes false, auth mode shadow/off, transactional audit
false, portfolio RBAC false, and RBAC storage false if required, followed by redeploy and
read-only health checks. Never delete identities, assignments, audit records, or migration
history during rollback.

## Telemetry and pilot-asset gate

Before connecting a real telemetry source or pilot asset, complete source authentication,
least-privilege ingestion credentials, asset-to-portfolio ownership validation, payload
validation and replay/idempotency tests, freshness/staleness alarms, clock/timezone checks,
rate limits, monitoring and on-call ownership, data-retention approval, and an explicit
proof that telemetry cannot trigger autonomous dispatch. `TELEMETRY_WRITES_ENABLED` and
its write credential require a separate controlled change; they are outside this RBAC
rollout.
