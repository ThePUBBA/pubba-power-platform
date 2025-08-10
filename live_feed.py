from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import pandas as pd

class DataSource:
    def prices(self, node: str, start: datetime, end: datetime) -> pd.DataFrame:
        raise NotImplementedError

@dataclass
class CSVSource(DataSource):
    data_dir: Path
    def prices(self, node: str, start: datetime, end: datetime) -> pd.DataFrame:
        # expects data/lmp_<NODE>_YYYY-MM-DD.csv with columns: timestamp,lmp
        files = sorted(self.data_dir.glob(f"lmp_{node}_*.csv"))
        dfs = []
        for p in files:
            try:
                df = pd.read_csv(p, parse_dates=["timestamp"])
                df["node"] = node
                dfs.append(df)
            except Exception:
                pass
        if not dfs:
            return pd.DataFrame(columns=["timestamp","node","lmp"])
        df = pd.concat(dfs)
        df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
        return df.sort_values("timestamp").reset_index(drop=True)

@dataclass
class OasisSource(DataSource):
    client: "OasisClient"
    def prices(self, node: str, start: datetime, end: datetime) -> pd.DataFrame:
        return self.client.rt5m_lmp(node=node, start=start, end=end)

@dataclass
class FallbackSource(DataSource):
    primary: DataSource
    backup: DataSource
    def prices(self, node: str, start: datetime, end: datetime) -> pd.DataFrame:
        try:
            df = self.primary.prices(node, start, end)
            if len(df): return df
        except Exception:
            pass
        return self.backup.prices(node, start, end)
