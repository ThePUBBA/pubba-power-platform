from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from arbitrage import ArbitrageAnalysisError, analyze_lmp_arbitrage
from airtable import (
    AirtableError,
    airtable_is_configured,
    create_dispatch_event,
    find_asset_by_asset_id,
    get_portfolio_summary,
    recalculate_daily_pnl,
    save_simulation_to_airtable,
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


class HealthResponse(BaseModel):
    status: str
    service_name: str
    api_version: str
    current_utc_timestamp: datetime


class PortfolioSummaryResponse(BaseModel):
    total_assets: int
    active_assets: int
    total_simulations: int
    total_dispatches: int
    cumulative_revenue: float
    cumulative_charging_cost: float
    cumulative_storage_cost: float
    cumulative_net_profit: float


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


def _archive_simulation(request: SimulationRequest, result: dict) -> None:
    airtable_result = {
        **result,
        "location": request.location,
        "market": request.market,
        "date": request.date,
    }
    simulation_record_id = None
    try:
        simulation_record_id = save_simulation_to_airtable(airtable_result)
    except AirtableError:
        logger.exception(
            "Airtable operation failed",
            extra={"airtable_operation": "archive_simulation"},
        )
        return

    if not simulation_record_id:
        logger.error(
            "Airtable simulation archive returned no record ID; skipping ledger updates",
            extra={"airtable_operation": "archive_simulation"},
        )
        return

    if not request.asset_id:
        return
    try:
        asset = find_asset_by_asset_id(request.asset_id)
    except AirtableError:
        logger.exception(
            "Airtable operation failed",
            extra={"airtable_operation": "find_asset", "asset_id": request.asset_id},
        )
        return
    if not asset:
        logger.warning(
            "Airtable asset not found; skipping portfolio ledger updates",
            extra={"airtable_operation": "find_asset", "asset_id": request.asset_id},
        )
        return

    try:
        create_dispatch_event(asset, airtable_result, simulation_record_id)
    except AirtableError:
        logger.exception(
            "Airtable operation failed",
            extra={"airtable_operation": "create_dispatch", "asset_id": request.asset_id},
        )
        return

    pnl_date = airtable_result["charging_window"]["start_timestamp"][:10]
    try:
        recalculate_daily_pnl(pnl_date)
    except AirtableError:
        logger.exception(
            "Airtable operation failed",
            extra={"airtable_operation": "update_daily_pnl", "asset_id": request.asset_id},
        )


def create_app() -> FastAPI:
    app = FastAPI(title=SERVICE_NAME, version=API_VERSION)
    origins = _allowed_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
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
        return {
            "status": "ok",
            "service_name": SERVICE_NAME,
            "api_version": API_VERSION,
            "current_utc_timestamp": datetime.now(timezone.utc),
        }

    @app.get("/portfolio/summary", response_model=PortfolioSummaryResponse)
    def portfolio_summary():
        try:
            return get_portfolio_summary()
        except AirtableError as exc:
            raise ApiError(
                502,
                "upstream_service_error",
                str(exc),
                upstream_service="Airtable",
            ) from exc

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

    @app.get("/simulate", response_model=SimulationResponse)
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
    def post_simulation(request: SimulationRequest):
        result = _run_simulation(request)
        if airtable_is_configured():
            _archive_simulation(request, result)
        return result

    return app


app = create_app()
