#!/usr/bin/env python3
"""
Only1 Power — oasis_client.py (robust, with retry + bulk DAM)
- RTM 5-min: PRC_INTVL_LMP (version=2) -> try node=...
- DAM hourly: PRC_LMP (version=12) -> bulk via grp_type=ALL once/day, then filter
- Retries 429 with exponential backoff
Set OASIS_DEBUG=1 for request/columns logging.
"""
from __future__ import annotations
import io, os, re, time, zipfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Iterable, List
import pandas as pd
import requests

OASIS_BASE = os.getenv("OASIS_BASE", "https://oasis.caiso.com/oasisapi")
OASIS_DEBUG = os.getenv("OASIS_DEBUG", "0") == "1"

class OasisError(Exception): ...

@dataclass
class OasisClient:
    session: Optional[requests.Session] = None
    base: Optional[str] = None
    timeout: int = 60
    max_retries: int = 5

    def __post_init__(self):
        self.s = self.session or requests.Session()
        self.base = self.base or OASIS_BASE

    @staticmethod
    def _fmt(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M-0000")

    def _fetch(self, queryname: str, params: Dict[str, Any]) -> pd.DataFrame:
        url = f"{self.base}/SingleZip"
        p = {"queryname": queryname, "resultformat": "6"}
        p.update(params)

        attempt, backoff = 0, 2
        while True:
            if OASIS_DEBUG: print("DEBUG OASIS REQUEST:", url, p)
            r = self.s.get(url, params=p, timeout=self.timeout)
            if r.status_code == 429 and attempt < self.max_retries:
                wait = int(r.headers.get("Retry-After", backoff))
                if OASIS_DEBUG: print(f"DEBUG 429: sleeping {wait}s (attempt {attempt+1})")
                time.sleep(wait)
                attempt += 1
                backoff = min(backoff * 2, 30)
                continue
            r.raise_for_status()
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csvs:
                return pd.DataFrame()
            with zf.open(csvs[0]) as f:
                df = pd.read_csv(f)
            if OASIS_DEBUG:
                print("DEBUG OASIS COLUMNS:", df.columns.tolist(), "ROWS:", len(df))
            return df

    @staticmethod
    def _pick_col(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
        u = {c.upper(): c for c in df.columns}
        for want in candidates:
            for k, v in u.items():
                if want in k:
                    return v
        return None

    @staticmethod
    def _filter_node(df: pd.DataFrame, node: str) -> pd.DataFrame:
        cand = [c for c in df.columns if any(x in c.upper() for x in ("NODE", "PNODE", "APNODE"))]
        for col in cand:
            sub = df[df[col].astype(str).str.upper() == node.upper()]
            if not sub.empty:
                return sub
        return pd.DataFrame(columns=df.columns)

    # ---- RTM 5-minute LMP (direct) ----
    def rt5m_lmp(self, node: str, start: datetime, end: datetime) -> pd.DataFrame:
        df = self._fetch("PRC_INTVL_LMP", {
            "startdatetime": self._fmt(start),
            "enddatetime": self._fmt(end),
            "market_run_id": "RTM",
            "version": "2",
            "node": node,
        })
        if df.empty:
            return pd.DataFrame(columns=["timestamp","node","lmp"])
        ts = self._pick_col(df, ["INTERVALSTARTTIME", "STARTTIME_GMT"])
        lmp = self._pick_col(df, ["LMP_PRC"])
        if not (ts and lmp):
            return pd.DataFrame(columns=["timestamp","node","lmp"])
        out = pd.DataFrame({
            "timestamp": pd.to_datetime(df[ts], utc=True),
            "node": node,
            "lmp": pd.to_numeric(df[lmp], errors="coerce"),
        }).dropna(subset=["timestamp","lmp"]).sort_values("timestamp").reset_index(drop=True)
        return out.drop_duplicates(subset=["timestamp","node"])

    # ---- DAM hourly LMP (bulk once/day) ----
    def dam_lmp_bulk(self, trade_day_start_utc: datetime, nodes: List[str]) -> Dict[str, pd.DataFrame]:
        start = trade_day_start_utc
        end = start + timedelta(days=1)
        # One call for ALL, then filter locally
        df = self._fetch("PRC_LMP", {
            "startdatetime": self._fmt(start),
            "enddatetime": self._fmt(end),
            "market_run_id": "DAM",
            "version": "12",
            "grp_type": "ALL_APNODES",
        })
        if df.empty:
            return {n: pd.DataFrame(columns=["timestamp","node","lmp"]) for n in nodes}

        ts = self._pick_col(df, ["INTERVALSTARTTIME", "STARTTIME_GMT"])
        lmp = self._pick_col(df, ["LMP_PRC"])
        node_col = self._pick_col(df, ["PNODE", "APNODE", "NODE"])
        if not (ts and lmp and node_col):
            return {n: pd.DataFrame(columns=["timestamp","node","lmp"]) for n in nodes}

        tidy = pd.DataFrame({
            "timestamp": pd.to_datetime(df[ts], utc=True),
            "node": df[node_col].astype(str),
            "lmp": pd.to_numeric(df[lmp], errors="coerce"),
        }).dropna(subset=["timestamp","lmp"]).sort_values(["node","timestamp"]).reset_index(drop=True)

        out: Dict[str, pd.DataFrame] = {}
        for n in nodes:
            sub = tidy[tidy["node"].str.upper() == n.upper()].copy()
            out[n] = sub.drop_duplicates(subset=["timestamp","node"])
        return out
