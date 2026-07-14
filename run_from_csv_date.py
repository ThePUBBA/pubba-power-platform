#!/usr/bin/env python3
"""
Only1 Power — run_from_csv_date.py (latest-only + auto-open + auto-refresh)

Reads local CSVs:
  data/lmp_<NODE>_<YYYY-MM-DD>.csv  (columns: timestamp,lmp or auto-detected)

Nodes can be short codes (MPBBAC, MPBNCA, MPBPGE) → mapped to SLAP_* names.
Dispatch = threshold control with deadband + hysteresis.
Utilization = Equivalent Full Cycles (EFC) vs max_cycles_per_day.

Outputs per run (shared timestamp):
  • 3 per-node dispatch charts (LMP + SOC + charge/discharge bars)
  • 1 multi-node summary table
  • 1 multi-node LMP overlay chart
Also writes reports/last_run_summary.csv for KPIs / history.

Modes:
  • Default: archive (timestamped filenames) + auto-open
  • --latest-only: overwrite canonical files in reports/latest/ (no archive)
  • --auto-refresh-sec N: inject meta-refresh so pages reload automatically
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import plot

# ---------- Aliases (short -> SLAP) ----------
ALIAS_RTM = {
    "MPBBAC": "SLAP_BANC-APND",
    "MPBNCA": "SLAP_NCPA-APND",
    "MPBPGE": "SLAP_PGAE-APND",
}

# ---------- Config ----------
@dataclass
class Thresholds:
    charge_lmp: float = 30.0
    discharge_lmp: float = 60.0
    deadband: float = 2.0  # $/MWh
    soc_min_pct: float = 5.0
    max_cycles_per_day: float = 1.5

# ---------- CSV helpers ----------
TIMESTAMP_CANDIDATES = [
    "timestamp", "time", "interval start", "interval_start",
    "intervalstarttime", "intervalstarttime_gmt", "starttime_gmt",
    "starttime", "start",
]
LMP_CANDIDATES = ["lmp", "lmp_prc", "price", "lmp ($/mwh)"]

def _pick_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    low = {c.lower(): c for c in cols}
    for w in candidates:
        if w in low:
            return low[w]
    # fuzzy contains fallback
    for c in cols:
        lc = c.lower()
        for w in candidates:
            parts = w.split("|")
            if all(p in lc for p in parts):
                return c
    return None

def load_prices_for_node(data_dir: Path, node: str, date_str: str) -> pd.DataFrame:
    path = data_dir / f"lmp_{node}_{date_str}.csv"
    if not path.exists():
        raise FileNotFoundError(path)

    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])  # expected schema
        if "lmp" not in df.columns:
            raise ValueError("missing lmp column")
    except Exception:
        raw = pd.read_csv(path)
        tcol = _pick_col(list(raw.columns), TIMESTAMP_CANDIDATES)
        lcol = _pick_col(list(raw.columns), LMP_CANDIDATES) or next(
            (c for c in raw.columns if "lmp" in c.lower()), None
        )
        if not tcol or not lcol:
            raise ValueError(f"Unrecognized columns in {path.name}: {list(raw.columns)}")
        df = raw[[tcol, lcol]].rename(columns={tcol: "timestamp", lcol: "lmp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp", "lmp"])  # type: ignore[arg-type]

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df[["timestamp", "lmp"]]

# ---------- HTML helpers ----------
def _wrap_html(title: str, body: str, auto_refresh_sec: int = 0) -> str:
    refresh = f"<meta http-equiv='refresh' content='{auto_refresh_sec}'>" if auto_refresh_sec and auto_refresh_sec > 0 else ""
    return (
        "<html><head><meta charset='utf-8'>" + refresh + f"<title>{title}</title></head>"
        "<body style='font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'>"
        + body + "</body></html>"
    )

def _render_fig(fig: go.Figure, title: str, out_path: Path, auto_refresh_sec: int = 0) -> Path:
    div = plot(fig, include_plotlyjs="cdn", output_type="div")
    html = _wrap_html(title, div, auto_refresh_sec)
    out_path.write_text(html)
    return out_path

# ---------- Strategy (deadband + hysteresis) ----------
def simulate(
    df: pd.DataFrame,
    *,
    capacity_mwh: float = 10.0,
    efficiency_rt: float = 0.85,
    th: Thresholds = Thresholds(),
) -> Dict:
    if df.empty:
        return {
            "events": [],
            "profit": 0.0,
            "utilization_pct": 0.0,
            "series": pd.DataFrame(columns=[
                "timestamp", "lmp", "soc_mwh", "charge_mw", "discharge_mw"
            ]),
        }

    df = df.sort_values("timestamp").copy()

    # Assume 5-min cadence; at most 1C (full in/out in 1 hour)
    step_mwh = capacity_mwh / 12.0
    step_to_mw = 12.0  # MWh per 5-min -> MW

    soc = capacity_mwh * 0.5  # start mid-tank
    revenue = 0.0
    energy_in = 0.0   # MWh charged (before efficiency)
    energy_out = 0.0  # MWh discharged

    last_mode = "idle"
    events: List[Dict] = []

    charge_hard = th.charge_lmp - th.deadband
    discharge_hard = th.discharge_lmp + th.deadband

    # Series for plotting
    ts_list: List[pd.Timestamp] = []
    lmp_list: List[float] = []
    soc_list: List[float] = []
    ch_mw: List[float] = []
    dis_mw: List[float] = []

    for _, r in df.iterrows():
        p = float(r["lmp"])  # $/MWh
        mode = "idle"

        # Hard triggers (with deadband)
        if p >= discharge_hard and soc > (th.soc_min_pct / 100.0) * capacity_mwh:
            e = min(step_mwh, soc)  # discharge
            soc -= e
            revenue += e * p
            energy_out += e
            mode = "discharge"
            dis_mw.append(e * step_to_mw)
            ch_mw.append(0.0)

        elif p <= charge_hard and soc < capacity_mwh:
            e = min(step_mwh, capacity_mwh - soc)  # charge
            revenue -= e * p
            soc += e * efficiency_rt
            energy_in += e
            mode = "charge"
            ch_mw.append(e * step_to_mw)
            dis_mw.append(0.0)

        else:
            # Hysteresis — continue previous action if still favorable inside band
            if last_mode == "discharge" and p >= th.discharge_lmp and soc > (th.soc_min_pct / 100.0) * capacity_mwh:
                e = min(step_mwh, soc)
                soc -= e
                revenue += e * p
                energy_out += e
                mode = "discharge"
                dis_mw.append(e * step_to_mw)
                ch_mw.append(0.0)
            elif last_mode == "charge" and p <= th.charge_lmp and soc < capacity_mwh:
                e = min(step_mwh, capacity_mwh - soc)
                revenue -= e * p
                soc += e * efficiency_rt
                energy_in += e
                mode = "charge"
                ch_mw.append(e * step_to_mw)
                dis_mw.append(0.0)
            else:
                mode = "idle"
                ch_mw.append(0.0)
                dis_mw.append(0.0)

        if not events or mode != last_mode:
            events.append({
                "timestamp": r["timestamp"],
                "mode": mode,
                "price": p,
                "soc_mwh": soc,
            })
            last_mode = mode

        ts_list.append(r["timestamp"])
        lmp_list.append(p)
        soc_list.append(soc)

    # Utilization via equivalent full cycles
    eq_cycles = (energy_in + energy_out) / (2.0 * capacity_mwh)
    utilization_pct = min(100.0, 100.0 * eq_cycles / th.max_cycles_per_day)

    series = pd.DataFrame({
        "timestamp": ts_list,
        "lmp": lmp_list,
        "soc_mwh": soc_list,
        "charge_mw": ch_mw,
        "discharge_mw": dis_mw,
    })

    return {
        "events": events,
        "profit": revenue,
        "utilization_pct": utilization_pct,
        "series": series,
        "eq_cycles": eq_cycles,
        "energy_in_mwh": energy_in,
        "energy_out_mwh": energy_out,
    }

# ---------- Reporting ----------
def _node_path(out_dir: Path, node: str, ts: str) -> Path:
    if ts == "latest":
        out = out_dir / "latest"
        out.mkdir(parents=True, exist_ok=True)
        return out / f"{node}_dispatch.html"
    return out_dir / f"{node}_dispatch_{ts}.html"

def _multi_table_path(out_dir: Path, ts: str) -> Path:
    if ts == "latest":
        out = out_dir / "latest"
        out.mkdir(parents=True, exist_ok=True)
        return out / "multi_node_lmp.html"
    return out_dir / f"multi_node_lmp_{ts}.html"

def _multi_prices_path(out_dir: Path, ts: str) -> Path:
    if ts == "latest":
        out = out_dir / "latest"
        out.mkdir(parents=True, exist_ok=True)
        return out / "multi_node_prices.html"
    return out_dir / f"multi_node_prices_{ts}.html"

def plot_node(node: str, df: pd.DataFrame, res: Dict, th: Thresholds, out_dir: Path, ts: str, auto_refresh_sec: int) -> Path:
    path = _node_path(out_dir, node, ts)

    series = res.get("series", pd.DataFrame())
    fig = go.Figure()

    # LMP
    if not df.empty:
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["lmp"], name="LMP ($/MWh)", line=dict(color="#2563eb", width=2)))

    # Charge/Discharge bars (MW)
    if not series.empty:
        fig.add_trace(go.Bar(x=series["timestamp"], y=series["charge_mw"], name="Charge (MW)", marker_color="#f59e0b", opacity=0.35))
        fig.add_trace(go.Bar(x=series["timestamp"], y=-series["discharge_mw"], name="Discharge (MW)", marker_color="#ef4444", opacity=0.35))
        fig.add_trace(go.Scatter(x=series["timestamp"], y=series["soc_mwh"], name="SOC (MWh)", yaxis="y2", line=dict(color="#7c3aed", width=2, dash="dot")))

    # Thresholds
    fig.add_hline(y=th.charge_lmp, line_dash="dash", line_color="#16a34a", annotation_text="Charge TH")
    fig.add_hline(y=th.discharge_lmp, line_dash="dash", line_color="#ef4444", annotation_text="Discharge TH")

    subtitle = (
        f"EFC: {res.get('eq_cycles',0):.2f}  |  "
        f"Ein: {res.get('energy_in_mwh',0):.1f} MWh  |  "
        f"Eout: {res.get('energy_out_mwh',0):.1f} MWh  |  "
        f"Deadband: ${th.deadband:.0f}"
    )

    fig.update_layout(
        title={
            "text": (
                f"Only1 Power — {node} | Profit: ${res.get('profit',0):,.2f} "
                f"| Utilization: {res.get('utilization_pct',0):.1f}%"
                f"<br><sup>{subtitle}</sup>"
            ),
            "x": 0.01,
        },
        xaxis_title="Time (UTC)",
        yaxis=dict(title="LMP ($/MWh)", side="left"),
        yaxis2=dict(title="SOC (MWh)", overlaying="y", side="right", rangemode="tozero"),
        barmode="overlay",
        template="plotly_white",
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"),
        margin=dict(t=120),
    )

    return _render_fig(fig, f"Only1 — {node}", path, auto_refresh_sec)

def save_multi(results: Dict[str, Dict], out_dir: Path, ts: str, auto_refresh_sec: int) -> Path:
    path = _multi_table_path(out_dir, ts)

    tbl = pd.DataFrame([
        {"node": n, "profit": r.get("profit", 0.0), "util%": r.get("utilization_pct", 0.0)}
        for n, r in results.items()
    ])

    def money(x):
        try:
            return f"${x:,.2f}"
        except Exception:
            return x

    def pct(x):
        try:
            return f"{x:.1f}%"
        except Exception:
            return x

    table_html = tbl.to_html(index=False, formatters={"profit": money, "util%": pct})
    html = _wrap_html("Only1 Multi-Node", "<h2>Only1 Power — Multi-Node Summary</h2>" + table_html, auto_refresh_sec)
    path.write_text(html)
    return path

def save_multi_prices(prices: Dict[str, pd.DataFrame], out_dir: Path, th: Thresholds, ts: str, auto_refresh_sec: int) -> Path:
    path = _multi_prices_path(out_dir, ts)

    fig = go.Figure()
    palette = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0ea5e9"]
    for idx, (node, df) in enumerate(prices.items()):
        if df.empty:
            continue
        color = palette[idx % len(palette)]
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["lmp"], name=node, line=dict(color=color, width=2)))

    fig.add_hline(y=th.charge_lmp, line_dash="dash", line_color="#16a34a", annotation_text="Charge TH")
    fig.add_hline(y=th.discharge_lmp, line_dash="dash", line_color="#ef4444", annotation_text="Discharge TH")

    fig.update_layout(
        title={"text": "Only1 Power — Multi-Node LMPs", "x": 0.01},
        xaxis_title="Time (UTC)",
        yaxis_title="LMP ($/MWh)",
        height=420,
        template="plotly_white",
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"),
        margin=dict(t=80)
    )

    return _render_fig(fig, "Only1 — Multi-Node LMPs", path, auto_refresh_sec)

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Only1 — Run sim from local CSVs for a given date (no network)")
    ap.add_argument("--date", required=True, help="UTC date like 2025-08-09")
    ap.add_argument("--nodes", default="MPBBAC,MPBNCA,MPBPGE")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--reports-dir", default="reports")
    ap.add_argument("--capacity-mwh", type=float, default=10.0)
    ap.add_argument("--efficiency-rt", type=float, default=0.85)
    ap.add_argument("--charge-lmp", type=float, default=30.0)
    ap.add_argument("--discharge-lmp", type=float, default=60.0)
    ap.add_argument("--deadband", type=float, default=2.0)
    # auto-open default TRUE; allow disabling with --no-auto-open
    ap.add_argument("--auto-open", dest="auto_open", action="store_true", default=True,
                    help="Open all 5 charts after run (default ON)")
    ap.add_argument("--no-auto-open", dest="auto_open", action="store_false",
                    help="Disable auto-open for this run")
    # latest-only + auto-refresh
    ap.add_argument("--latest-only", action="store_true", help="Overwrite canonical 'latest' files (no archive)")
    ap.add_argument("--auto-refresh-sec", type=int, default=0, help="Inject auto-reload meta tag into HTML (seconds)")
    args = ap.parse_args()

    # One shared timestamp for all artifacts in this run (or 'latest')
    run_ts = "latest" if args.latest_only else datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Resolve nodes to SLAP names
    raw_nodes = [n.strip() for n in args.nodes.split(",") if n.strip()]
    nodes = [ALIAS_RTM.get(n, n) for n in raw_nodes]

    data_dir = Path(args.data_dir)
    reports_dir = Path(args.reports_dir)
    data_dir.mkdir(exist_ok=True)
    reports_dir.mkdir(exist_ok=True)

    th = Thresholds(
        charge_lmp=args.charge_lmp,
        discharge_lmp=args.discharge_lmp,
        deadband=args.deadband,
        soc_min_pct=5.0,
        max_cycles_per_day=1.5,
    )

    # Load CSVs
    all_prices: Dict[str, pd.DataFrame] = {}
    for node in nodes:
        try:
            df = load_prices_for_node(data_dir, node, args.date)
        except Exception as e:
            print(f"Warning: {node}: {e}")
            continue
        all_prices[node] = df
        print(f"Loaded {len(df)} rows for {node} from lmp_{node}_{args.date}.csv")

    if not all_prices:
        print("No CSVs found for that date. Exiting.")
        return

    # Simulate + report
    results: Dict[str, Dict] = {}
    node_paths: List[Path] = []
    for node, df in all_prices.items():
        res = simulate(df, capacity_mwh=args.capacity_mwh, efficiency_rt=args.efficiency_rt, th=th)
        results[node] = res
        node_report = plot_node(node, df, res, th, reports_dir, ts=run_ts, auto_refresh_sec=args.auto_refresh_sec)
        node_paths.append(node_report)
        print(f"Saved node report: {node_report}")

    multi = save_multi(results, reports_dir, run_ts, args.auto_refresh_sec)
    print(f"Saved multi-node chart: {multi}")

    multi_prices = save_multi_prices(all_prices, reports_dir, th, run_ts, args.auto_refresh_sec)
    print(f"Saved multi-node prices chart: {multi_prices}")

    # Summary CSV for downstream dashboards (includes run_ts)
    import csv
    summary_path = reports_dir / "last_run_summary.csv"
    with open(summary_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "node", "profit", "util_pct", "charge_lmp", "discharge_lmp", "deadband", "capacity_mwh", "efficiency_rt", "run_ts"])
        for n, r in results.items():
            w.writerow([
                args.date,
                n,
                r.get("profit", 0.0),
                r.get("utilization_pct", 0.0),
                args.charge_lmp,
                args.discharge_lmp,
                args.deadband,
                args.capacity_mwh,
                args.efficiency_rt,
                run_ts,
            ])
    print(f"Wrote summary CSV: {summary_path}")

    # Auto-open all five charts (default ON)
    if args.auto_open:
        import webbrowser
        to_open = [multi_prices, multi]
        for p in node_paths:
            to_open.append(p)
        for p in to_open:
            try:
                webbrowser.open(p.resolve().as_uri(), new=2)
            except Exception:
                pass

    print("\nProfit by Node:")
    for n, r in results.items():
        print(f"  {n}: ${r.get('profit', 0.0):.2f} | Util {r.get('utilization_pct', 0.0):.1f}%")

if __name__ == "__main__":
    main()
