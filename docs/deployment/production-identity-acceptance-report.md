# Production identity acceptance report

Date: 2026-07-18  
Repository baseline: `3235702627149bbf5aa81674de47e3a4ab543245`  
Decision: **NO-GO for enforce mode and recommendation writes**

This report records only evidence observable from the authorized local and public production interfaces. No migration, identity, assignment, configuration flag, or production record was changed. No token or secret was collected.

## Environment evidence

- `main` matched `origin/main` at the start of acceptance.
- `https://api.pubbapower.com/health`: HTTP 200, API status `ok`, Supabase `connected`.
- Dashboard summary, recommendations, recommendation history, simulations, dispatches, and portfolio telemetry endpoints: HTTP 200.
- `/operators/me` without a credential: HTTP 401 as designed.
- Recommendation responses remain advisory and report `autonomous_dispatch=false`.
- Public DNS for `app.pubbapower.com` did not resolve from the acceptance environment. The repository documents it as an intended—not confirmed active—domain.
- The acceptance shell had no production Supabase URL/service-role credential or OIDC issuer/audience. GitHub contained no repository Actions secrets, variables, or deployment records exposing the external Render/Streamlit configuration.

## Acceptance evidence matrix

`BLOCKED` means required production access, approved identity, or configuration evidence was not available; it does not mean the product failed.

| Test | Role | Portfolio | Expected | Actual | HTTP | Audit event | Result | Notes |
|---|---|---|---|---|---:|---|---|---|
| API health | None | N/A | Healthy | API and Supabase connected | 200 | N/A | PASS | Read-only public check |
| Dashboard summary | None/off mode | `ONLY1` | Existing read remains operational | Portfolio summary returned | 200 | No | PASS | No identity assertion |
| Recommendations | None/off mode | `ONLY1` | Advisory read | Advisory response; autonomous dispatch false | 200 | No | PASS | Market status unavailable at observation |
| Recommendation history | None/off mode | `ONLY1` | Existing read | Empty history response | 200 | No | PASS | No write attempted |
| Simulations | None/off mode | `ONLY1` | Existing read | Four records returned | 200 | No | PASS | Read-only |
| Dispatches | None/off mode | `ONLY1` | Existing read | Four records returned | 200 | No | PASS | Read-only |
| Telemetry | None/off mode | `ONLY1` | Contract remains operational | Endpoint returned; telemetry unavailable | 200 | No | PASS | No real BMS/SCADA source expected |
| Missing operator credential | None | N/A | 401 | Authentication required | 401 | No | PASS | `/operators/me` |
| Migration 002 objects | Admin DB reader | Production | All objects verified | No authorized database metadata connection | N/A | N/A | BLOCKED | Run read-only verification SQL |
| Migration 003 objects/RPCs | Admin DB reader | Production | All objects and grants verified | No authorized database metadata connection | N/A | N/A | BLOCKED | Run read-only verification SQL |
| OIDC discovery/JWKS | Approved identity owner | N/A | Discovery, issuer, audience, JWKS valid | Provider/configuration unavailable | N/A | N/A | BLOCKED | Do not infer provider |
| Streamlit redirect/login/logout | Approved identity | Assigned | Login/logout works | Active host and secrets unavailable | N/A | N/A | BLOCKED | `app.pubbapower.com` unresolved |
| First Admin dry run | Admin candidate | Global | Dry run passes, no insert | No approved subject or administrative environment | N/A | No | BLOCKED | Do not use email as subject |
| Viewer matrix | Viewer | Assigned/unassigned | Read assigned; deny writes/unassigned | No approved Viewer identity | N/A | Expected on denial where configured | BLOCKED | API evidence required |
| Operator matrix | Operator | Assigned/unassigned | Allowed workflow; deny dispatch/cross-portfolio | No approved Operator identity | N/A | Expected | BLOCKED | Writes remain disabled |
| Approver matrix | Approver | Assigned/unassigned | Approve/link dispatch assigned only | No approved Approver identity | N/A | Expected | BLOCKED | Writes remain disabled |
| Admin matrix | Admin | Global | Global visibility and management | No bootstrapped Admin session | N/A | Expected | BLOCKED | Global policy implemented in code |
| Shadow observation | Mixed | Assigned | Would-deny logs; reads continue | Production mode/log access unavailable | N/A | No business writes | BLOCKED | Requires Render and Streamlit access |
| Transaction rollback | Authorized roles | Isolated | No partial business/audit state | No isolated production test records or DB access | N/A | Rolled back | BLOCKED | Never use important records |

## Migration verification required

Run the read-only queries in `docs/deployment/production-identity-acceptance-runbook.md` against the production Supabase project. Migration 002 must precede 003. Stop if any table, constraint, foreign key, index, RLS flag, immutable trigger, RPC, or service-role/public privilege differs.

## OIDC verification required

An authorized identity administrator must record, without secret values:

- Provider and tenant
- Discovery URL HTTP success
- Discovery issuer exactly matching `OPERATOR_OIDC_ISSUER`
- Configured API audience exactly matching `OPERATOR_OIDC_AUDIENCE`
- HTTPS JWKS retrieval and signing-key match
- Exact active Streamlit redirect URI
- `openid email profile` scopes
- Signed stable `sub`, email, and optional display-name behavior
- Successful Streamlit login/logout and server-side ID-token availability

## Monitoring acceptance

The application now emits sanitized structured `security_event` values for:

- `authentication_missing`
- `authentication_invalid`
- `operator_unknown`
- `operator_inactive`
- `operator_role_invalid`
- `portfolio_access_denied`
- `portfolio_permission_denied`
- `oidc_discovery_failed`
- `oidc_token_verification_failed`
- `transactional_operator_action_failed`

Events exclude credentials, tokens, authorization headers, email claims, and raw JWT claims. Acceptance still requires confirming these fields arrive in the production logging system, are searchable, have retention/alert ownership, and do not reveal secrets.

## Enforce-mode go/no-go

Current decision: **NO-GO**. All items must be evidenced before changing `OPERATOR_AUTH_MODE=enforce`:

- [ ] Migrations 002 and 003 verified in production
- [ ] OIDC discovery, issuer, audience, JWKS, scopes, and redirect verified
- [ ] First Admin dry run and separately approved execution completed
- [ ] Viewer, Operator, Approver, and Admin matrices passed with approved identities
- [ ] Shadow mode observed through an agreed operating window
- [ ] Known, unknown, inactive, and invalid-role cases passed
- [ ] Portfolio selector and direct-API cross-portfolio denial passed
- [ ] Cross-portfolio simulation and dispatch links failed without disclosure
- [ ] Atomic success, business failure, and audit failure evidence passed on isolated records
- [ ] Authentication and authorization security events visible and sanitized
- [ ] Dashboard login/logout and page rendering passed
- [ ] API health stayed HTTP 200
- [ ] Rollback was rehearsed and an authorized rollback owner is available

## Recommendation-write gate

Keep `RECOMMENDATION_WRITES_ENABLED=false`. In addition to every enforce-mode item, require written approval from the operations owner, security owner, database owner, and business owner; an isolated successful end-to-end workflow; alerting/on-call ownership; confirmed rollback timing; and a separately scheduled change window. Enabling enforce mode does not itself authorize recommendation writes.

## Exact manual actions

1. Give the acceptance operator read-only Supabase metadata access or execute the runbook verification SQL and return sanitized results.
2. Identify the already-approved OIDC provider and active Streamlit hostname; do not send client secrets or tokens.
3. Confirm Render environment variable names/modes without disclosing values.
4. Configure the Streamlit redirect and secrets through its secret manager.
5. Supply an explicitly approved Admin identity and verified `sub`; run bootstrap without `--execute` first.
6. Obtain separate approval before `--execute`.
7. Provision approved Viewer, Operator, and Approver identities through the provider and operator-management workflow.
8. Assign a non-critical acceptance portfolio plus a separate denial-test portfolio.
9. Set shadow mode only, keep writes disabled, redeploy, and collect one operating window of sanitized logs.
10. Progress RBAC storage, portfolio RBAC, and transactional auditing one flag at a time with acceptance evidence after each.
11. Rehearse rollback.
12. Hold an explicit go/no-go review for enforce mode.
13. Hold a separate approval and change window for recommendation writes.
