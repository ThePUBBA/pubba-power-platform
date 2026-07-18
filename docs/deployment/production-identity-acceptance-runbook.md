# Production identity rollout and acceptance runbook

This is a manual change-control procedure. It does not authorize a migration, provider purchase, user creation, production write, or switch to enforcement. Record an owner, maintenance window, approver, start/end time, evidence links, and rollback decision for every stage.

## 1. Preconditions and migration order

Apply these files in exactly this order:

1. `supabase/migrations/202607180002_operator_identity_rbac.sql`
2. `supabase/migrations/202607180003_portfolio_rbac_transactional_audit.sql`

Migration 003 depends on migration 002's `operators`, `recommendation_approvals`, and `operator_audit_events` tables and on the existing `portfolios`, `recommendation_history`, `simulation_results`, and `dispatch_events` tables. Migration 002 depends on `recommendation_history`. Before starting, confirm all earlier repository migrations through `202607180001_recommendation_history.sql` are already present.

Risks: applying out of order fails on missing relations; an incorrectly copied file can leave only part of its statements applied; RLS intentionally has no browser-facing policies and the backend service role remains the data path; RPC activation before assignments exist denies non-Admin operators; a wrong OIDC issuer/audience locks users out in enforce mode. Keep every feature flag off during application.

## 2. Manual Supabase SQL application

For each file, use the repository at the exact deployed commit. Obtain raw SQL locally with `sed -n '1,$p' <filename>` or open the file and copy its complete contents. In Supabase Dashboard, select the production project, open **SQL Editor**, create a new query, paste exactly one complete migration, recheck the project name and filename, then choose **Run** once. Do not combine the two migrations.

Expected success is a completed query with no SQL error. Messages that an extension or object already exists can be notices because creation is idempotent; any error is a stop condition. Save the SQL Editor execution record with the change ticket.

### Migration 002

File: `supabase/migrations/202607180002_operator_identity_rbac.sql`

Expected objects:

- Tables: `operators`, `recommendation_approvals`, `operator_audit_events`
- Operator role/status and approval/outcome constraints
- Recommendation and operator foreign keys
- Operator, approval, and audit indexes
- RLS on all three tables
- Immutable update/delete triggers on approvals and audit events

Read-only verification:

```sql
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in ('operators','recommendation_approvals','operator_audit_events')
order by table_name;

select c.conname, c.contype, c.conrelid::regclass as table_name,
       pg_get_constraintdef(c.oid) as definition
from pg_constraint c
where c.conrelid in (
  'public.operators'::regclass,
  'public.recommendation_approvals'::regclass,
  'public.operator_audit_events'::regclass
)
order by table_name::text, c.conname;

select c.relname as table_name, c.relrowsecurity
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('operators','recommendation_approvals','operator_audit_events')
order by c.relname;

select event_object_table, trigger_name, action_timing, event_manipulation
from information_schema.triggers
where trigger_schema = 'public'
  and event_object_table in ('recommendation_approvals','operator_audit_events')
order by event_object_table, trigger_name, event_manipulation;
```

Expected: three table rows; the documented checks and foreign keys; `relrowsecurity=true` for all three; immutable triggers for update/delete.

### Migration 003

File: `supabase/migrations/202607180003_portfolio_rbac_transactional_audit.sql`

Expected objects:

- Table: `operator_portfolio_access`
- Unique operator/portfolio assignment and role constraint
- Operator, portfolio, and creator foreign keys
- RLS and two assignment indexes
- Portfolio-role and metadata-sanitization helpers
- Audited capture, recommendation action, operator update, and portfolio-access RPCs
- RPC execute permission limited to `service_role`; public execute revoked

Read-only verification:

```sql
select c.relname as table_name, c.relrowsecurity
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname = 'operator_portfolio_access';

select conname, contype, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.operator_portfolio_access'::regclass
order by conname;

select indexname, indexdef
from pg_indexes
where schemaname = 'public' and tablename = 'operator_portfolio_access'
order by indexname;

select p.proname, pg_get_function_identity_arguments(p.oid) as arguments,
       p.prosecdef as security_definer,
       has_function_privilege('anon', p.oid, 'EXECUTE') as anon_execute,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_execute,
       has_function_privilege('service_role', p.oid, 'EXECUTE') as service_role_execute
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.proname like 'pubba_%'
order by p.proname;
```

Expected: RLS true; documented constraints/indexes; audited functions are security-definer; `anon_execute=false` and `authenticated_execute=false`; audited RPCs have `service_role_execute=true`. Stop if any result differs.

## 3. OIDC provider decision guide

Do not select a provider solely from this table. Prefer the workforce directory PUBBA already administers so joiner/mover/leaver actions remain in one system. Confirm current quotes directly with the vendor.

| Provider | Small-team fit | Setup | Employee lifecycle | MFA | Cost and scale |
|---|---|---|---|---|---|
| Google Workspace | Strong if corporate mail/accounts already use Workspace | Low to moderate | Central Admin console | Two-step authentication and security controls | Per-user Workspace subscription; straightforward for small teams and scales to Enterprise |
| Microsoft Entra ID | Strong if Microsoft 365 is already authoritative | Moderate | Strong directory, groups, Conditional Access, provisioning | Basic MFA/security defaults; advanced control depends on licensing | P1/P2 may already be bundled with Microsoft 365; strong enterprise/hybrid scale |
| Auth0 | Strong for an application-first team without a workforce directory | Moderate | Application-oriented; workforce lifecycle may require another source | Multiple factors, with plan-dependent availability | Free/entry tiers exist; production B2B, MFA, support, and scale can change cost materially |
| Okta Workforce Identity | Strong when dedicated workforce IAM is desired | Moderate to high | Strong lifecycle management and integrations | Adaptive/phishing-resistant MFA offerings | Per-user suites and possible contract minimums; strong enterprise scale |

Official decision inputs: [Google Workspace plans](https://workspace.google.com/pricing), [Google Admin controls](https://workspace.google.com/products/admin/), [Microsoft Entra pricing](https://www.microsoft.com/en-us/security/business/microsoft-entra-pricing), [Microsoft Entra MFA licensing](https://learn.microsoft.com/en-us/entra/identity/authentication/concept-mfa-licensing), [Auth0 pricing](https://auth0.com/pricing), [Auth0 MFA](https://auth0.com/docs/secure/multi-factor-authentication), [Okta pricing](https://www.okta.com/pricing/), and [Okta Workforce Identity](https://www.okta.com/products/workforce-identity/).

Decision evidence: existing directory, directory owner, supported offboarding process, MFA policy, recovery process, required compliance, expected operator count, annual cost, and security approval.

## 4. OIDC values and compatibility

Record these without placing secrets in the ticket:

| Required value | Destination | Requirement |
|---|---|---|
| Client ID | Streamlit secret | OIDC web application identifier |
| Client secret | Streamlit secret | Secret manager only; rotate after suspected exposure |
| Server metadata URL | Streamlit secret | HTTPS `/.well-known/openid-configuration` URL |
| Redirect URI | Streamlit secret and provider | Exact `https://<app-host>/oauth2callback` match |
| Cookie secret | Streamlit secret | Independent cryptographically random value |
| Issuer | API environment | Exact discovery-document `issuer`, without an accidental tenant mismatch |
| Audience | API environment | API audience expected in the JWT `aud` claim |
| Scopes | Provider/application | `openid email profile` |
| Subject claim | Backend contract | Stable signed `sub`; sole identity lookup key |
| Email claim | Profile/reference | Signed `email`; never authorization key |
| Display-name claim | Profile/reference | Usually signed `name`; never authorization key |

Compatibility acceptance: `st.login()` redirects successfully; `st.user.is_logged_in` is true; `st.user.tokens.id` is server-accessible; FastAPI validates signature, issuer, audience, expiry, issued-at, and subject; discovery issuer matches configuration; discovery supplies an HTTPS JWKS URI; login/logout does not expose a token in UI or logs.

Production Streamlit template (real values go only in Streamlit Secrets):

```toml
[auth]
redirect_uri = "https://<APP-HOST>/oauth2callback"
cookie_secret = "<RANDOM-SECRET>"
client_id = "<OIDC-CLIENT-ID>"
client_secret = "<OIDC-CLIENT-SECRET>"
server_metadata_url = "https://<OIDC-HOST>/.well-known/openid-configuration"
expose_tokens = ["id"]
```

FastAPI deployment environment (not Streamlit secrets):

```text
OPERATOR_OIDC_ISSUER=https://<EXACT-ISSUER>
OPERATOR_OIDC_AUDIENCE=<EXACT-API-AUDIENCE>
OPERATOR_AUTH_MODE=off
OPERATOR_RBAC_STORAGE_ENABLED=false
OPERATOR_PORTFOLIO_RBAC_ENABLED=false
OPERATOR_TRANSACTIONAL_AUDIT_ENABLED=false
RECOMMENDATION_WRITES_ENABLED=false
```

## 5. First Admin dry run

Obtain `sub` from a cryptographically verified ID token through an approved server-side diagnostic or provider console. Email alone is insufficient.

Dry run; performs reads and validation but no insert:

```bash
python scripts/bootstrap_first_admin.py \
  --subject '<VERIFIED-OIDC-SUB>' \
  --email '<ADMIN-EMAIL>' \
  --display-name '<ADMIN-DISPLAY-NAME>' \
  --confirm-first-admin
```

Expected: `Dry run passed... no operator was created`. The script rejects an email-like subject, an existing subject, a missing confirmation, or any existing Admin.

After separate change approval, repeat with `--execute`. Capture the returned operator UUID, then remove service-role credentials from the administrative shell. Never paste the service-role key into Streamlit or a ticket.

## 6. Role acceptance matrix

Use real approved test identities represented below only by placeholders. Assign them to a non-critical acceptance portfolio and also retain a second portfolio to prove denial.

| Identity | Assigned role | Must succeed | Must fail |
|---|---|---|---|
| `<VIEWER-SUB>` | Viewer | Assigned portfolio overview/history | Capture, acknowledgement, simulation/dispatch links, unassigned portfolio |
| `<OPERATOR-SUB>` | Operator | Assigned portfolio reads, capture, acknowledge, prepare/link simulation | Approval, dispatch link, unassigned portfolio |
| `<APPROVER-SUB>` | Approver | Operator actions, approve/reject, dispatch link in assignment | Unassigned portfolio |
| `<ADMIN-SUB>` | Admin | Global portfolio visibility, operator and assignment management | Invalid inputs; Admin is still subject to active status |

For every case capture request path, status, safe error code, portfolio, operator UUID, audit row where applicable, and screenshot/API response without tokens. UI filtering is supporting evidence only; API denial is required.

## 7. Staged acceptance sequence

### Shadow

Set only `OPERATOR_AUTH_MODE=shadow`. Keep the four other flags false. Redeploy. Verify login/logout, verified subject resolution, operator role resolution, anonymous and invalid-token `would_deny` logs, all existing reads, zero new business/audit rows, and write-disabled responses. Observe at least one normal operating window with no unexplained identity failure before advancing.

### RBAC storage

Set `OPERATOR_RBAC_STORAGE_ENABLED=true`; leave writes and portfolio/transaction flags false. Verify known active profiles resolve, unknown users fail provisioning, inactive users fail, bootstrap Admin resolves, and an approved Admin role/status change persists. Do not advance on any mismatch.

### Portfolio RBAC

After migration 003 and assignments, set `OPERATOR_PORTFOLIO_RBAC_ENABLED=true`. Verify the selector contains only authorized portfolios; the role matrix; direct API cross-portfolio denial; and cross-portfolio simulation/dispatch link denial before object disclosure.

### Transactional audit

In a disposable acceptance portfolio, set `OPERATOR_TRANSACTIONAL_AUDIT_ENABLED=true` while recommendation writes remain false. For each supported action, obtain before counts/business state, temporarily enable writes only in the isolated acceptance environment under a separate approval, perform one valid action, and verify exactly one business change plus one audit event.

For rollback testing, deliberately cause the audit insert to fail inside a transaction using an isolated database test strategy approved by the database owner—for example, invoke the RPC with an invalid operator UUID or invalid constrained payload. Verify the RPC fails and both the business state and audit count remain identical to their before snapshots. Then cause the business validation to fail and again verify neither side changes. Never alter triggers or constraints on production and never use important records.

Actions: capture, acknowledge, simulation review/link, approve, reject, dispatch link, operator role/status change, and portfolio access change.

### Enforce

Only after signed acceptance, set `OPERATOR_AUTH_MODE=enforce`. Verify anonymous 401, role denial 403, protected portfolio 404, valid role access, login/logout, API health, no cross-portfolio exposure, and no tokens in logs. Keep `RECOMMENDATION_WRITES_ENABLED=false`.

## 8. Recommendation-write approval gate

Before enabling writes, require: migrations verified; OIDC security approval; first Admin and recovery Admin established through approved workflows; all roles passed; inactive/unknown users denied; portfolio denials passed; transactional success and rollback evidence passed; shadow observation accepted; enforce-mode smoke test passed; monitoring and on-call owner documented; rollback exercised; business owner, security owner, and operations owner approved the exact change window.

Only then may a separate change set `RECOMMENDATION_WRITES_ENABLED=true`.

## 9. Rollback order

1. Set `RECOMMENDATION_WRITES_ENABLED=false`.
2. Set `OPERATOR_AUTH_MODE=shadow` or `off`.
3. Set `OPERATOR_TRANSACTIONAL_AUDIT_ENABLED=false`.
4. Set `OPERATOR_PORTFOLIO_RBAC_ENABLED=false`.
5. Set `OPERATOR_RBAC_STORAGE_ENABLED=false` if necessary.
6. Redeploy and verify health plus existing reads.

Never delete or rewrite operator identities, approvals, assignments, migrations, or audit history. Preserve evidence and record the rollback reason.

## 10. Production acceptance checklist

- [ ] Change owner, approvers, window, evidence location, and rollback authority recorded
- [ ] Earlier schema through recommendation history verified
- [ ] Migration 002 applied and read-only verification passed
- [ ] Migration 003 applied and read-only verification passed
- [ ] Existing workforce directory and OIDC provider decision approved
- [ ] Streamlit secrets configured without exposure
- [ ] API issuer/audience configured and discovery/JWKS verified
- [ ] First Admin dry run passed and approved execution completed
- [ ] Viewer acceptance passed
- [ ] Operator acceptance passed
- [ ] Approver acceptance passed
- [ ] Admin acceptance passed
- [ ] Shadow mode observed and evidence approved
- [ ] RBAC storage enabled and accepted
- [ ] Portfolio RBAC enabled and cross-portfolio tests passed
- [ ] Transactional auditing enabled and both rollback tests passed
- [ ] Enforce mode enabled and smoke test passed
- [ ] Recommendation writes remain disabled until separate written approval
- [ ] Recommendation-write approval obtained and scheduled, if applicable
- [ ] Final health/read smoke tests passed
- [ ] Completion or rollback recorded
