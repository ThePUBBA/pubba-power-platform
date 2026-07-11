from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder

from arbitrage import ArbitrageAnalysisError, analyze_lmp_arbitrage
from caiso import CaisoOasisError, fetch_lmp_data
from simulation import StorageSimulationError, simulate_storage_profit


app = FastAPI()


@app.get("/")
def root():
    return {"message": "Only1 LMP API is running"}


@app.get("/lmp")
def get_lmp(
    market: str = "RTM",
    location: str = "TH_NP15_GEN-APND",
    date: Optional[str] = None,
):
    try:
        df = fetch_lmp_data(location=location, market=market, date=date)
    except CaisoOasisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (ArbitrageAnalysisError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return jsonable_encoder(result)


@app.get("/simulate")
def get_simulation(
    power_mw: float,
    market: str = "RTM",
    location: str = "TH_NP15_GEN-APND",
    date: Optional[str] = None,
    duration_hours: float = 8,
    round_trip_efficiency: float = 0.80,
    cycles: float = 1,
    storage_fee_per_mwh: float = 0,
    variable_om_per_mwh: float = 0,
):
    try:
        df = fetch_lmp_data(location=location, market=market, date=date)
        result = simulate_storage_profit(
            df,
            power_mw=power_mw,
            duration_hours=duration_hours,
            round_trip_efficiency=round_trip_efficiency,
            cycles=cycles,
            storage_fee_per_mwh=storage_fee_per_mwh,
            variable_om_per_mwh=variable_om_per_mwh,
        )
    except CaisoOasisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (ArbitrageAnalysisError, StorageSimulationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return jsonable_encoder(result)
