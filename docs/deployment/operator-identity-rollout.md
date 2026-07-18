# Production operator identity rollout

PUBBA Power supports provider-neutral OpenID Connect and does not select or create an identity provider. Keep `OPERATOR_AUTH_MODE=off`, `OPERATOR_PORTFOLIO_RBAC_ENABLED=false`, `OPERATOR_TRANSACTIONAL_AUDIT_ENABLED=false`, and `RECOMMENDATION_WRITES_ENABLED=false` until each stage is verified.

## Provider values

| Value | Google Workspace | Microsoft Entra ID | Auth0 | Okta |
|---|---|---|---|---|
| Issuer | Provider discovery-document issuer | Tenant-specific v2 issuer | Tenant issuer | Authorization-server issuer |
| Client ID/secret | OIDC web client | App registration | Regular web application | Web application |
| API audience | Configured PUBBA API audience | PUBBA API application ID URI | Auth0 API identifier | Authorization-server audience |
| Redirect URI | `https://<streamlit-host>/oauth2callback` | Same | Same | Same |
| Scopes | `openid email profile` | `openid email profile` | `openid email profile` | `openid email profile` |
| Stable subject | Cryptographically verified `sub` | Cryptographically verified `sub` | Cryptographically verified `sub` | Cryptographically verified `sub` |
| Email/name | `email`, `name` when released | `email`/`preferred_username`, `name` | `email`, `name` | `email`, `name` |

The backend authorizes exclusively by verified `sub`; email and display name are informational. Configure Streamlit `[auth]` secrets from `.streamlit/secrets.example.toml`, including the provider metadata URL, client ID, client secret, cookie secret, redirect URI, and exposed ID token. Configure the API with the exact issuer and audience. Never commit these values.

## First Admin bootstrap

1. Complete a test OIDC login and inspect the signed token through an approved server-side diagnostic or the provider administration console.
2. Copy the exact stable `sub`; do not use email as the subject.
3. With service-role environment variables available only in an approved administrative shell, run:
   `python scripts/bootstrap_first_admin.py --subject '<verified-sub>' --email '<email>' --display-name '<name>' --confirm-first-admin`
4. The command refuses email-like subjects, duplicate subjects, or creation when any Admin already exists.
5. Verify `/operators/me` with the Admin's real OIDC session.

Rollback: deactivate the bootstrap record with an approved database change while auth enforcement is off. Do not delete its audit history. Correct a mistaken subject only before operator activity exists; otherwise deactivate it and provision a new record through the Admin workflow.

## Ordered rollout checklist

1. Apply `202607180002_operator_identity_rbac.sql` in Supabase SQL Editor and verify tables, constraints, indexes, RLS, foreign keys, and immutable triggers.
2. Configure the chosen OIDC provider and exact redirect URI.
3. Configure Streamlit secrets.
4. Configure API issuer and audience.
5. Bootstrap exactly one first Admin.
6. Test login and `/operators/me`.
7. Test Viewer read-only behavior.
8. Test Operator capture/simulation behavior with writes still disabled.
9. Test Approver approval/dispatch permissions with writes still disabled.
10. Test Admin operator management.
11. Set `OPERATOR_AUTH_MODE=shadow`; keep writes disabled.
12. Review application logs for `missing`, `would_deny`, issuer, and audience failures without logging tokens.
13. Apply `202607180003_portfolio_rbac_transactional_audit.sql`.
14. Configure active portfolio assignments through the Admin API.
15. Set `OPERATOR_PORTFOLIO_RBAC_ENABLED=true` and test cross-portfolio 404/403 responses.
16. Set `OPERATOR_TRANSACTIONAL_AUDIT_ENABLED=true` and test atomic rollback in a non-production portfolio.
17. Set `OPERATOR_AUTH_MODE=enforce` only after all roles pass acceptance testing.
18. Set `RECOMMENDATION_WRITES_ENABLED=true` only after written operational approval.

## Rollback

Turn `RECOMMENDATION_WRITES_ENABLED=false` first. Then set auth mode to `shadow` or `off`, disable portfolio RBAC and transactional RPC use, and redeploy. Do not remove migrations, audit records, operator identities, or portfolio assignments. Provider credentials can be revoked/rotated independently. The original non-transactional paths remain available while the transactional flag is false.
