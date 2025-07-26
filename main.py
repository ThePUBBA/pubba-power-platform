from fastapi import FastAPI
from gridstatus import CAISO
from datetime import date

app = FastAPI()
iso = CAISO()

@app.get("/")
def root():
    return {"message": "Only1 LMP API is running"}

@app.get("/lmp")
def get_lmp(market: str = "DAM", location: str = "TH_NP15_GEN-APND"):
    today = date.today().strftime("%Y-%m-%d")
    data = iso.get_lmp(date=today, market=market, locations=[location])
    return data.to_dict(orient="records")
