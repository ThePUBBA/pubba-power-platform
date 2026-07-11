from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


PRICE_COLUMN = "lmp_prc"
START_COLUMN = "interval_start_gmt"
END_COLUMN = "interval_end_gmt"


class ArbitrageAnalysisError(ValueError):
    """Raised when LMP data cannot support an arbitrage analysis."""


@dataclass(frozen=True)
class PriceWindow:
    start_timestamp: str
    end_timestamp: str
    average_price: float
    prices: list[dict[str, float | str]]


def analyze_lmp_arbitrage(
    lmp_data: pd.DataFrame,
    duration_hours: float = 8,
    round_trip_efficiency: float = 0.80,
) -> dict:
    """Find simple charge/discharge windows for a storage asset.

    The first version chooses the lowest average contiguous price window for
    charging and the highest average non-overlapping contiguous price window
    for discharging.
    """

    _validate_inputs(duration_hours, round_trip_efficiency)
    frame = _prepare_lmp_frame(lmp_data)
    interval_hours = _infer_interval_hours(frame)
    intervals_per_window = round(duration_hours / interval_hours)

    if intervals_per_window < 1:
        raise ArbitrageAnalysisError("duration_hours is shorter than one interval")
    if len(frame) < intervals_per_window * 2:
        raise ArbitrageAnalysisError(
            "not enough LMP intervals for non-overlapping charge and discharge windows"
        )

    charge_start = _best_window_start(frame[PRICE_COLUMN], intervals_per_window, "min")
    discharge_start = _best_window_start(
        frame[PRICE_COLUMN],
        intervals_per_window,
        "max",
        excluded_indexes=set(range(charge_start, charge_start + intervals_per_window)),
    )

    charge_window = _build_window(frame, charge_start, intervals_per_window)
    discharge_window = _build_window(frame, discharge_start, intervals_per_window)
    gross_spread = discharge_window.average_price - charge_window.average_price
    efficiency_adjusted_spread = (
        discharge_window.average_price * round_trip_efficiency
    ) - charge_window.average_price
    estimated_margin = discharge_window.average_price - (
        charge_window.average_price / round_trip_efficiency
    )

    return {
        "duration_hours": duration_hours,
        "round_trip_efficiency": round_trip_efficiency,
        "interval_hours": interval_hours,
        "intervals_per_window": intervals_per_window,
        "charging_window": _window_to_dict(charge_window),
        "discharging_window": _window_to_dict(discharge_window),
        "average_charging_price": charge_window.average_price,
        "average_discharging_price": discharge_window.average_price,
        "gross_price_spread": gross_spread,
        "efficiency_adjusted_spread": efficiency_adjusted_spread,
        "estimated_gross_margin_per_mwh_discharged": estimated_margin,
        "assumptions": {
            "price_column": PRICE_COLUMN,
            "window_selection": "lowest average charge window and highest average non-overlapping discharge window",
            "estimated_margin_per_mwh_discharged": "average_discharging_price - average_charging_price / round_trip_efficiency",
        },
    }


def _validate_inputs(duration_hours: float, round_trip_efficiency: float) -> None:
    if duration_hours <= 0:
        raise ArbitrageAnalysisError("duration_hours must be positive")
    if round_trip_efficiency <= 0 or round_trip_efficiency > 1:
        raise ArbitrageAnalysisError(
            "round_trip_efficiency must be greater than 0 and less than or equal to 1"
        )


def _prepare_lmp_frame(lmp_data: pd.DataFrame) -> pd.DataFrame:
    required_columns = {PRICE_COLUMN, START_COLUMN, END_COLUMN}
    missing = sorted(required_columns - set(lmp_data.columns))
    if missing:
        raise ArbitrageAnalysisError(
            f"LMP data is missing required columns: {', '.join(missing)}"
        )

    frame = lmp_data[[START_COLUMN, END_COLUMN, PRICE_COLUMN]].copy()
    frame[START_COLUMN] = pd.to_datetime(frame[START_COLUMN], utc=True, errors="coerce")
    frame[END_COLUMN] = pd.to_datetime(frame[END_COLUMN], utc=True, errors="coerce")
    frame[PRICE_COLUMN] = pd.to_numeric(frame[PRICE_COLUMN], errors="coerce")
    frame = frame.dropna(subset=[START_COLUMN, END_COLUMN, PRICE_COLUMN])
    frame = frame.sort_values(START_COLUMN).reset_index(drop=True)

    if frame.empty:
        raise ArbitrageAnalysisError("LMP data does not include usable price intervals")

    return frame


def _infer_interval_hours(frame: pd.DataFrame) -> float:
    interval_lengths = (
        frame[END_COLUMN] - frame[START_COLUMN]
    ).dt.total_seconds() / 3600
    positive_lengths = interval_lengths[interval_lengths > 0]
    if positive_lengths.empty:
        raise ArbitrageAnalysisError("LMP intervals must have positive duration")

    return float(positive_lengths.median())


def _best_window_start(
    prices: pd.Series,
    window_size: int,
    mode: str,
    excluded_indexes: set[int] | None = None,
) -> int:
    excluded_indexes = excluded_indexes or set()
    candidates: list[tuple[float, int]] = []
    for start in range(0, len(prices) - window_size + 1):
        indexes = set(range(start, start + window_size))
        if indexes & excluded_indexes:
            continue
        average_price = float(prices.iloc[start : start + window_size].mean())
        candidates.append((average_price, start))

    if not candidates:
        raise ArbitrageAnalysisError(
            "not enough non-overlapping intervals for charge and discharge windows"
        )

    return min(candidates)[1] if mode == "min" else max(candidates)[1]


def _build_window(frame: pd.DataFrame, start: int, window_size: int) -> PriceWindow:
    window = frame.iloc[start : start + window_size]
    prices = [
        {
            "timestamp": _to_json_timestamp(row[START_COLUMN]),
            "price": float(row[PRICE_COLUMN]),
        }
        for _, row in window.iterrows()
    ]

    return PriceWindow(
        start_timestamp=_to_json_timestamp(window.iloc[0][START_COLUMN]),
        end_timestamp=_to_json_timestamp(window.iloc[-1][END_COLUMN]),
        average_price=float(window[PRICE_COLUMN].mean()),
        prices=prices,
    )


def _window_to_dict(window: PriceWindow) -> dict:
    return {
        "start_timestamp": window.start_timestamp,
        "end_timestamp": window.end_timestamp,
        "average_price": window.average_price,
        "prices": window.prices,
    }


def _to_json_timestamp(value: pd.Timestamp) -> str:
    return value.isoformat()
