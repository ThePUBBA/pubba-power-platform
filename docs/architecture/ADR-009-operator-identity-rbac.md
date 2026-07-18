# ADR-009: Operator identity, RBAC, and approval auditing

## Authentication audit

Before this phase, Streamlit had no login, session identity, OIDC integration, or
trustworthy hosting identity. FastAPI was read-public and recommendation writes used a
shared `X-Recommendation-Key`. Supabase was accessed only by FastAPI with its service
role key; Supabase Auth was not configured. Browser headers, form emails, shared tokens,
and Streamlit Community Cloud account identity are therefore not accepted as operator
identity. No existing OIDC, SSO, or Supabase Auth provider was discoverable in the
repository or deployment configuration.

## Selected architecture

PUBBA Power now supports any existing standards-compliant OIDC provider without naming
or inventing one. Streamlit uses its native OIDC session support and exposes only the ID
token to server-side Python. The dashboard forwards that token as `Authorization:
Bearer` to FastAPI. FastAPI verifies the issuer, audience, expiry, required claims, and
signature using the issuer JWKS endpoint. It then resolves the verified `sub` against
`public.operators`; request-supplied emails, display names, roles, and custom identity
headers are ignored.

The database role is authoritative for authorization. Supported roles are `viewer`,
`operator`, `approver`, and `admin`. Inactive profiles and unknown or invalid roles fail
closed. Shared recommendation tokens may remain temporarily for non-user service
compatibility, but no operator endpoint treats them as individual identity.

## Permission model

- Viewer: recommendation and history reads.
- Operator: Viewer plus capture, acknowledge, simulation preparation, and simulation linking.
- Approver: Operator plus explicit approval decisions and dispatch linking.
- Admin: Approver plus operator profile and role/status administration.

FastAPI enforces permissions. Streamlit hiding or disabling a control is presentation
only and cannot grant access. Protected reads require identity when
`OPERATOR_AUTH_REQUIRED=true`. All operator writes always require a verified identity,
the appropriate role, `RECOMMENDATION_WRITES_ENABLED=true`, and
`OPERATOR_RBAC_STORAGE_ENABLED=true`.

## Persistence and audit

`202607180002_operator_identity_rbac.sql` adds `operators`,
`recommendation_approvals`, and append-only-use `operator_audit_events`. It does not
rewrite recommendation history. Approval records have a single stable recommendation
foreign key and record decision, note, timestamp, and operator UUID. Audit metadata is
allow-listed by application behavior and excludes authorization material and secrets.

The history timeline uses actual audit events to show operator display names. Legacy
events without operator audit rows remain visible with attribution unavailable; an
identity is never inferred from a timestamp or free-form field.

## Bootstrap and deployment

Do not apply the migration automatically. Review and run it in the Supabase SQL Editor,
then insert the first Admin profile using the OIDC provider's verified subject through
an authorized database administration process. Register the Streamlit redirect URI
with the organization's existing OIDC provider and configure Streamlit `[auth]` secrets
using `.streamlit/secrets.example.toml`. Configure matching issuer and audience on
FastAPI. Test Viewer, Operator, Approver, and Admin accounts before enabling
`OPERATOR_AUTH_REQUIRED`, RBAC storage, or recommendation writes in production.

PUBBA Power does not create passwords or invite credentials. Admin profile creation
only maps an identity that already exists in the selected provider.
