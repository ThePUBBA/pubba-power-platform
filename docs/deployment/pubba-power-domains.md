# PUBBA Power domain deployment

This guide prepares the existing services for the intended production domains. It does not authorize or perform registrar, DNS, Render, or other hosting-provider changes.

## Recommended domain architecture

| Domain | Purpose |
| --- | --- |
| `pubbapower.com` | PUBBA Power marketing site |
| `www.pubbapower.com` | Redirect to `https://pubbapower.com` |
| `app.pubbapower.com` | Streamlit PUBBA Power Operations Console |
| `api.pubbapower.com` | FastAPI service, OpenAPI schema, and API documentation |

These are intended production domains until DNS, hosting custom domains, and TLS are configured and verified.

## Application configuration

Configure the dashboard with the preferred variable:

```bash
PUBBA_POWER_API_BASE_URL=https://api.pubbapower.com
```

`PUBBA_POWER_API_BASE_URL` takes precedence over the compatibility variable `ONLY1_API_BASE_URL`. Existing deployments can retain `ONLY1_API_BASE_URL`; do not remove it until every environment has migrated.

Configure FastAPI browser access with a comma-separated allowlist:

```bash
ALLOWED_ORIGINS=https://pubbapower.com,https://www.pubbapower.com,https://app.pubbapower.com,https://your-org.retool.com
```

Keep the actual Retool origin if Retool is still used. Entries are trimmed and empty entries are ignored. Do not use a wildcard with credentialed CORS. CORS is browser policy enforcement, not API authentication.

The API does not currently enable `TrustedHostMiddleware`. This is intentional for this increment: introducing an incomplete host allowlist could reject existing Render hostnames, preview services, health checks, or local development. Host enforcement can be added later after all active provider hostnames are inventoried and tested.

Existing Supabase variables and secrets remain required and unchanged. Domain readiness requires no database migration.

## Render and DNS setup

1. In the active FastAPI Render service, add `api.pubbapower.com` as a custom domain and copy the exact DNS target Render provides.
2. In the active Streamlit hosting service, add `app.pubbapower.com` and copy that provider's exact DNS target.
3. Configure the marketing host for `pubbapower.com` and `www.pubbapower.com`.
4. At the registrar, create the records requested by each active provider. Subdomains commonly use `CNAME`. The apex may require `A`, `ALIAS`, or `ANAME`, depending on registrar and provider support.
5. Do not guess DNS targets. Use only the values displayed by the active hosting provider.
6. Configure a permanent redirect from `www.pubbapower.com` to `https://pubbapower.com`.
7. Wait for provider domain verification and managed TLS certificate issuance before switching links or traffic.
8. Set `PUBBA_POWER_API_BASE_URL` on the Streamlit service and the production `ALLOWED_ORIGINS` value on FastAPI, then redeploy each affected service.

Registrar DNS changes remain manual and must be performed by an authorized domain administrator.

## TLS and HTTPS

All public URLs should use HTTPS. Enable the hosting provider's managed certificate and HTTP-to-HTTPS redirect. Do not consider a domain ready until its certificate is valid for the exact hostname and a browser can connect without a warning.

## Local development

No localhost default is injected by application code. Set either variable explicitly:

```bash
PUBBA_POWER_API_BASE_URL=http://localhost:8000
# Compatibility alternative:
ONLY1_API_BASE_URL=http://localhost:8000
```

If a local browser frontend needs CORS, include its exact origin in `ALLOWED_ORIGINS`. Leaving `ALLOWED_ORIGINS` empty disables CORS middleware; it does not create a wildcard policy.

## Deployment verification

After DNS and TLS are active, verify the API without changing endpoint contracts:

```bash
curl -i https://api.pubbapower.com/health
curl -i https://api.pubbapower.com/portfolio/summary
```

`GET /health` should return the existing health schema and HTTP 200. Its `status` may be `degraded` if Supabase connectivity is unavailable. `GET /portfolio/summary` should return the existing portfolio-summary schema or the existing structured service error if its dependencies are unavailable. Open `https://api.pubbapower.com/docs` and confirm the PUBBA Power API documentation loads.

Then verify:

- `https://pubbapower.com` serves the intended marketing site over HTTPS.
- `https://www.pubbapower.com` redirects to `https://pubbapower.com`.
- `https://app.pubbapower.com` loads the Operations Console and can retrieve its portfolio summary.
- A browser preflight from the app origin returns `Access-Control-Allow-Origin: https://app.pubbapower.com`.
- Existing Render URLs and the Retool origin continue to work during the transition.

## Rollback

1. Restore the dashboard API variable to the previous Render API URL, or remove `PUBBA_POWER_API_BASE_URL` so `ONLY1_API_BASE_URL` resumes control.
2. Restore the previous `ALLOWED_ORIGINS` value and redeploy FastAPI.
3. Remove or disable the new custom domains in the hosting services if they cause routing problems.
4. Restore the prior DNS records using the registrar's recorded values and TTL guidance.
5. Verify the original Render URLs, health endpoint, dashboard, and Retool integration.

Do not remove compatibility environment variables, existing provider domains, or DNS records until the new domains have passed verification and an agreed stabilization period.
