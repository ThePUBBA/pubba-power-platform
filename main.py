from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder

from arbitrage import ArbitrageAnalysisError, analyze_lmp_arbitrage
from caiso import CaisoOasisError, fetch_lmp_data


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
