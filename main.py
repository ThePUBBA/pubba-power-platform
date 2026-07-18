from __future__ import annotations

import csv
import hmac
import io
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, Header, Query, Request
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
    create_recommendation_capture,
    create_telemetry,
    derive_idempotency_key,
    get_asset_performance,
    get_asset,
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
    list_simulation_results,
    list_telemetry_history,
    find_recent_recommendation_capture,
    persist_simulation,
    update_asset,
    update_recommendation_links,
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


def _recommendation_writes_allowed(write_key: str | None) -> bool:
    if os.getenv("RECOMMENDATION_WRITES_ENABLED", "").strip().lower() not in {
        "1", "true", "yes",
    }:
        return False
    expected = os.getenv("RECOMMENDATION_WRITE_TOKEN", "")
    return bool(expected and write_key) and hmac.compare_digest(write_key, expected)


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
    ):
        try:
            return build_portfolio_summary(
                start_at=start_at, end_at=end_at, timezone_name=timezone_name
            )
        except PortfolioSummaryError as exc:
            raise ApiError(400, exc.code, str(exc), field=exc.field) from exc
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/portfolio/assets", response_model=list[AssetPerformanceResponse])
    def portfolio_assets():
        try:
            return get_asset_performance()
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
        timezone_name: Optional[str] = Query(default=None, alias="timezone"),
        include_market: bool = Query(default=True),
    ):
        try:
            dashboard = build_dashboard_summary(
                timezone_name=timezone_name, include_market=include_market
            )
            try:
                dashboard["recommendations"] = current_recommendations(
                    dashboard=dashboard
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

    def current_recommendations(*, dashboard: dict | None = None) -> dict:
        try:
            dashboard = dashboard or build_dashboard_summary(include_market=True)
            assets = get_asset_performance()
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
    def portfolio_recommendations():
        return current_recommendations()

    @app.get("/recommendations/assets/{asset_id}")
    def asset_recommendation(asset_id: str):
        result = current_recommendations()
        recommendation = next((
            item for item in result["recommendations"] if item["asset_id"] == asset_id
        ), None)
        if recommendation is None:
            raise ApiError(404, "asset_not_found", "Asset was not found", field="asset_id")
        return recommendation

    def require_recommendation_write(write_key: str | None) -> None:
        if not _recommendation_writes_allowed(write_key):
            raise ApiError(
                403, "recommendation_writes_disabled",
                "Recommendation audit writes are disabled or not authorized",
            )

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
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return history_detail(record, simulation=simulation, dispatch=dispatch)

    @app.post("/recommendations/{asset_id}/capture", status_code=201)
    def capture_recommendation(
        asset_id: str, response: Response,
        x_recommendation_key: Optional[str] = Header(
            default=None, alias="X-Recommendation-Key"
        ),
    ):
        require_recommendation_write(x_recommendation_key)
        current = current_recommendations()
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
            portfolio = get_default_portfolio()
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
                response.status_code = 200
                return {"capture_status": "duplicate", "recommendation": existing}
            created = create_recommendation_capture(snapshot)
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
    ):
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
    def recommendation_history_portfolio_analytics():
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
    def recommendation_history_detail(recommendation_id: str):
        return load_history_detail(recommendation_id)

    @app.post("/recommendations/history/{recommendation_id}/acknowledge")
    def acknowledge_recommendation(
        recommendation_id: str, request: RecommendationAcknowledgementRequest,
        x_recommendation_key: Optional[str] = Header(default=None, alias="X-Recommendation-Key"),
    ):
        require_recommendation_write(x_recommendation_key)
        detail = load_history_detail(recommendation_id)
        if detail.get("acknowledged_at"):
            raise ApiError(409, "recommendation_already_acknowledged", "Recommendation was already acknowledged")
        try:
            updated = update_recommendation_links(recommendation_id, {
                "acknowledged_at": datetime.now(timezone.utc).isoformat(),
                "acknowledgement_note": request.note,
                "acknowledgement_attribution": "authenticated_operator_workflow",
            })
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return history_detail(
            updated, simulation=detail.get("simulation"), dispatch=detail.get("dispatch")
        )

    @app.post("/recommendations/history/{recommendation_id}/link-simulation")
    def link_recommendation_simulation(
        recommendation_id: str, request: RecommendationLinkRequest,
        x_recommendation_key: Optional[str] = Header(default=None, alias="X-Recommendation-Key"),
    ):
        require_recommendation_write(x_recommendation_key)
        detail = load_history_detail(recommendation_id)
        if detail.get("simulation_id"):
            if str(detail["simulation_id"]) == request.record_id:
                return detail
            raise ApiError(409, "simulation_already_linked", "Recommendation already has a simulation link")
        try:
            simulation = get_simulation_result(request.record_id)
            if not simulation:
                raise ApiError(404, "simulation_not_found", "Simulation was not found")
            if simulation.get("portfolio_id") != detail.get("portfolio_id") or (
                simulation.get("asset_id") and simulation.get("asset_id") != detail.get("asset_id")
            ):
                raise ApiError(409, "simulation_link_mismatch", "Simulation does not match recommendation ownership")
            updated = update_recommendation_links(recommendation_id, {
                "simulation_id": simulation["id"],
                "simulation_linked_at": datetime.now(timezone.utc).isoformat(),
            })
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return history_detail(updated, simulation=simulation, dispatch=detail.get("dispatch"))

    @app.post("/recommendations/history/{recommendation_id}/link-dispatch")
    def link_recommendation_dispatch(
        recommendation_id: str, request: RecommendationLinkRequest,
        x_recommendation_key: Optional[str] = Header(default=None, alias="X-Recommendation-Key"),
    ):
        require_recommendation_write(x_recommendation_key)
        detail = load_history_detail(recommendation_id)
        if detail.get("dispatch_id"):
            if str(detail["dispatch_id"]) == request.record_id:
                return detail
            raise ApiError(409, "dispatch_already_linked", "Recommendation already has a dispatch link")
        try:
            dispatch = get_dispatch_event_record(request.record_id)
            if not dispatch:
                raise ApiError(404, "dispatch_not_found", "Dispatch was not found")
            if (
                dispatch.get("portfolio_id") != detail.get("portfolio_id")
                or dispatch.get("asset_id") != detail.get("asset_id")
            ):
                raise ApiError(409, "dispatch_link_mismatch", "Dispatch does not match recommendation ownership")
            updated = update_recommendation_links(recommendation_id, {
                "dispatch_id": dispatch["id"],
                "dispatch_linked_at": datetime.now(timezone.utc).isoformat(),
            })
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)
        return history_detail(updated, simulation=detail.get("simulation"), dispatch=dispatch)

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
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        asset_id: Optional[str] = None,
        market: Optional[str] = None,
        location: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ):
        _validate_date_range(start_date, end_date)
        try:
            return list_dispatch_events(
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
        asset_id: Optional[str] = None,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ):
        try:
            portfolio = get_default_portfolio()
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
