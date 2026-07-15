"""Reusable FastAPI client for the Streamlit presentation layer."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests


DEFAULT_TIMEOUT_SECONDS = 10
REQUIRED_SUMMARY_SECTIONS = {
    "portfolio", "period", "financial", "period_revenue",
    "operations", "fleet", "metadata",
}


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
        configured_url = base_url or os.getenv("ONLY1_API_BASE_URL", "")
        if not configured_url.strip():
            raise DashboardApiError(
                "Backend URL is not configured. Set ONLY1_API_BASE_URL.",
                code="not_configured",
            )
        self.base_url = configured_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session

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

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise DashboardApiError(
                "The backend request timed out. Try refreshing.", code="timeout"
            ) from exc
        except requests.RequestException as exc:
            raise DashboardApiError(
                "The backend is unavailable. Check the service and retry.",
                code="connection_error",
            ) from exc
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
