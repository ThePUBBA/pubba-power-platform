"""Reusable FastAPI client for the Streamlit presentation layer."""

from __future__ import annotations

import os
from time import perf_counter
from datetime import datetime
from typing import Any

import requests


DEFAULT_TIMEOUT_SECONDS = 10
REQUIRED_SUMMARY_SECTIONS = {
    "portfolio", "period", "financial", "period_revenue",
    "operations", "fleet", "metadata",
}
REQUIRED_DASHBOARD_SECTIONS = {
    "portfolio", "period", "kpis", "data_quality", "series", "status", "metadata",
}


def _configured_api_base_url(explicit_url: str | None = None) -> str:
    """Resolve the dashboard API URL while preserving the legacy variable."""
    candidates = (
        explicit_url,
        os.getenv("PUBBA_POWER_API_BASE_URL"),
        os.getenv("ONLY1_API_BASE_URL"),
    )
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()
    return ""


class DashboardApiError(RuntimeError):
    """Safe operator-facing API failure."""

    def __init__(self, message: str, *, code: str = "api_error") -> None:
        super().__init__(message)
        self.code = code


class Only1ApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        session: Any = requests,
    ) -> None:
        configured_url = _configured_api_base_url(base_url)
        if not configured_url:
            raise DashboardApiError(
                "Backend URL is not configured. Set PUBBA_POWER_API_BASE_URL "
                "or ONLY1_API_BASE_URL.",
                code="not_configured",
            )
        self.base_url = configured_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session
        self.last_latency_ms: float | None = None

    def get_portfolio_summary(
        self,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        timezone_name: str | None = None,
    ) -> dict:
        params = {
            key: value
            for key, value in {
                "start_at": start_at.isoformat() if start_at else None,
                "end_at": end_at.isoformat() if end_at else None,
                "timezone": timezone_name.strip() if timezone_name else None,
            }.items()
            if value not in (None, "")
        }
        payload = self._request("get", "/portfolio/summary", params=params)
        if not isinstance(payload, dict) or not REQUIRED_SUMMARY_SECTIONS.issubset(payload):
            raise DashboardApiError(
                "The backend returned an invalid portfolio summary.",
                code="invalid_response",
            )
        for section in REQUIRED_SUMMARY_SECTIONS:
            if not isinstance(payload[section], dict):
                raise DashboardApiError(
                    "The backend returned an invalid portfolio summary.",
                    code="invalid_response",
                )
        return payload

    def run_simulation(self, request_body: dict) -> dict:
        payload = self._request("post", "/simulate", json=request_body)
        if not isinstance(payload, dict) or "estimated_net_margin" not in payload:
            raise DashboardApiError(
                "The backend returned an invalid simulation result.",
                code="invalid_response",
            )
        return payload

    def get_dashboard_summary(
        self, *, timezone_name: str | None = None, include_market: bool = True
    ) -> dict:
        params = {"include_market": str(include_market).lower()}
        if timezone_name and timezone_name.strip():
            params["timezone"] = timezone_name.strip()
        payload = self._request("get", "/dashboard/summary", params=params)
        if not isinstance(payload, dict) or not REQUIRED_DASHBOARD_SECTIONS.issubset(payload):
            raise DashboardApiError(
                "The backend returned invalid executive dashboard data.",
                code="invalid_response",
            )
        if not isinstance(payload["kpis"], dict) or not isinstance(payload["series"], dict):
            raise DashboardApiError(
                "The backend returned invalid executive dashboard data.",
                code="invalid_response",
            )
        return payload

    def get_portfolio_assets(self) -> list[dict]:
        payload = self._request("get", "/portfolio/assets")
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise DashboardApiError(
                "The backend returned invalid asset intelligence data.",
                code="invalid_response",
            )
        return payload

    def get_telemetry_history(self, asset_id: str, *, limit: int = 500) -> list[dict]:
        payload = self._request(
            "get", f"/telemetry/assets/{asset_id}/history", params={"limit": limit}
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise DashboardApiError(
                "The backend returned invalid telemetry history.",
                code="invalid_response",
            )
        return [item for item in payload["records"] if isinstance(item, dict)]

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.Timeout as exc:
            self.last_latency_ms = (perf_counter() - started) * 1000
            raise DashboardApiError(
                "The backend request timed out. Try refreshing.", code="timeout"
            ) from exc
        except requests.RequestException as exc:
            self.last_latency_ms = (perf_counter() - started) * 1000
            raise DashboardApiError(
                "The backend is unavailable. Check the service and retry.",
                code="connection_error",
            ) from exc
        self.last_latency_ms = (perf_counter() - started) * 1000
        if not 200 <= response.status_code < 300:
            code, message = _safe_error(response)
            raise DashboardApiError(message, code=code)
        try:
            return response.json()
        except ValueError as exc:
            raise DashboardApiError(
                "The backend returned an unreadable response.",
                code="invalid_response",
            ) from exc


def _safe_error(response: Any) -> tuple[str, str]:
    fallback = f"Backend request failed with status {response.status_code}."
    try:
        body = response.json()
    except ValueError:
        return "http_error", fallback
    if not isinstance(body, dict):
        return "http_error", fallback
    if isinstance(body.get("error"), dict):
        error = body["error"]
        code = str(error.get("code") or "http_error")
        message = str(error.get("message") or fallback)
    else:
        code = str(body.get("error_code") or "http_error")
        message = str(body.get("message") or fallback)
    if response.status_code >= 500:
        if code == "missing_default_portfolio":
            return code, "The default portfolio is unavailable."
        return code, "The backend encountered a service error. Try refreshing."
    return code, message
