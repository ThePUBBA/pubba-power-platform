from __future__ import annotations

import csv
import hmac
import io
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from arbitrage import ArbitrageAnalysisError, analyze_lmp_arbitrage
from supabase import (
    DuplicateAssetError,
    SupabaseError,
    aggregate_report,
    check_supabase_connectivity,
    create_asset,
    create_operator,
    create_operator_audit_event,
    create_recommendation_capture,
    create_recommendation_approval,
    create_telemetry,
    derive_idempotency_key,
    get_asset_performance,
    get_asset,
    get_operator,
    get_operator_by_subject,
    get_portfolio,
    get_recommendation_approval,
    get_default_portfolio,
    get_latest_telemetry,
    get_latest_telemetry_for_source,
    get_recommendation_history,
    get_simulation_result,
    get_dispatch_event_record,
    list_latest_telemetry_by_source,
    list_assets,
    list_dispatch_events,
    list_portfolio_latest_telemetry,
    list_recommendation_history,
    list_operator_audit_events,
    list_operator_portfolios,
    list_portfolios,
    list_operators,
    list_simulation_results,
    list_telemetry_history,
    find_recent_recommendation_capture,
    persist_simulation,
    update_asset,
    update_operator,
    update_recommendation_links,
    get_operator_portfolio_access,
    transactional_operator_action,
)
from caiso import CaisoOasisError, fetch_lmp_data
from simulation import StorageSimulationError, simulate_storage_profit
from services.portfolio_summary import PortfolioSummaryError, build_portfolio_summary
from services.dashboard_summary import build_dashboard_summary
from services.telemetry import (
    TelemetryValidationError,
    calculate_dispatch_readiness,
    normalize_telemetry,
    source_health,
    telemetry_freshness,
)
from services.telemetry_adapters import GenericJsonTelemetryAdapter
from services.telemetry_ingestion import configured_batch_limit, ingest_batch
from services.telemetry_sources import merge_source_runtime_health, source_runtime_registry
from services.recommendations import rank_portfolio_recommendations
from services.recommendation_history import (
    history_analytics,
    history_detail,
    recommendation_snapshot,
)
from services.operator_auth import (
    OperatorAuthError,
    OperatorPrincipal,
    ROLES,
    operator_auth_required,
    operator_auth_mode,
    principal_from_record,
    verify_oidc_token,
)


SERVICE_NAME = "PUBBA Power API"
SERVICE_DESCRIPTION = (
    "PUBBA Power API for electricity trading, energy storage portfolio "
    "operations, optimization, and grid services."
)
API_VERSION = "1.0.0"
logger = logging.getLogger(__name__)


class PricePoint(BaseModel):
    timestamp: str
    price: float


class PriceWindowResponse(BaseModel):
    start_timestamp: str
    end_timestamp: str
    average_price: float
    prices: list[PricePoint]


class ArbitrageResponse(BaseModel):
    duration_hours: float
    round_trip_efficiency: float
    interval_hours: float
    intervals_per_window: int
    charging_window: PriceWindowResponse
    discharging_window: PriceWindowResponse
    average_charging_price: float
    average_discharging_price: float
    gross_price_spread: float
    efficiency_adjusted_spread: float
    estimated_gross_margin_per_mwh_discharged: float
    assumptions: dict[str, str]


class SimulationRequest(BaseModel):
    location: str = "TH_NP15_GEN-APND"
    market: str = "RTM"
    date: Optional[str] = None
    power_mw: float = Field(gt=0)
    duration_hours: float = Field(default=8, gt=0)
    round_trip_efficiency: float = Field(default=0.80, gt=0, le=1)
    cycles: float = Field(default=1, gt=0)
    storage_fee_per_mwh: float = Field(default=0, ge=0)
    variable_om_per_mwh: float = Field(default=0, ge=0)
    asset_id: Optional[str] = None


class SimulationResponse(BaseModel):
    power_mw: float
    duration_hours: float
    round_trip_efficiency: float
    cycles: float
    storage_fee_per_mwh: float
    variable_om_per_mwh: float
    energy_capacity_mwh: float
    charging_energy_required_mwh: float
    discharged_energy_mwh: float
    charging_cost: float
    discharge_revenue: float
    gross_arbitrage_margin: float
    storage_lease_cost: float
    variable_operating_cost: float
    estimated_net_margin: float
    net_margin_per_mw: float
    net_margin_per_mwh_discharged: float
    arbitrage: ArbitrageResponse
    charging_window: PriceWindowResponse
    discharging_window: PriceWindowResponse
    assumptions: dict[str, str]
    persistence: Optional["PersistenceResponse"] = None


class PersistenceResponse(BaseModel):
    status: str
    simulation_id: Optional[str] = None
    dispatch_id: Optional[str] = None
    error_code: Optional[str] = None
    message: str


class HealthResponse(BaseModel):
    status: str
    service_name: str
    api_version: str
    current_utc_timestamp: datetime
    supabase_connectivity_status: str


class PortfolioIdentityResponse(BaseModel):
    id: str
    code: str
    name: str
    default_market: str
    reporting_timezone: str
    currency_code: str


class SummaryPeriodResponse(BaseModel):
    start_at: Optional[datetime] = None
    end_at: datetime
    timezone: str


class SummaryFinancialResponse(BaseModel):
    gross_revenue: Decimal = Field(description="Gross revenue in portfolio currency")
    charging_cost: Decimal = Field(description="Charging cost in portfolio currency")
    net_profit: Decimal = Field(description="Net profit in portfolio currency")
    total_portfolio_profit: Decimal = Field(description="Lifetime completed-dispatch profit")
    trading_return: Decimal = Field(description="Net profit / charging cost as a decimal ratio")
    weighted_average_spread_per_mwh: Decimal = Field(description="Energy-weighted spread in currency/MWh")


class PeriodRevenueResponse(BaseModel):
    today: Decimal
    week: Decimal
    month: Decimal
    quarter: Decimal
    year: Decimal


class SummaryOperationsResponse(BaseModel):
    total_dispatches: int
    purchased_energy_mwh: Decimal
    sold_energy_mwh: Decimal
    energy_throughput_mwh: Decimal
    last_dispatch_at: Optional[datetime] = None


class SummaryFleetResponse(BaseModel):
    active_assets: int
    power_capacity_mw: Decimal
    energy_capacity_mwh: Decimal


class SummaryMetadataResponse(BaseModel):
    metric_version: str
    data_freshness_at: Optional[datetime] = None
    generated_at: datetime


class PortfolioSummaryResponse(BaseModel):
    portfolio: PortfolioIdentityResponse
    period: SummaryPeriodResponse
    financial: SummaryFinancialResponse
    period_revenue: PeriodRevenueResponse
    operations: SummaryOperationsResponse
    fleet: SummaryFleetResponse
    metadata: SummaryMetadataResponse


class AssetPerformanceResponse(BaseModel):
    asset_id: str
    asset_name: str
    technology: str
    status: str
    power_mw: float
    energy_mwh: float
    location: str
    total_dispatches: int
    total_revenue: float
    total_charging_cost: float
    total_profit: float
    average_profit_per_dispatch: float
    last_dispatch_time: Optional[str] = None


class AssetCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    asset_name: str = Field(min_length=1)
    technology: Optional[str] = None
    power_mw: float = Field(default=0, ge=0)
    energy_mwh: float = Field(default=0, ge=0)
    duration_hours: float = Field(default=0, ge=0)
    location: Optional[str] = None
    lease_cost_monthly: float = Field(default=0, ge=0)
    status: str = "active"


class AssetUpdateRequest(BaseModel):
    asset_name: Optional[str] = Field(default=None, min_length=1)
    technology: Optional[str] = None
    power_mw: Optional[float] = Field(default=None, ge=0)
    energy_mwh: Optional[float] = Field(default=None, ge=0)
    duration_hours: Optional[float] = Field(default=None, ge=0)
    location: Optional[str] = None
    lease_cost_monthly: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = None


class TelemetryCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    recorded_at: datetime
    state_of_charge_pct: Optional[float] = None
    current_power_mw: Optional[float] = None
    available_charge_power_mw: Optional[float] = None
    available_discharge_power_mw: Optional[float] = None
    available_energy_mwh: Optional[float] = None
    temperature_c: Optional[float] = None
    operational_status: Optional[str] = None
    availability_status: Optional[str] = None
    telemetry_source: str = Field(min_length=1)
    is_simulated: bool


class TelemetryBatchRequest(BaseModel):
    observations: list[dict]


class RecommendationLinkRequest(BaseModel):
    record_id: str = Field(min_length=1)


class RecommendationAcknowledgementRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


class RecommendationApprovalRequest(BaseModel):
    approval_status: str = Field(pattern="^(approved|rejected)$")
    note: Optional[str] = Field(default=None, max_length=1000)


class OperatorCreateRequest(BaseModel):
    auth_subject: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=255)
    role: str
    status: str = "active"


class OperatorUpdateRequest(BaseModel):
    role: Optional[str] = None
    status: Optional[str] = None


class OperatorPortfolioAccessRequest(BaseModel):
    portfolio_id: str = Field(min_length=1)
    role_override: Optional[str] = None
    active: bool = True


class ReportPeriodResponse(BaseModel):
    period_start: str
    period_end: str
    total_dispatches: int
    total_energy_mwh: float
    charging_cost: float
    discharge_revenue: float
    storage_cost: float
    net_profit: float


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        *,
        field: str | None = None,
        upstream_service: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.field = field
        self.upstream_service = upstream_service


def _error_payload(
    error_code: str,
    message: str,
    *,
    field: str | None = None,
    upstream_service: str | None = None,
) -> dict[str, str]:
    payload = {"error_code": error_code, "message": message}
    if field:
        payload["field"] = field
    if upstream_service:
        payload["upstream_service"] = upstream_service
    return payload


def _allowed_origins() -> list[str]:
    return [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]


def _run_simulation(request: SimulationRequest) -> dict:
    try:
        df = fetch_lmp_data(
            location=request.location,
            market=request.market,
            date=request.date,
        )
        return simulate_storage_profit(
            df,
            power_mw=request.power_mw,
            duration_hours=request.duration_hours,
            round_trip_efficiency=request.round_trip_efficiency,
            cycles=request.cycles,
            storage_fee_per_mwh=request.storage_fee_per_mwh,
            variable_om_per_mwh=request.variable_om_per_mwh,
        )
    except CaisoOasisError as exc:
        raise ApiError(
            502,
            "upstream_service_error",
            str(exc),
            upstream_service="CAISO OASIS",
        ) from exc
    except (ArbitrageAnalysisError, StorageSimulationError, ValueError) as exc:
        field = str(exc).split(" ", 1)[0] if str(exc) else None
        raise ApiError(400, "simulation_error", str(exc), field=field) from exc


def _persist_completed_simulation(
    request: SimulationRequest,
    result: dict,
    idempotency_key: str,
) -> dict:
    try:
        return persist_simulation(
            request.model_dump(),
            result,
            idempotency_key,
        )
    except SupabaseError as exc:
        logger.exception(
            "Supabase ledger persistence failed",
            extra={
                "supabase_operation": exc.operation or "persist_simulation",
                "error_code": exc.error_code,
                "simulation_id": exc.simulation_id,
            },
        )
        return {
            "status": "partial" if exc.simulation_id else "failed",
            "simulation_id": exc.simulation_id,
            "dispatch_id": None,
            "error_code": exc.error_code,
            "message": str(exc),
        }


def _raise_supabase_api_error(exc: SupabaseError) -> None:
    raise ApiError(
        exc.status_code,
        exc.error_code,
        str(exc),
        upstream_service="Supabase",
    ) from exc


def _raise_telemetry_api_error(exc: SupabaseError) -> None:
    if exc.error_code == "missing_asset":
        _raise_supabase_api_error(exc)
    raise ApiError(
        503,
        "telemetry_storage_unavailable",
        "Telemetry storage is unavailable",
        upstream_service="Supabase",
    ) from exc


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and start_date > end_date:
        raise ApiError(
            400,
            "invalid_date_range",
            "start_date must be on or before end_date",
            field="start_date",
        )


def _telemetry_response(record: dict | None) -> dict:
    if not record:
        return {
            "telemetry_status": "unavailable",
            "record": None,
            "freshness": {"status": "unavailable", "age_seconds": None, "stale": True},
            "readiness": calculate_dispatch_readiness(None).as_dict(),
        }
    try:
        normalized = normalize_telemetry(record)
    except TelemetryValidationError:
        return {
            "telemetry_status": "invalid",
            "record": None,
            "freshness": {"status": "unavailable", "age_seconds": None, "stale": True},
            "readiness": calculate_dispatch_readiness(None).as_dict(),
        }
    return {
        "telemetry_status": "available",
        "record": {**record, **normalized},
        "freshness": telemetry_freshness(normalized["recorded_at"]),
        "readiness": calculate_dispatch_readiness(normalized).as_dict(),
    }


def _telemetry_writes_allowed(write_key: str | None) -> bool:
    if os.getenv("TELEMETRY_WRITES_ENABLED", "").strip().lower() not in {
        "1", "true", "yes",
    }:
        return False
    expected = os.getenv("TELEMETRY_WRITE_TOKEN", "")
    return bool(expected and write_key) and hmac.compare_digest(write_key, expected)


def _operator_rbac_storage_enabled() -> bool:
    return os.getenv("OPERATOR_RBAC_STORAGE_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title=SERVICE_NAME,
        description=SERVICE_DESCRIPTION,
        version=API_VERSION,
    )
    origins = _allowed_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["*"],
        )

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(
                exc.error_code,
                exc.message,
                field=exc.field,
                upstream_service=exc.upstream_service,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        error = exc.errors()[0]
        field = ".".join(
            str(part)
            for part in error["loc"]
            if part not in {"body", "query", "path", "header"}
        )
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "validation_error",
                error["msg"],
                field=field or None,
            ),
        )

    def resolve_operator(authorization: str | None) -> OperatorPrincipal:
        if not authorization or not authorization.startswith("Bearer "):
            logger.info(
                "Operator authentication required",
                extra={"security_event": "authentication_missing"},
            )
            raise ApiError(401, "authentication_required", "Operator authentication is required")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            logger.info(
                "Operator authentication required",
                extra={"security_event": "authentication_missing"},
            )
            raise ApiError(401, "authentication_required", "Operator authentication is required")
        try:
            identity = verify_oidc_token(token)
            record = get_operator_by_subject(identity.subject)
        except OperatorAuthError as exc:
            logger.warning(
                "Operator authentication rejected",
                extra={"security_event": "authentication_invalid"},
            )
            raise ApiError(401, "invalid_operator_credential", str(exc)) from exc
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        if not record:
            logger.warning(
                "Operator is not provisioned",
                extra={"security_event": "operator_unknown"},
            )
            raise ApiError(403, "operator_not_provisioned", "Operator access is not provisioned")
        try:
            principal = principal_from_record(record)
        except OperatorAuthError as exc:
            logger.warning(
                "Operator profile rejected",
                extra={"security_event": "operator_role_invalid"},
            )
            raise ApiError(403, "operator_access_denied", "Operator access is not authorized") from exc
        if principal.status != "active":
            logger.warning(
                "Inactive operator rejected",
                extra={"security_event": "operator_inactive"},
            )
            raise ApiError(403, "operator_inactive", "Operator access is inactive")
        return principal

    def authenticated_operator(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> OperatorPrincipal:
        return resolve_operator(authorization)

    def optional_read_operator(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> OperatorPrincipal | None:
        mode = operator_auth_mode()
        if mode == "off":
            return None
        if mode == "enforce":
            return resolve_operator(authorization)
        if not authorization:
            logger.info("Operator authentication shadow evaluation", extra={"outcome": "missing"})
            return None
        try:
            return resolve_operator(authorization)
        except ApiError as exc:
            logger.warning(
                "Operator authentication shadow evaluation",
                extra={"outcome": "would_deny", "error_code": exc.error_code},
            )
            return None

    def portfolio_rbac_enabled() -> bool:
        return os.getenv("OPERATOR_PORTFOLIO_RBAC_ENABLED", "false").strip().lower() in {
            "1", "true", "yes", "on",
        }

    def transactional_audit_enabled() -> bool:
        return os.getenv("OPERATOR_TRANSACTIONAL_AUDIT_ENABLED", "false").strip().lower() in {
            "1", "true", "yes", "on",
        }

    def require_portfolio_permission(
        principal: OperatorPrincipal, portfolio_id: str, permission: str,
    ) -> str:
        """Resolve effective portfolio role server-side; never trust client claims."""
        if not portfolio_rbac_enabled() or principal.role == "admin":
            if not principal.can(permission):
                raise ApiError(403, "operator_forbidden", "Operator is not authorized for this action")
            return principal.role
        try:
            assignment = get_operator_portfolio_access(principal.operator_id, portfolio_id)
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        if not assignment:
            logger.warning(
                "Cross-portfolio operator access rejected",
                extra={
                    "security_event": "portfolio_access_denied",
                    "operator_id": principal.operator_id,
                    "portfolio_id": portfolio_id,
                },
            )
            raise ApiError(404, "portfolio_not_found", "Portfolio was not found")
        role = str(assignment.get("role_override") or principal.role)
        effective = OperatorPrincipal(
            operator_id=principal.operator_id, auth_subject=principal.auth_subject,
            email=principal.email, display_name=principal.display_name,
            role=role, status=principal.status,
        )
        if not effective.can(permission):
            logger.warning(
                "Portfolio permission rejected",
                extra={
                    "security_event": "portfolio_permission_denied",
                    "operator_id": principal.operator_id,
                    "portfolio_id": portfolio_id,
                    "permission": permission,
                },
            )
            raise ApiError(403, "operator_forbidden", "Operator is not authorized for this action")
        return role

    def resolve_read_portfolio(
        principal: OperatorPrincipal | None, requested_portfolio_id: str | None,
    ) -> str | None:
        if not principal or not portfolio_rbac_enabled() or principal.role == "admin":
            return requested_portfolio_id
        try:
            assignments = list_operator_portfolios(principal.operator_id)
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        allowed = {str(item.get("portfolio_id")) for item in assignments if item.get("active", True)}
        if requested_portfolio_id:
            if requested_portfolio_id not in allowed:
                logger.warning(
                    "Cross-portfolio read rejected",
                    extra={
                        "security_event": "portfolio_access_denied",
                        "operator_id": principal.operator_id,
                        "portfolio_id": requested_portfolio_id,
                    },
                )
                raise ApiError(404, "portfolio_not_found", "Portfolio was not found")
            return requested_portfolio_id
        if len(allowed) == 1:
            return next(iter(allowed))
        if not allowed:
            raise ApiError(404, "portfolio_not_found", "Portfolio was not found")
        raise ApiError(400, "portfolio_required", "An authorized portfolio must be selected")

    def require_permission(permission: str):
        def dependency(
            principal: OperatorPrincipal = Depends(authenticated_operator),
        ) -> OperatorPrincipal:
            if not principal.can(permission):
                if _operator_rbac_storage_enabled():
                    try:
                        audit_action(
                            principal, "authorization_denied", "permission", permission,
                            outcome="rejected", metadata={},
                        )
                    except SupabaseError:
                        logger.warning("Operator authorization denial audit could not be persisted")
                raise ApiError(403, "operator_forbidden", "Operator is not authorized for this action")
            return principal
        return dependency

    def require_operator_writes() -> None:
        if os.getenv("RECOMMENDATION_WRITES_ENABLED", "").strip().lower() not in {"1", "true", "yes"}:
            raise ApiError(403, "recommendation_writes_disabled", "Recommendation audit writes are disabled")
        if not _operator_rbac_storage_enabled():
            raise ApiError(503, "operator_audit_storage_disabled", "Operator audit storage is not enabled")

    def audit_action(
        principal: OperatorPrincipal, action: str, entity_type: str,
        entity_id: str, *, outcome: str = "succeeded", metadata: dict | None = None,
    ) -> dict:
        safe_metadata = {
            key: value for key, value in (metadata or {}).items()
            if key.lower() not in {"token", "authorization", "credential", "secret"}
        }
        return create_operator_audit_event({
            "operator_id": principal.operator_id, "action": action,
            "entity_type": entity_type, "entity_id": entity_id,
            "outcome": outcome, "metadata": safe_metadata,
        })

    def audit_rejected(
        principal: OperatorPrincipal, action: str, entity_type: str,
        entity_id: str, metadata: dict | None = None,
    ) -> None:
        try:
            audit_action(
                principal, action, entity_type, entity_id,
                outcome="rejected", metadata=metadata,
            )
        except SupabaseError:
            logger.warning("Rejected operator action audit could not be persisted")

    def atomic_recommendation_action(
        principal: OperatorPrincipal, recommendation_id: str,
        action: str, payload: dict | None = None,
    ) -> dict:
        return transactional_operator_action(
            "pubba_audited_recommendation_action",
            {
                "p_operator_id": principal.operator_id,
                "p_recommendation_id": recommendation_id,
                "p_action": action,
                "p_payload": payload or {},
            },
        )

    @app.get("/")
    def root():
        return {"message": "PUBBA Power API is running"}

    @app.get("/health", response_model=HealthResponse)
    def health():
        supabase_status = check_supabase_connectivity()
        return {
            "status": "ok" if supabase_status == "connected" else "degraded",
            "service_name": SERVICE_NAME,
            "api_version": API_VERSION,
            "current_utc_timestamp": datetime.now(timezone.utc),
            "supabase_connectivity_status": supabase_status,
        }

    @app.get(
        "/portfolio/summary",
        response_model=PortfolioSummaryResponse,
        summary="Get the executive portfolio summary",
        description=(
            "Returns portfolio-scoped financial, operational, and fleet KPIs. "
            "Financial and energy metrics include completed dispatches; legacy "
            "simulation-derived ledger rows are normalized as completed. Reporting "
            "periods use the portfolio timezone and metric version 1.0. Monetary "
            "values use the portfolio currency, spread uses currency/MWh, capacity "
            "uses MW, and energy uses MWh."
        ),
        responses={400: {"description": "Invalid date range or timezone"}, 503: {"description": "Default portfolio unavailable"}},
    )
    def portfolio_summary(
        portfolio_id: Optional[str] = None,
        start_at: Optional[datetime] = Query(
            default=None, description="Inclusive summary start timestamp with offset"
        ),
        end_at: Optional[datetime] = Query(
            default=None, description="Inclusive summary end timestamp with offset"
        ),
        timezone_name: Optional[str] = Query(
            default=None,
            alias="timezone",
            description="Validated IANA reporting timezone override",
        ),
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        try:
            portfolio_id = resolve_read_portfolio(principal, portfolio_id)
            options = {
                "start_at": start_at, "end_at": end_at,
                "timezone_name": timezone_name,
            }
            if portfolio_id:
                portfolio = get_portfolio(portfolio_id)
                if not portfolio:
                    raise ApiError(404, "portfolio_not_found", "Portfolio was not found")
                options["portfolio_resolver"] = lambda: portfolio
            return build_portfolio_summary(**options)
        except PortfolioSummaryError as exc:
            raise ApiError(400, exc.code, str(exc), field=exc.field) from exc
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/portfolio/assets", response_model=list[AssetPerformanceResponse])
    def portfolio_assets(
        portfolio_id: Optional[str] = None,
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        try:
            portfolio_id = resolve_read_portfolio(principal, portfolio_id)
            return (
                get_asset_performance(portfolio_id=portfolio_id)
                if portfolio_id else get_asset_performance()
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get(
        "/dashboard/summary",
        summary="Get live executive dashboard data",
        description=(
            "Aggregates portfolio KPIs, completed dispatch time series, service "
            "status, and optional live CAISO RTM pricing. Values derived from "
            "simulation ledger rows are explicitly labeled calculated estimates."
        ),
    )
    def dashboard_summary(
        portfolio_id: Optional[str] = None,
        timezone_name: Optional[str] = Query(default=None, alias="timezone"),
        include_market: bool = Query(default=True),
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        try:
            portfolio_id = resolve_read_portfolio(principal, portfolio_id)
            options = {"timezone_name": timezone_name, "include_market": include_market}
            portfolio = None
            if portfolio_id:
                portfolio = get_portfolio(portfolio_id)
                if not portfolio:
                    raise ApiError(404, "portfolio_not_found", "Portfolio was not found")
                options.update({
                    "portfolio_resolver": lambda: portfolio,
                    "telemetry_loader": lambda: list_portfolio_latest_telemetry(str(portfolio["id"])),
                })
            dashboard = build_dashboard_summary(**options)
            try:
                dashboard["recommendations"] = current_recommendations(
                    dashboard=dashboard,
                    portfolio_id=str(portfolio["id"]) if portfolio else None,
                )
            except ApiError:
                dashboard["recommendations"] = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "advisory_only": True,
                    "autonomous_dispatch": False,
                    "market_status": "unavailable",
                    "highest_opportunity_score": 0,
                    "best_candidate_asset_id": None,
                    "recommendations": [],
                }
            return dashboard
        except PortfolioSummaryError as exc:
            raise ApiError(400, exc.code, str(exc), field=exc.field) from exc
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/assets")
    def assets(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ):
        try:
            return list_assets(limit=limit, offset=offset)
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/assets/{asset_id}")
    def asset(asset_id: str):
        try:
            record = get_asset(asset_id)
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        if not record:
            raise ApiError(404, "missing_asset", f"Asset not found: {asset_id}")
        return record

    @app.post("/assets", status_code=201)
    def add_asset(request: AssetCreateRequest):
        try:
            return create_asset(request.model_dump())
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.patch("/assets/{asset_id}")
    def patch_asset(asset_id: str, request: AssetUpdateRequest):
        fields = request.model_dump(exclude_unset=True)
        if not fields:
            raise ApiError(
                400,
                "invalid_request",
                "At least one asset field must be provided",
            )
        try:
            return update_asset(asset_id, fields)
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/telemetry/assets/{asset_id}/latest")
    def latest_asset_telemetry(asset_id: str):
        try:
            return {"asset_id": asset_id, **_telemetry_response(get_latest_telemetry(asset_id))}
        except SupabaseError as exc:
            _raise_telemetry_api_error(exc)

    @app.get("/telemetry/assets/{asset_id}/history")
    def asset_telemetry_history(
        asset_id: str,
        start_time: Optional[datetime] = Query(default=None),
        end_time: Optional[datetime] = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
    ):
        for field, value in (("start_time", start_time), ("end_time", end_time)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ApiError(400, "invalid_timestamp", f"{field} must include a timezone offset", field=field)
        if start_time and end_time and start_time > end_time:
            raise ApiError(400, "invalid_date_range", "start_time must be on or before end_time", field="start_time")
        try:
            records = list_telemetry_history(
                asset_id, start_at=start_time, end_at=end_time, limit=limit
            )
        except SupabaseError as exc:
            _raise_telemetry_api_error(exc)
        valid = []
        invalid_records = 0
        for record in records:
            response = _telemetry_response(record)
            if response["record"] is None:
                invalid_records += 1
                continue
            valid.append(response["record"])
        return {
            "asset_id": asset_id,
            "records": valid,
            "invalid_records_skipped": invalid_records,
        }

    @app.get("/telemetry/portfolio/latest")
    def portfolio_latest_telemetry():
        try:
            records = list_portfolio_latest_telemetry()
        except SupabaseError as exc:
            _raise_telemetry_api_error(exc)
        return {
            "telemetry_status": "available" if records else "unavailable",
            "assets": [
                {"asset_id": str(record.get("asset_id") or ""), **_telemetry_response(record)}
                for record in records
            ],
        }

    @app.get("/telemetry/sources/health")
    def telemetry_sources_health():
        configured = [
            item.strip()
            for item in os.getenv("TELEMETRY_CONFIGURED_SOURCES", "").split(",")
            if item.strip()
        ]
        try:
            records = list_latest_telemetry_by_source()
        except SupabaseError as exc:
            _raise_telemetry_api_error(exc)
        health = source_health(records, configured_sources=configured)
        return {
            "sources": merge_source_runtime_health(
                health, source_runtime_registry.snapshot()
            )
        }

    def current_recommendations(
        *, dashboard: dict | None = None, portfolio_id: str | None = None,
    ) -> dict:
        try:
            dashboard = dashboard or build_dashboard_summary(include_market=True)
            assets = (
                get_asset_performance(portfolio_id=portfolio_id)
                if portfolio_id else get_asset_performance()
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        metadata = dashboard.get("metadata") or {}
        market = {
            "status": (dashboard.get("status") or {}).get("market_data"),
            "location": metadata.get("market_location"),
            "market": metadata.get("market_type"),
            "current_price_per_mwh": (dashboard.get("kpis") or {}).get(
                "current_market_price_per_mwh"
            ),
            "price_points": (dashboard.get("series") or {}).get("market_prices") or [],
            "updated_at": metadata.get("market_updated_at"),
        }
        telemetry = (dashboard.get("telemetry") or {}).get("assets") or []
        return rank_portfolio_recommendations(
            assets=assets, market=market, telemetry_records=telemetry
        )

    @app.get("/recommendations/portfolio")
    def portfolio_recommendations(
        portfolio_id: Optional[str] = None,
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        if principal:
            portfolio_id = resolve_read_portfolio(principal, portfolio_id)
            if portfolio_id:
                require_portfolio_permission(principal, portfolio_id, "recommendations:read")
        return current_recommendations(portfolio_id=portfolio_id)

    @app.get("/recommendations/assets/{asset_id}")
    def asset_recommendation(
        asset_id: str,
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        result = current_recommendations()
        recommendation = next((
            item for item in result["recommendations"] if item["asset_id"] == asset_id
        ), None)
        if recommendation is None:
            raise ApiError(404, "asset_not_found", "Asset was not found", field="asset_id")
        return recommendation

    def load_history_detail(recommendation_id: str) -> dict:
        try:
            record = get_recommendation_history(recommendation_id)
            if not record:
                raise ApiError(
                    404, "recommendation_not_found",
                    "Recommendation history record was not found",
                )
            simulation = (
                get_simulation_result(str(record["simulation_id"]))
                if record.get("simulation_id") else None
            )
            dispatch = (
                get_dispatch_event_record(str(record["dispatch_id"]))
                if record.get("dispatch_id") else None
            )
            approval = None
            audit_events = []
            if _operator_rbac_storage_enabled():
                approval = get_recommendation_approval(recommendation_id)
                if approval:
                    approver = get_operator(str(approval["approved_by_operator_id"]))
                    approval = {**approval, "operator": approver}
                raw_events = list_operator_audit_events(
                    entity_type="recommendation", entity_id=recommendation_id
                )
                operator_cache: dict[str, dict | None] = {}
                for event in raw_events:
                    operator_id = str(event.get("operator_id") or "")
                    if operator_id not in operator_cache:
                        operator_cache[operator_id] = get_operator(operator_id)
                    audit_events.append({**event, "operator": operator_cache[operator_id]})
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return history_detail(
            record, simulation=simulation, dispatch=dispatch,
            approval=approval, audit_events=audit_events,
        )

    @app.post("/recommendations/{asset_id}/capture", status_code=201)
    def capture_recommendation(
        asset_id: str, response: Response, portfolio_id: Optional[str] = None,
        principal: OperatorPrincipal = Depends(
            require_permission("recommendations:capture")
        ),
    ):
        require_operator_writes()
        portfolio_id = resolve_read_portfolio(principal, portfolio_id)
        current = current_recommendations(portfolio_id=portfolio_id)
        item = next((
            value for value in current["recommendations"]
            if value["asset_id"] == asset_id
        ), None)
        if item is None:
            raise ApiError(404, "asset_not_found", "Asset was not found", field="asset_id")
        if item.get("market_status") != "fresh" or not item.get("estimated_economics"):
            raise ApiError(
                409, "recommendation_not_capturable",
                "A fresh market recommendation is not currently available",
            )
        try:
            portfolio = get_portfolio(portfolio_id) if portfolio_id else get_default_portfolio()
            if not portfolio:
                raise ApiError(404, "portfolio_not_found", "Portfolio was not found")
            require_portfolio_permission(
                principal, str(portfolio["id"]), "recommendations:capture"
            )
            asset_record = get_asset(asset_id)
            if not asset_record:
                raise ApiError(404, "asset_not_found", "Asset was not found", field="asset_id")
            snapshot = recommendation_snapshot(
                item, portfolio_id=portfolio["id"], asset=asset_record
            )
            try:
                duplicate_seconds = int(os.getenv("RECOMMENDATION_CAPTURE_DEDUP_SECONDS", "300"))
            except ValueError as exc:
                raise ApiError(
                    500, "invalid_recommendation_configuration",
                    "Recommendation capture configuration is invalid",
                ) from exc
            if duplicate_seconds < 0:
                raise ApiError(
                    500, "invalid_recommendation_configuration",
                    "Recommendation capture configuration is invalid",
                )
            existing = find_recent_recommendation_capture(
                asset_id=asset_id, snapshot_hash=snapshot["snapshot_hash"],
                since=datetime.now(timezone.utc) - timedelta(seconds=duplicate_seconds),
            )
            if existing:
                audit_action(
                    principal, "recommendation_capture_duplicate", "recommendation",
                    str(existing["id"]), outcome="rejected",
                    metadata={"asset_id": asset_id},
                )
                response.status_code = 200
                return {"capture_status": "duplicate", "recommendation": existing}
            if transactional_audit_enabled():
                created = transactional_operator_action(
                    "pubba_audited_recommendation_capture",
                    {"p_operator_id": principal.operator_id, "p_snapshot": snapshot},
                )
            else:
                created = create_recommendation_capture(snapshot)
                audit_action(
                    principal, "recommendation_captured", "recommendation",
                    str(created["id"]), metadata={"asset_id": asset_id},
                )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return {"capture_status": "captured", "recommendation": created}

    @app.get("/recommendations/history")
    def recommendation_history(
        portfolio_id: Optional[str] = None, asset_id: Optional[str] = None,
        direction: Optional[str] = None,
        start_time: Optional[datetime] = Query(default=None),
        end_time: Optional[datetime] = Query(default=None),
        minimum_score: Optional[int] = Query(default=None, ge=0, le=100),
        linked_simulation: Optional[bool] = None,
        linked_dispatch: Optional[bool] = None,
        outcome_status: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        portfolio_id = resolve_read_portfolio(principal, portfolio_id)
        if direction and direction not in {"charge", "discharge", "hold", "insufficient_data"}:
            raise ApiError(400, "invalid_direction", "Unknown recommendation direction", field="direction")
        for field, value in (("start_time", start_time), ("end_time", end_time)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ApiError(400, "invalid_timestamp", f"{field} must include a timezone offset", field=field)
        if start_time and end_time and start_time > end_time:
            raise ApiError(400, "invalid_date_range", "start_time must be on or before end_time")
        outcome_filters = {
            "no_action_taken": (False, False),
            "simulation_only": (True, False),
            "dispatch_linked": (None, True),
        }
        if outcome_status:
            if outcome_status not in outcome_filters:
                raise ApiError(400, "invalid_outcome_status", "Unknown outcome status", field="outcome_status")
            outcome_simulation, outcome_dispatch = outcome_filters[outcome_status]
            if linked_simulation is not None and outcome_simulation is not None and linked_simulation != outcome_simulation:
                raise ApiError(400, "conflicting_filters", "Outcome status conflicts with simulation filter")
            if linked_dispatch is not None and linked_dispatch != outcome_dispatch:
                raise ApiError(400, "conflicting_filters", "Outcome status conflicts with dispatch filter")
            linked_simulation = outcome_simulation if outcome_simulation is not None else linked_simulation
            linked_dispatch = outcome_dispatch
        try:
            records = list_recommendation_history(
                portfolio_id=portfolio_id, asset_id=asset_id, direction=direction,
                start_at=start_time, end_at=end_time, minimum_score=minimum_score,
                linked_simulation=linked_simulation, linked_dispatch=linked_dispatch,
                limit=limit, offset=offset,
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return {"records": records, "count": len(records), "limit": limit, "offset": offset}

    @app.get("/recommendations/history/analytics")
    def recommendation_history_portfolio_analytics(
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        try:
            portfolio = get_default_portfolio()
            records = list_recommendation_history(
                portfolio_id=portfolio["id"], limit=1000
            )
            enriched = []
            for record in records:
                dispatch = (
                    get_dispatch_event_record(str(record["dispatch_id"]))
                    if record.get("dispatch_id") else None
                )
                enriched.append(history_detail(record, dispatch=dispatch))
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return history_analytics(enriched)

    @app.get("/recommendations/history/{recommendation_id}")
    def recommendation_history_detail(
        recommendation_id: str,
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        detail = load_history_detail(recommendation_id)
        if principal:
            require_portfolio_permission(
                principal, str(detail["portfolio_id"]), "recommendations:read"
            )
        return detail

    @app.post("/recommendations/history/{recommendation_id}/acknowledge")
    def acknowledge_recommendation(
        recommendation_id: str, request: RecommendationAcknowledgementRequest,
        principal: OperatorPrincipal = Depends(
            require_permission("recommendations:acknowledge")
        ),
    ):
        require_operator_writes()
        detail = load_history_detail(recommendation_id)
        require_portfolio_permission(
            principal, str(detail["portfolio_id"]), "recommendations:acknowledge"
        )
        if detail.get("acknowledged_at"):
            audit_rejected(
                principal, "recommendation_acknowledgement_duplicate",
                "recommendation", recommendation_id,
            )
            raise ApiError(409, "recommendation_already_acknowledged", "Recommendation was already acknowledged")
        try:
            if transactional_audit_enabled():
                atomic_recommendation_action(
                    principal, recommendation_id, "acknowledge", {"note": request.note}
                )
            else:
                updated = update_recommendation_links(recommendation_id, {
                    "acknowledged_at": datetime.now(timezone.utc).isoformat(),
                    "acknowledgement_note": request.note,
                    "acknowledgement_attribution": f"operator:{principal.operator_id}",
                })
                audit_action(
                    principal, "recommendation_acknowledged", "recommendation",
                    recommendation_id, metadata={"note_supplied": bool(request.note)},
                )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return load_history_detail(recommendation_id)

    @app.post("/recommendations/history/{recommendation_id}/link-simulation")
    def link_recommendation_simulation(
        recommendation_id: str, request: RecommendationLinkRequest,
        principal: OperatorPrincipal = Depends(
            require_permission("recommendations:link_simulation")
        ),
    ):
        require_operator_writes()
        detail = load_history_detail(recommendation_id)
        require_portfolio_permission(
            principal, str(detail["portfolio_id"]), "recommendations:link_simulation"
        )
        if detail.get("simulation_id"):
            if str(detail["simulation_id"]) == request.record_id:
                return detail
            audit_rejected(principal, "simulation_link_rejected", "recommendation", recommendation_id)
            raise ApiError(409, "simulation_already_linked", "Recommendation already has a simulation link")
        try:
            simulation = get_simulation_result(request.record_id)
            if not simulation:
                audit_rejected(principal, "simulation_link_rejected", "recommendation", recommendation_id)
                raise ApiError(404, "simulation_not_found", "Simulation was not found")
            if simulation.get("portfolio_id") != detail.get("portfolio_id") or (
                simulation.get("asset_id") and simulation.get("asset_id") != detail.get("asset_id")
            ):
                audit_rejected(principal, "simulation_link_rejected", "recommendation", recommendation_id)
                raise ApiError(409, "simulation_link_mismatch", "Simulation does not match recommendation ownership")
            if transactional_audit_enabled():
                atomic_recommendation_action(
                    principal, recommendation_id, "link_simulation",
                    {"record_id": str(simulation["id"])},
                )
            else:
                updated = update_recommendation_links(recommendation_id, {
                    "simulation_id": simulation["id"],
                    "simulation_linked_at": datetime.now(timezone.utc).isoformat(),
                })
                audit_action(
                    principal, "simulation_linked", "recommendation", recommendation_id,
                    metadata={"simulation_id": str(simulation["id"])},
                )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return load_history_detail(recommendation_id)

    @app.post("/recommendations/history/{recommendation_id}/review-simulation")
    def review_recommendation_simulation(
        recommendation_id: str, request: RecommendationAcknowledgementRequest,
        principal: OperatorPrincipal = Depends(
            require_permission("recommendations:link_simulation")
        ),
    ):
        require_operator_writes()
        detail = load_history_detail(recommendation_id)
        require_portfolio_permission(
            principal, str(detail["portfolio_id"]), "recommendations:link_simulation"
        )
        if not detail.get("simulation_id"):
            audit_rejected(principal, "simulation_review_rejected", "recommendation", recommendation_id)
            raise ApiError(409, "simulation_not_linked", "A simulation must be linked before review")
        if any(event.get("action") == "simulation_reviewed" for event in detail.get("audit_events") or []):
            audit_rejected(principal, "simulation_review_duplicate", "recommendation", recommendation_id)
            raise ApiError(409, "simulation_already_reviewed", "The linked simulation was already reviewed")
        try:
            if transactional_audit_enabled():
                atomic_recommendation_action(
                    principal, recommendation_id, "review_simulation",
                    {"simulation_id": str(detail["simulation_id"]), "note": request.note},
                )
            else:
                audit_action(
                    principal, "simulation_reviewed", "recommendation", recommendation_id,
                    metadata={"simulation_id": str(detail["simulation_id"]), "note_supplied": bool(request.note)},
                )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return load_history_detail(recommendation_id)

    @app.post("/recommendations/history/{recommendation_id}/link-dispatch")
    def link_recommendation_dispatch(
        recommendation_id: str, request: RecommendationLinkRequest,
        principal: OperatorPrincipal = Depends(
            require_permission("recommendations:link_dispatch")
        ),
    ):
        require_operator_writes()
        detail = load_history_detail(recommendation_id)
        require_portfolio_permission(
            principal, str(detail["portfolio_id"]), "recommendations:link_dispatch"
        )
        if detail.get("dispatch_id"):
            if str(detail["dispatch_id"]) == request.record_id:
                return detail
            audit_rejected(principal, "dispatch_link_rejected", "recommendation", recommendation_id)
            raise ApiError(409, "dispatch_already_linked", "Recommendation already has a dispatch link")
        try:
            dispatch = get_dispatch_event_record(request.record_id)
            if not dispatch:
                audit_rejected(principal, "dispatch_link_rejected", "recommendation", recommendation_id)
                raise ApiError(404, "dispatch_not_found", "Dispatch was not found")
            if (
                dispatch.get("portfolio_id") != detail.get("portfolio_id")
                or dispatch.get("asset_id") != detail.get("asset_id")
            ):
                audit_rejected(principal, "dispatch_link_rejected", "recommendation", recommendation_id)
                raise ApiError(409, "dispatch_link_mismatch", "Dispatch does not match recommendation ownership")
            if transactional_audit_enabled():
                atomic_recommendation_action(
                    principal, recommendation_id, "link_dispatch",
                    {"record_id": str(dispatch["id"])},
                )
            else:
                updated = update_recommendation_links(recommendation_id, {
                    "dispatch_id": dispatch["id"],
                    "dispatch_linked_at": datetime.now(timezone.utc).isoformat(),
                })
                audit_action(
                    principal, "dispatch_linked", "recommendation", recommendation_id,
                    metadata={"dispatch_id": str(dispatch["id"])},
                )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return load_history_detail(recommendation_id)

    @app.post("/recommendations/history/{recommendation_id}/approval", status_code=201)
    def decide_recommendation_approval(
        recommendation_id: str, request: RecommendationApprovalRequest,
        principal: OperatorPrincipal = Depends(
            require_permission("recommendations:approve")
        ),
    ):
        require_operator_writes()
        detail = load_history_detail(recommendation_id)
        require_portfolio_permission(
            principal, str(detail["portfolio_id"]), "recommendations:approve"
        )
        if detail.get("approval"):
            audit_rejected(principal, "approval_duplicate_rejected", "recommendation", recommendation_id)
            raise ApiError(409, "approval_already_recorded", "An approval decision is already recorded")
        try:
            if transactional_audit_enabled():
                result = atomic_recommendation_action(
                    principal, recommendation_id,
                    "approve" if request.approval_status == "approved" else "reject",
                    {"note": request.note},
                )
                approval = result.get("approval") or {}
            else:
                approval = create_recommendation_approval({
                    "recommendation_id": recommendation_id,
                    "approved_by_operator_id": principal.operator_id,
                    "approval_status": request.approval_status,
                    "approval_note": request.note,
                })
                audit_action(
                    principal,
                    "recommendation_approved" if request.approval_status == "approved" else "approval_rejected",
                    "recommendation", recommendation_id,
                    metadata={"approval_status": request.approval_status, "note_supplied": bool(request.note)},
                )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return {
            **approval,
            "operator": principal.public_dict(),
        }

    @app.get("/operators/me")
    def operator_me(
        principal: OperatorPrincipal = Depends(authenticated_operator),
    ):
        return {"id": principal.operator_id, **principal.public_dict()}

    @app.get("/operators/me/portfolios")
    def operator_portfolios(
        principal: OperatorPrincipal = Depends(authenticated_operator),
    ):
        try:
            if principal.role == "admin":
                return [{"access_role": "admin", **portfolio} for portfolio in list_portfolios()]
            records = list_operator_portfolios(principal.operator_id)
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return [
            {
                **(item.get("portfolios") or {}),
                "access_role": item.get("role_override") or principal.role,
            }
            for item in records if item.get("portfolios")
        ]

    @app.get("/operators")
    def operators(
        limit: int = Query(default=250, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        principal: OperatorPrincipal = Depends(require_permission("operators:manage")),
    ):
        try:
            records = list_operators(limit=limit, offset=offset)
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return [{
            "id": item.get("id"), "email": item.get("email"),
            "display_name": item.get("display_name"), "role": item.get("role"),
            "status": item.get("status"), "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        } for item in records]

    @app.post("/operators", status_code=201)
    def add_operator(
        request: OperatorCreateRequest,
        principal: OperatorPrincipal = Depends(require_permission("operators:manage")),
    ):
        if request.role not in ROLES or request.status not in {"active", "inactive"}:
            raise ApiError(422, "invalid_operator_access", "Operator role or status is invalid")
        if not _operator_rbac_storage_enabled():
            raise ApiError(503, "operator_audit_storage_disabled", "Operator audit storage is not enabled")
        try:
            created = create_operator({
                "auth_subject": request.auth_subject.strip(),
                "email": request.email.strip().lower(),
                "display_name": request.display_name.strip(),
                "role": request.role, "status": request.status,
            })
            audit_action(
                principal, "operator_created", "operator", str(created["id"]),
                metadata={"role": request.role, "status": request.status},
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return {key: created.get(key) for key in (
            "id", "email", "display_name", "role", "status", "created_at", "updated_at"
        )}

    @app.patch("/operators/{operator_id}")
    def change_operator(
        operator_id: str, request: OperatorUpdateRequest,
        principal: OperatorPrincipal = Depends(require_permission("operators:manage")),
    ):
        fields = request.model_dump(exclude_none=True)
        if not fields:
            raise ApiError(422, "operator_update_required", "A role or status update is required")
        if fields.get("role") not in (None, *ROLES) or fields.get("status") not in (None, "active", "inactive"):
            raise ApiError(422, "invalid_operator_access", "Operator role or status is invalid")
        if not _operator_rbac_storage_enabled():
            raise ApiError(503, "operator_audit_storage_disabled", "Operator audit storage is not enabled")
        try:
            if transactional_audit_enabled():
                updated = transactional_operator_action(
                    "pubba_audited_operator_update",
                    {"p_actor_operator_id": principal.operator_id,
                     "p_target_operator_id": operator_id, "p_changes": fields},
                )
            else:
                updated = update_operator(operator_id, fields)
                audit_action(
                    principal, "operator_access_updated", "operator", operator_id,
                    metadata=fields,
                )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return {key: updated.get(key) for key in (
            "id", "email", "display_name", "role", "status", "created_at", "updated_at"
        )}

    @app.put("/operators/{operator_id}/portfolio-access")
    def change_operator_portfolio_access(
        operator_id: str, request: OperatorPortfolioAccessRequest,
        principal: OperatorPrincipal = Depends(require_permission("operators:manage")),
    ):
        if request.role_override not in (None, "viewer", "operator", "approver"):
            raise ApiError(422, "invalid_portfolio_role", "Portfolio role override is invalid")
        if not transactional_audit_enabled():
            raise ApiError(503, "transactional_audit_disabled", "Transactional auditing is not enabled")
        try:
            return transactional_operator_action(
                "pubba_audited_portfolio_access_change",
                {
                    "p_actor_operator_id": principal.operator_id,
                    "p_target_operator_id": operator_id,
                    "p_portfolio_id": request.portfolio_id,
                    "p_role_override": request.role_override,
                    "p_active": request.active,
                },
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.post("/telemetry", status_code=201)
    def add_telemetry(
        request: TelemetryCreateRequest,
        x_telemetry_key: Optional[str] = Header(default=None, alias="X-Telemetry-Key"),
    ):
        if not _telemetry_writes_allowed(x_telemetry_key):
            raise ApiError(
                403, "telemetry_writes_disabled",
                "Telemetry writes are disabled or not authorized",
            )
        try:
            result = ingest_batch(
                [request.model_dump()], adapter=GenericJsonTelemetryAdapter(),
                persist=create_telemetry,
                source_latest=get_latest_telemetry_for_source,
                max_batch_size=1,
            )
        except TelemetryValidationError as exc:
            raise ApiError(422, "invalid_telemetry", str(exc), field=exc.field) from exc
        except SupabaseError as exc:
            _raise_telemetry_api_error(exc)
        if result["rejected"]:
            rejection = result["rejected_records"][0]
            status_code = 404 if rejection["code"] == "unknown_asset" else 422
            raise ApiError(
                status_code, rejection["code"], rejection["message"],
                field=rejection.get("field"),
            )
        if result["duplicate"]:
            try:
                response = _telemetry_response(get_latest_telemetry(request.asset_id))
            except SupabaseError as exc:
                _raise_telemetry_api_error(exc)
            return {**response, "ingestion_status": "duplicate"}
        record = result["accepted_records"][0]["record"]
        return {
            **_telemetry_response(record),
            "ingestion_status": "accepted",
            "ingestion_id": result["ingestion_id"],
        }

    @app.post("/telemetry/batch")
    def add_telemetry_batch(
        request: TelemetryBatchRequest,
        x_telemetry_key: Optional[str] = Header(default=None, alias="X-Telemetry-Key"),
    ):
        if not _telemetry_writes_allowed(x_telemetry_key):
            raise ApiError(
                403, "telemetry_writes_disabled",
                "Telemetry writes are disabled or not authorized",
            )
        try:
            return ingest_batch(
                request.observations,
                adapter=GenericJsonTelemetryAdapter(),
                persist=create_telemetry,
                source_latest=get_latest_telemetry_for_source,
                max_batch_size=configured_batch_limit(),
            )
        except TelemetryValidationError as exc:
            raise ApiError(422, "invalid_telemetry", str(exc), field=exc.field) from exc
        except SupabaseError as exc:
            _raise_telemetry_api_error(exc)

    @app.get("/dispatch-events")
    def dispatch_events(
        portfolio_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        asset_id: Optional[str] = None,
        market: Optional[str] = None,
        location: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        portfolio_id = resolve_read_portfolio(principal, portfolio_id)
        _validate_date_range(start_date, end_date)
        try:
            return list_dispatch_events(
                portfolio_id=portfolio_id,
                start_date=start_date,
                end_date=end_date,
                asset_id=asset_id,
                market=market,
                location=location,
                status=status,
                limit=limit,
                offset=offset,
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/simulations")
    def simulations(
        portfolio_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        principal: OperatorPrincipal | None = Depends(optional_read_operator),
    ):
        try:
            portfolio_id = resolve_read_portfolio(principal, portfolio_id)
            portfolio = get_default_portfolio() if not portfolio_id else {"id": portfolio_id}
            return list_simulation_results(
                portfolio_id=portfolio["id"], asset_id=asset_id,
                limit=limit, offset=offset,
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/dispatch-events/export.csv")
    def export_dispatch_events(
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        asset_id: Optional[str] = None,
        market: Optional[str] = None,
        location: Optional[str] = None,
        status: Optional[str] = None,
    ):
        _validate_date_range(start_date, end_date)
        try:
            records = list_dispatch_events(
                start_date=start_date,
                end_date=end_date,
                asset_id=asset_id,
                market=market,
                location=location,
                status=status,
                limit=None,
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        fieldnames = [
            "id",
            "dispatch_id",
            "asset_id",
            "simulation_id",
            "dispatch_timestamp",
            "charge_start",
            "charge_end",
            "discharge_start",
            "discharge_end",
            "market",
            "location",
            "status",
            "energy_mwh",
            "charging_cost",
            "discharge_revenue",
            "storage_cost",
            "net_profit",
            "created_at",
        ]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=dispatch-events.csv"
            },
        )

    def report(period: str, start_date: date | None, end_date: date | None):
        _validate_date_range(start_date, end_date)
        try:
            return aggregate_report(
                period, start_date=start_date, end_date=end_date
            )
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/reports/daily", response_model=list[ReportPeriodResponse])
    def daily_report(
        start_date: Optional[date] = None, end_date: Optional[date] = None
    ):
        return report("daily", start_date, end_date)

    @app.get("/reports/weekly", response_model=list[ReportPeriodResponse])
    def weekly_report(
        start_date: Optional[date] = None, end_date: Optional[date] = None
    ):
        return report("weekly", start_date, end_date)

    @app.get("/reports/monthly", response_model=list[ReportPeriodResponse])
    def monthly_report(
        start_date: Optional[date] = None, end_date: Optional[date] = None
    ):
        return report("monthly", start_date, end_date)

    @app.get("/reports/quarterly", response_model=list[ReportPeriodResponse])
    def quarterly_report(
        start_date: Optional[date] = None, end_date: Optional[date] = None
    ):
        return report("quarterly", start_date, end_date)

    @app.get("/reports/yearly", response_model=list[ReportPeriodResponse])
    def yearly_report(
        start_date: Optional[date] = None, end_date: Optional[date] = None
    ):
        return report("yearly", start_date, end_date)

    @app.get("/lmp")
    def get_lmp(
        market: str = "RTM",
        location: str = "TH_NP15_GEN-APND",
        date: Optional[str] = None,
    ):
        try:
            df = fetch_lmp_data(location=location, market=market, date=date)
        except CaisoOasisError as exc:
            raise ApiError(502, "upstream_service_error", str(exc), upstream_service="CAISO OASIS") from exc
        except ValueError as exc:
            raise ApiError(400, "invalid_request", str(exc), field="date") from exc
        return jsonable_encoder(df.to_dict(orient="records"))

    @app.get("/arbitrage")
    def get_arbitrage(
        market: str = "RTM",
        location: str = "TH_NP15_GEN-APND",
        date: Optional[str] = None,
        duration_hours: float = 8,
        round_trip_efficiency: float = 0.80,
    ):
        try:
            df = fetch_lmp_data(location=location, market=market, date=date)
            result = analyze_lmp_arbitrage(
                df,
                duration_hours=duration_hours,
                round_trip_efficiency=round_trip_efficiency,
            )
        except CaisoOasisError as exc:
            raise ApiError(502, "upstream_service_error", str(exc), upstream_service="CAISO OASIS") from exc
        except (ArbitrageAnalysisError, ValueError) as exc:
            field = str(exc).split(" ", 1)[0] if str(exc) else None
            raise ApiError(400, "arbitrage_error", str(exc), field=field) from exc
        return jsonable_encoder(result)

    @app.get(
        "/simulate",
        response_model=SimulationResponse,
        response_model_exclude_none=True,
    )
    def get_simulation(
        power_mw: float = Query(gt=0),
        market: str = "RTM",
        location: str = "TH_NP15_GEN-APND",
        date: Optional[str] = None,
        duration_hours: float = Query(default=8, gt=0),
        round_trip_efficiency: float = Query(default=0.80, gt=0, le=1),
        cycles: float = Query(default=1, gt=0),
        storage_fee_per_mwh: float = Query(default=0, ge=0),
        variable_om_per_mwh: float = Query(default=0, ge=0),
    ):
        return _run_simulation(
            SimulationRequest(
                location=location,
                market=market,
                date=date,
                power_mw=power_mw,
                duration_hours=duration_hours,
                round_trip_efficiency=round_trip_efficiency,
                cycles=cycles,
                storage_fee_per_mwh=storage_fee_per_mwh,
                variable_om_per_mwh=variable_om_per_mwh,
            )
        )

    @app.post("/simulate", response_model=SimulationResponse)
    def post_simulation(
        request: SimulationRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        result = _run_simulation(request)
        persistence = _persist_completed_simulation(
            request,
            result,
            idempotency_key
            or derive_idempotency_key(request.model_dump(), result),
        )
        return {**result, "persistence": persistence}

    return app


app = create_app()
