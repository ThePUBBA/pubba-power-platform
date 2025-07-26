from fastapi import FastAPI, HTTPException
from only1_iso import ISO
from datetime import date
import logging

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Only1 LMP API is running"}

@app.get("/lmp")
def get_lmp(market: str = "LMP", location: str = "TH_NP15_GEN-APND"):
    today = date.today().strftime("%Y-%m-%d")
    try:
        logging.info(f"Fetching LMP for market={market}, location={location}, date={today}")
        df = ISO().get_lmp(date=today, market=market, locations=[location])
        return df.to_dict(orient="records")
    except Exception as e:
        logging.exception("Error fetching LMP data:")
        raise HTTPException(status_code=500, detail=str(e))

