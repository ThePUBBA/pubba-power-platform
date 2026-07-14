from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date, datetime, timezone
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
    derive_idempotency_key,
    get_asset_performance,
    get_asset,
    get_portfolio_summary,
    list_assets,
    list_dispatch_events,
    persist_simulation,
    update_asset,
)
from caiso import CaisoOasisError, fetch_lmp_data
from simulation import StorageSimulationError, simulate_storage_profit


SERVICE_NAME = "Only1 LMP API"
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


class PortfolioSummaryResponse(BaseModel):
    total_assets: int
    active_assets: int
    total_simulations: int
    total_dispatches: int
    cumulative_revenue: float
    cumulative_charging_cost: float
    cumulative_storage_cost: float
    cumulative_net_profit: float


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


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date and end_date and start_date > end_date:
        raise ApiError(
            400,
            "invalid_date_range",
            "start_date must be on or before end_date",
            field="start_date",
        )


def create_app() -> FastAPI:
    app = FastAPI(title=SERVICE_NAME, version=API_VERSION)
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
        return {"message": "Only1 LMP API is running"}

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

    @app.get("/portfolio/summary", response_model=PortfolioSummaryResponse)
    def portfolio_summary():
        try:
            return get_portfolio_summary()
        except SupabaseError as exc:
            _raise_supabase_api_error(exc)

    @app.get("/portfolio/assets", response_model=list[AssetPerformanceResponse])
    def portfolio_assets():
        try:
            return get_asset_performance()
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
