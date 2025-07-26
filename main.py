from fastapi import FastAPI, HTTPException
from caiso import fetch_lmp_data

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Only1 LMP API is running"}

@app.get("/lmp")
def get_lmp(market: str = "LMP", location: str = "TH_NP15_GEN-APND", date: str = None):
    try:
        df = fetch_lmp_data(location=location, market=market, date=date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return df.to_dict(orient="records")

