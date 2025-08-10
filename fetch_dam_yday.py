from datetime import datetime, timedelta, timezone
import pandas as pd
import gridstatus

# Short codes -> CAISO DLAPs
NODES = {
    "MPBBAC": "DLAP_BANC-APND",
    "MPBNCA": "DLAP_NCPA-APND",
    "MPBPGE": "DLAP_PGAE-APND",
}

# Yesterday’s CAISO trade-day date label (we’ll still pull DAM by calendar date)
yday_utc = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

caiso = gridstatus.CAISO()

for short, dlap in NODES.items():
    # Pull DAM hourly for the calendar day (gridstatus handles the 07:00/08:00 window)
    df = caiso.get_lmp(date=yday_utc, market="DAY_AHEAD_HOURLY", locations=[dlap])
    if df.empty:
        print(f"⚠️  {dlap}: no rows")
        continue
    # Normalize to the same CSV schema your runner expects
    # gridstatus columns are like: 'Interval Start', 'Interval End', 'Market', 'Location', 'LMP', ...
    df["timestamp"] = pd.to_datetime(df["Interval Start"]).dt.tz_convert("UTC")
    out = df[["timestamp", "LMP"]].rename(columns={"LMP": "lmp"})
    out.to_csv(f"data/lmp_{dlap}_{yday_utc}.csv", index=False)
    print(f"✅ wrote data/lmp_{dlap}_{yday_utc}.csv ({len(out)} rows)")
