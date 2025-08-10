import os, glob, csv
from datetime import datetime
from typing import Dict, List, Tuple
import plotly.graph_objs as go
from plotly.offline import plot

ROOT_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(ROOT_DIR, "data")
REPORT_DIR = os.path.join(ROOT_DIR, "reports")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# Auto-discover data/lmp_<NODE>_<DATE>.csv
NODE_FILES: Dict[str, str] = {}
for path in sorted(glob.glob(os.path.join(DATA_DIR, "lmp_*.csv"))):
    fname = os.path.basename(path)
    parts = fname.split("_")
    node = parts[1] if len(parts) >= 3 else fname
    NODE_FILES[node] = path  # full path

print("📂 Found CSVs:")
for node, full_path in NODE_FILES.items():
    print(f"  {node}: {full_path}")

# Params (5‑min timestep)
CAPACITY_MWH = 5.0
POWER_MW = 1.0
ROUND_TRIP_EFF = 0.85
CHARGE_TH = 30.0
DISCHARGE_TH = 60.0

def load_lmp_csv(path: str) -> Tuple[List[datetime], List[float]]:
    times: List[datetime] = []
    prices: List[float] = []
    with open(path, "r", newline="") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            times.append(datetime.fromisoformat(row["Time"]))
            prices.append(float(row["LMP"]))
    return times, prices

def simulate_5min(prices: List[float],
                  capacity_mwh=CAPACITY_MWH, power_mw=POWER_MW,
                  rte=ROUND_TRIP_EFF, charge_th=CHARGE_TH, discharge_th=DISCHARGE_TH):
    dt = 5/60.0
    eta_c = rte ** 0.5
    eta_d = rte ** 0.5
    soc = 0.0
    soc_series, charge_mw, discharge_mw = [], [], []
    profit = 0.0

    for p in prices:
        p = float(p); c_mw = d_mw = 0.0
        if p <= charge_th and soc < capacity_mwh:
            market_e = power_mw * dt
            headroom = capacity_mwh - soc
            delta_soc_full = market_e * eta_c
            if delta_soc_full > headroom:
                market_e = headroom / eta_c
            c_mw = market_e / dt
            soc += market_e * eta_c
            profit -= p * market_e
        elif p >= discharge_th and soc > 0:
            internal_e = min(power_mw * dt, soc)
            delivered = internal_e * eta_d
            d_mw = delivered / dt
            soc -= internal_e
            profit += p * delivered
        soc_series.append(soc); charge_mw.append(c_mw); discharge_mw.append(d_mw)

    avg_abs_power = (sum(charge_mw) + sum(discharge_mw)) / len(prices) if prices else 0.0
    utilization = avg_abs_power / power_mw if power_mw else 0.0
    return soc_series, charge_mw, discharge_mw, profit, utilization

def plot_node_report(node, times, prices, soc, charges, discharges, profit, utilization):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=times, y=prices, name="LMP ($/MWh)", line=dict(color="#2563EB")))
    fig.add_trace(go.Scatter(x=times, y=soc, name="SOC (MWh)", yaxis="y2", line=dict(color="#7C3AED", dash="dot")))
    fig.add_trace(go.Bar(x=times, y=charges, name="Charge (MW)", marker_color="#F59E0B", opacity=0.45))
    fig.add_trace(go.Bar(x=times, y=discharges, name="Discharge (MW)", marker_color="#DC2626", opacity=0.45))
    fig.add_hline(y=CHARGE_TH, line=dict(color="#10B981", dash="dash"), annotation_text="Charge TH", annotation_position="top left")
    fig.add_hline(y=DISCHARGE_TH, line=dict(color="#EF4444", dash="dash"), annotation_text="Discharge TH", annotation_position="bottom left")

    fig.update_layout(
        title=f"Only1 Power — {node} Dispatch | Profit: ${profit:,.2f} | Utilization: {utilization:.0%}",
        xaxis_title="Time",
        yaxis=dict(title="LMP ($/MWh)"),
        yaxis2=dict(title="SOC (MWh)", overlaying="y", side="right"),
        barmode="overlay",
        template="plotly_white",
        legend=dict(orientation="h", y=-0.25),
        margin=dict(l=60, r=60, t=70, b=80)
    )
    # Single footer brand (no duplicate at top)
    fig.add_annotation(text="Only1 Power · only1power.com", xref="paper", yref="paper",
                       x=0.0, y=-0.22, showarrow=False, font=dict(size=12, color="#6B7280"))

    out_path = os.path.join(REPORT_DIR, f"{node}_dispatch_{datetime.now().strftime('%Y%m%d_%H%M')}.html")
    plot(fig, filename=out_path, auto_open=False)
    return out_path

def plot_multi_node(prices_by_node: Dict[str, List[float]], times: List[datetime]):
    fig = go.Figure()
    for node, series in prices_by_node.items():
        fig.add_trace(go.Scatter(x=times, y=series, mode="lines", name=node))
    fig.add_hline(y=CHARGE_TH, line=dict(color="#10B981", dash="dash"))
    fig.add_hline(y=DISCHARGE_TH, line=dict(color="#EF4444", dash="dash"))
    fig.update_layout(title="CAISO Multi‑Node LMP Comparison", xaxis_title="Time",
                      yaxis_title="LMP ($/MWh)", template="plotly_white",
                      legend=dict(orientation="h", y=-0.2))
    out_path = os.path.join(REPORT_DIR, f"multi_node_lmp_{datetime.now().strftime('%Y%m%d_%H%M')}.html")
    plot(fig, filename=out_path, auto_open=False)
    return out_path

def main():
    if not NODE_FILES:
        print("⚠️  No CSVs found in ./data")
        return
    multi_prices: Dict[str, List[float]] = {}
    base_times: List[datetime] = []
    profit_table: List[Tuple[str, float]] = []
    for node, path in NODE_FILES.items():
        if not os.path.exists(path):
            print(f"⚠️  Skipping {node}: not found -> {path}")
            continue
        times, prices = load_lmp_csv(path)
        if not base_times: base_times = times
        soc, ch, dis, profit, util = simulate_5min(prices)
        out = plot_node_report(node, times, prices, soc, ch, dis, profit, util)
        print(f"✅ Saved node report: {out}")
        profit_table.append((node, round(profit,2)))
        multi_prices[node] = prices
    if multi_prices and base_times:
        out = plot_multi_node(multi_prices, base_times)
        print(f"✅ Saved multi‑node chart: {out}")
    if profit_table:
        print("\n📊 Profit by Node:")
        for n,p in profit_table:
            print(f"  {n}: ${p:,.2f}")

if __name__ == "__main__":
    main()
