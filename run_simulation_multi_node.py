#!/usr/bin/env python3
"""
Only1 Power — run_simulation_multi_node.py (POC, DAM bulk + RTM optional)
- POC default: --market dam, pulls ALL once/day then filters (fewer API calls, avoids 429)
- --yesterday / --date supported; RTM optional with --market rtm
- Simple threshold sim + Plotly reports
"""
from __future__ import annotations
import argparse, os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import plot
from oasis_client import OasisClient
# optional custom strategy
try:
    from strategy import simulate_node as simulate_node_external  # type: ignore
except Exception:
    simulate_node_external = None

# Node aliases: RTM uses SLAP_*, DAM uses DLAP_*
ALIAS_RTM = {"MPBBAC":"SLAP_BANC-APND","MPBNCA":"SLAP_NCPA-APND","MPBPGE":"SLAP_PGAE-APND"}
ALIAS_DAM = {"MPBBAC":"DLAP_BANC-APND","MPBNCA":"DLAP_NCPA-APND","MPBPGE":"DLAP_PGAE-APND"}

@dataclass
class Thresholds:
    charge_lmp: float = float(os.getenv("ONLY1_CHARGE_LMP", 30))
    discharge_lmp: float = float(os.getenv("ONLY1_DISCHARGE_LMP", 60))
    soc_min_pct: float = float(os.getenv("ONLY1_SOC_MIN_PCT", 5))
    max_cycles_per_day: float = float(os.getenv("ONLY1_MAX_CYCLES", 1.5))

def simulate_node_fallback(df_prices: pd.DataFrame, capacity_mwh: float, efficiency_rt: float, th: Thresholds) -> dict:
    if df_prices.empty: return {"events": [], "profit": 0.0, "utilization_pct": 0.0}
    df = df_prices.sort_values("timestamp").copy()
    step = capacity_mwh / 12.0  # 5-min slice of 1C
    soc = capacity_mwh * 0.5; revenue=0.0; through=0.0; last="idle"; events=[]
    for _, r in df.iterrows():
        p = float(r["lmp"]) if pd.notna(r["lmp"]) else None
        if p is None: continue
        if p >= th.discharge_lmp and soc > (th.soc_min_pct/100.0)*capacity_mwh:
            e = min(step, soc); soc -= e; revenue += e*p; through += e; mode="discharge"
        elif p <= th.charge_lmp and soc < capacity_mwh:
            e = min(step, capacity_mwh - soc); revenue -= e*p; soc += e*efficiency_rt; through += e; mode="charge"
        else:
            mode="idle"
        if mode != last:
            events.append({"timestamp": r["timestamp"], "mode": mode, "price": p, "soc_mwh": soc}); last=mode
    util = 100.0 * min(1.0, through/capacity_mwh)
    return {"events": events, "profit": revenue, "utilization_pct": util}

def save_node_report(node: str, prices: pd.DataFrame, res: dict, th: Thresholds, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = out_dir / f"{node}_dispatch_{ts}.html"
    fig = plot_node(node, prices, res, th)
    plot(fig, filename=str(path), auto_open=False, include_plotlyjs="cdn")
    return path

def plot_node(node: str, prices: pd.DataFrame, res: dict, th: Thresholds):
    fig = plotly_figure()
    if not prices.empty:
        fig.add_trace(go.Scatter(x=prices["timestamp"], y=prices["lmp"], name="LMP ($/MWh)", line=dict(color="#2a6efb")))
    fig.add_hline(y=th.charge_lmp, line_dash="dash", line_color="#22c55e", annotation_text="Charge TH")
    fig.add_hline(y=th.discharge_lmp, line_dash="dash", line_color="#ef4444", annotation_text="Discharge TH")
    title=f"Only1 — {node} | Profit ${res.get('profit',0):,.2f} | Util {res.get('utilization_pct',0):.1f}%"
    fig.update_layout(title=title, xaxis_title="Time (UTC)", yaxis_title="LMP ($/MWh)", template="plotly_white")
    return fig

def plotly_figure(): return go.Figure()

def save_multi(results: Dict[str, dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = out_dir / f"multi_node_lmp_{ts}.html"
    rows = [{"node":n, "profit":r.get("profit",0.0), "utilization_pct": r.get("utilization_pct",0.0)} for n,r in results.items()]
    df = pd.DataFrame(rows)
    html = f"""<html><head><meta charset='utf-8'><title>Only1 Multi-Node</title></head>
    <body style='font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;'>
      <h2>Only1 Power — Multi-Node Summary</h2>
      {df.to_html(index=False, float_format=lambda x: f"${x:,.2f}" if isinstance(x,(int,float)) else x)}
    </body></html>"""
    path.write_text(html); return path

def parse_date(d: str) -> datetime:
    y,m,day = map(int, d.split("-"))
    return datetime(y,m,day,tzinfo=timezone.utc)

def main():
    p = argparse.ArgumentParser(description="Only1 multi-node sim (POC bulk DAM, RTM optional)")
    p.add_argument("--nodes", type=str, default=os.getenv("ONLY1_NODES","MPBBAC,MPBNCA,MPBPGE"))
    p.add_argument("--market", choices=["dam","rtm"], default=os.getenv("ONLY1_MARKET","dam"))
    p.add_argument("--live", action="store_true")
    p.add_argument("--hours", type=int, default=int(os.getenv("ONLY1_LIVE_HOURS",6)))
    p.add_argument("--yesterday", action="store_true")
    p.add_argument("--date", type=str)
    p.add_argument("--data-dir", type=str, default=os.getenv("ONLY1_DATA_DIR","data"))
    p.add_argument("--reports-dir", type=str, default=os.getenv("ONLY1_REPORTS_DIR","reports"))
    p.add_argument("--capacity-mwh", type=float, default=float(os.getenv("ONLY1_CAPACITY_MWH",10)))
    p.add_argument("--efficiency-rt", type=float, default=float(os.getenv("ONLY1_EFFICIENCY_RT",0.85)))
    p.add_argument("--charge-lmp", type=float, default=float(os.getenv("ONLY1_CHARGE_LMP",30)))
    p.add_argument("--discharge-lmp", type=float, default=float(os.getenv("ONLY1_DISCHARGE_LMP",60)))
    p.add_argument("--soc-min-pct", type=float, default=float(os.getenv("ONLY1_SOC_MIN_PCT",5)))
    p.add_argument("--max-cycles", type=float, default=float(os.getenv("ONLY1_MAX_CYCLES",1.5)))
    p.add_argument("--write-csv", action="store_true")
    args = p.parse_args()

    raw = [n.strip() for n in args.nodes.split(",") if n.strip()]
    nodes = [ALIAS_DAM.get(n,n) if args.market=="dam" else ALIAS_RTM.get(n,n) for n in raw]

    data_dir = Path(args.data_dir); reports_dir = Path(args.reports_dir)
    data_dir.mkdir(parents=True, exist_ok=True); reports_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    use_date = parse_date(args.date) if args.date else (datetime(*(now - timedelta(days=1)).timetuple()[:3], tzinfo=timezone.utc) if args.yesterday else None)

    client = OasisClient()
    if use_date:
        if args.market=="dam":
            # DAM trade-day window: 07:00Z → +1d 07:00Z
            trade_start = use_date + timedelta(hours=7)
            print(f"🟦 DAM DATE mode (trade day UTC): {trade_start.isoformat()} → {(trade_start+timedelta(days=1)).isoformat()}")
            # bulk fetch once
            dfs = client.dam_lmp_bulk(trade_start, nodes)
            all_prices: Dict[str, pd.DataFrame] = {}
            for node in nodes:
                df = dfs.get(node, pd.DataFrame(columns=["timestamp","node","lmp"]))
                print(f"→ {node} (DAM): fetched {len(df)} rows "
                      f"({df['timestamp'].min() if len(df) else 'NA'} → {df['timestamp'].max() if len(df) else 'NA'})")
                if df.empty: continue
                if args.write_csv:
                    tag = (trade_start - timedelta(hours=7)).date().isoformat()
                    df[["timestamp","lmp"]].to_csv(data_dir / f"lmp_{node}_{tag}.csv", index=False)
                all_prices[node]=df
        else:
            # RTM trade-day window
            start = use_date + timedelta(hours=7); end = start + timedelta(days=1)
            print(f"🟧 RTM DATE mode (trade day UTC): {start.isoformat()} → {end.isoformat()}")
            all_prices={}
            for node in nodes:
                df = client.rt5m_lmp(node, start, end)
                print(f"→ {node} (RTM): fetched {len(df)} rows")
                if not df.empty:
                    all_prices[node]=df
    elif args.live:
        # Live (RTM): floor to last completed 5-min with 15-min lag
        def floor5(dt): m=dt.minute-(dt.minute%5); return dt.replace(minute=m, second=0, microsecond=0)
        end = floor5(now - timedelta(minutes=15)); start = end - timedelta(hours=args.hours)
        print(f"🌐 LIVE mode: {start.isoformat()} → {end.isoformat()}")
        all_prices={}
        for node in nodes:
            df = client.rt5m_lmp(node, start, end)
            print(f"→ {node} (RTM LIVE): fetched {len(df)} rows")
            if not df.empty: all_prices[node]=df
    else:
        print("📄 CSV mode (today)"); start = datetime(now.year,now.month,now.day,tzinfo=timezone.utc); end=now
        all_prices={}

    if not all_prices:
        print("❌ No price data available; exiting."); return

    th = Thresholds(args.charge_lmp, args.discharge_lmp, args.soc_min_pct, args.max_cycles)
    results: Dict[str, dict] = {}
    for node, df in all_prices.items():
        if simulate_node_external:
            res = simulate_node_external(df,
                thresholds={"charge_lmp": th.charge_lmp, "discharge_lmp": th.discharge_lmp, "soc_min_pct": th.soc_min_pct, "max_cycles_per_day": th.max_cycles_per_day},
                capacity_mwh=args.capacity_mwh, efficiency_rt=args.efficiency_rt)
        else:
            res = simulate_node_fallback(df, args.capacity_mwh, args.efficiency_rt, th)
        results[node]=res
        path = save_node_report(node, df, res, th, reports_dir)
        print(f"✅ Saved node report: {path}")

    multi = save_multi(results, reports_dir)
    print(f"✅ Saved multi-node chart: {multi}")
    print("\n📊 Profit by Node:")
    for n, r in results.items(): print(f"  {n}: ${r.get('profit',0.0):.2f}")

if __name__ == "__main__":
    main()
