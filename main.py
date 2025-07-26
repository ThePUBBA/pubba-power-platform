from fastapi import FastAPI, HTTPException
from datetime import date
from only1_iso import ISO

app = FastAPI()
iso = ISO()

@app.get("/")
def root():
    return {"status": "Only1 LMP API is live"}

@app.get("/lmp")
def get_lmp(market: str = "LMP", location: str = "TH_NP15_GEN-APND"):
    today = date.today().strftime("%Y-%m-%d")
    try:
        df = iso.get_lmp(date=today, market=market, locations=[location])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return df.to_dict(orient="records")

