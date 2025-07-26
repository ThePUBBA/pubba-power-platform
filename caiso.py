import pandas as pd
import requests
from datetime import datetime

def fetch_lmp_data(location="TH_NP15_GEN-APND", market="LMP", date=None):
    if date is None:
        date = datetime.utcnow().strftime("%Y%m%d")

    url = "http://oasis.caiso.com/oasisapi/SingleZip"
    params = {
        "queryname": "PRC_LMP",
        "startdatetime": f"{date}T00:00-0000",
        "enddatetime": f"{date}T23:59-0000",
        "market_run_id": market,
        "node": location,
        "version": 1,
        "resultformat": 6
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    df = pd.read_csv(pd.compat.StringIO(response.text))
    df = df[["LOCATION", "OPR_DT", "INTERVAL_NUM", "LMP"]]
    df.columns = ["location", "date", "hour", "price"]
    return df

