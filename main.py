from fastapi import FastAPI, HTTPException
from datetime import date
from gridstatus import CAISO, MarketType

app = FastAPI()
iso = CAISO()

@app.get("/")
def read_root():
    return {"message": "Only1 LMP API is live."}

@app.get("/lmp")
def get_lmp(market: str = "RTM", location: str = "TH_NP15_GEN-APND"):
    try:
        market_enum = MarketType[market]
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid market type. Use 'RTM' or 'DAM'.")

    today = date.today().strftime("%Y-%m-%d")
    data = iso.get_lmp(date=today, market=market_enum, locations=[location])
    return data.to_dict(orient="records")from fastapi import FastAPI
from gridstatus import CAISO
from datetime import date

app = FastAPI()
iso = CAISO()

@app.get("/")
def root():
    return {"message": "Only1 LMP API is running"}

@app.get("/lmp")
def get_lmp(market: str = "RTM", location: str = "TH_NP15_GEN-APND"):
    today = date.today().strftime("%Y-%m-%d")
    data = iso.get_lmp(date=today, market=market, locations=[location])
    return data.to_dict(orient="records")
