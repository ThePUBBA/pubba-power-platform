from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta
from io import BytesIO
from typing import Optional
from zoneinfo import ZoneInfo
import zipfile

import pandas as pd
import requests


CAISO_OASIS_URL = "https://oasis.caiso.com/oasisapi/SingleZip"
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
UTC_TZ = ZoneInfo("UTC")
DEFAULT_TIMEOUT_SECONDS = 30

MARKET_RUN_IDS = {"DAM", "HASP", "RTPD", "RTM"}


class CaisoOasisError(RuntimeError):
    """Raised when CAISO OASIS cannot return parseable LMP data."""


def fetch_lmp_data(
    location: str = "TH_NP15_GEN-APND",
    market: str = "RTM",
    date: Optional[str] = None,
    days: int = 1,
) -> pd.DataFrame:
    """Fetch CAISO interval LMP data and return records as a pandas DataFrame."""

    location = _validate_location(location)
    market_run_id = _normalize_market(market)
    if not isinstance(days, int) or not 1 <= days <= 31:
        raise ValueError("days must be an integer between 1 and 31")
    start, end = _date_window(date, days=days)
    params = _build_oasis_params(location, market_run_id, start, end)
    response_content = _request_oasis(params)
    return _parse_oasis_zip(response_content)


def _validate_location(location: str) -> str:
    if not location or not location.strip():
        raise ValueError("location must be a non-empty CAISO node name")
    return location.strip()


def _normalize_market(market: str) -> str:
    market_run_id = (market or "").strip().upper()
    if market_run_id == "LMP":
        market_run_id = "RTM"

    if market_run_id not in MARKET_RUN_IDS:
        valid = ", ".join(sorted(MARKET_RUN_IDS | {"LMP"}))
        raise ValueError(f"market must be one of: {valid}")
    return market_run_id


def _date_window(
    date_value: Optional[str], *, days: int = 1,
) -> tuple[datetime, datetime]:
    if date_value:
        try:
            trade_date = date_type.fromisoformat(date_value)
        except ValueError as exc:
            raise ValueError("date must use ISO format YYYY-MM-DD") from exc
    else:
        trade_date = datetime.now(PACIFIC_TZ).date()

    start = datetime.combine(trade_date, time.min, tzinfo=PACIFIC_TZ)
    end = start + timedelta(days=days)
    return start.astimezone(UTC_TZ), end.astimezone(UTC_TZ)


def _build_oasis_params(
    location: str,
    market_run_id: str,
    start: datetime,
    end: datetime,
) -> dict[str, str]:
    return {
        "queryname": "PRC_INTVL_LMP",
        "startdatetime": _format_oasis_datetime(start),
        "enddatetime": _format_oasis_datetime(end),
        "version": "2",
        "resultformat": "6",
        "market_run_id": market_run_id,
        "node": location,
    }


def _format_oasis_datetime(value: datetime) -> str:
    return value.astimezone(UTC_TZ).strftime("%Y%m%dT%H:%M-0000")


def _request_oasis(
    params: dict[str, str],
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    try:
        response = requests.get(CAISO_OASIS_URL, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise CaisoOasisError("CAISO OASIS request timed out") from exc
    except requests.RequestException as exc:
        raise CaisoOasisError(f"CAISO OASIS request failed: {exc}") from exc

    if not response.content:
        raise CaisoOasisError("CAISO OASIS returned an empty response")

    return response.content


def _parse_oasis_zip(content: bytes) -> pd.DataFrame:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            csv_names = [
                name for name in archive.namelist() if name.lower().endswith(".csv")
            ]
            if not csv_names:
                _raise_oasis_message_error(archive)

            with archive.open(csv_names[0]) as csv_file:
                df = pd.read_csv(csv_file)
    except zipfile.BadZipFile as exc:
        raise CaisoOasisError("CAISO OASIS returned a malformed ZIP response") from exc
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise CaisoOasisError("CAISO OASIS returned a malformed CSV response") from exc

    if df.empty:
        raise CaisoOasisError("CAISO OASIS returned no LMP rows")

    return _normalize_lmp_frame(df)


def _raise_oasis_message_error(archive: zipfile.ZipFile) -> None:
    text_names = [
        name
        for name in archive.namelist()
        if name.lower().endswith((".xml", ".txt"))
    ]

    for name in text_names:
        try:
            message = archive.read(name).decode("utf-8", errors="replace").strip()
        except OSError:
            continue
        if message:
            raise CaisoOasisError(f"CAISO OASIS returned an error response: {message}")

    raise CaisoOasisError("CAISO OASIS response ZIP did not include a CSV file")


def _normalize_lmp_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_normalize_column_name(column) for column in df.columns]
    df = _select_lmp_price_rows(df)

    for column in ("interval_start_gmt", "interval_end_gmt"):
        if column in df.columns:
            values = pd.to_datetime(df[column], utc=True, errors="coerce")
            if values.isna().any():
                raise CaisoOasisError(
                    f"CAISO OASIS returned invalid timestamps in {column}"
                )
            df[column] = values.dt.tz_convert(PACIFIC_TZ).dt.strftime(
                "%Y-%m-%dT%H:%M:%S%z"
            )

    if "interval_start_gmt" in df.columns:
        df["timestamp"] = df["interval_start_gmt"]

    numeric_columns = (
        "opr_hr",
        "opr_interval",
        "mw",
        "lmp_prc",
        "lmp_energy_prc",
        "lmp_cong_prc",
        "lmp_loss_prc",
        "lmp_ghg_prc",
    )
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    return df.where(pd.notna(df), None)


def _select_lmp_price_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize CAISO's long-form price components to the total LMP price."""

    if "xml_data_item" in df.columns:
        data_items = df["xml_data_item"].astype("string").str.strip().str.upper()
        df = df.loc[data_items == "LMP_PRC"].copy()
        if df.empty:
            raise CaisoOasisError(
                "CAISO OASIS response did not include XML_DATA_ITEM=LMP_PRC rows"
            )

    if "lmp_prc" not in df.columns and "value" in df.columns:
        df["lmp_prc"] = df["value"]

    if "lmp_prc" not in df.columns:
        raise CaisoOasisError(
            "CAISO OASIS response did not include an LMP price column"
        )

    return df


def _normalize_column_name(column: str) -> str:
    normalized = column.strip().lower()
    aliases = {
        "intervalstarttime_gmt": "interval_start_gmt",
        "intervalendtime_gmt": "interval_end_gmt",
        "nodeid": "node_id",
        "nodeid_xml": "node_id_xml",
        "marketrunid": "market_run_id",
        "lmptype": "lmp_type",
        "lmpprice": "lmp_prc",
    }
    return aliases.get(normalized, normalized)
