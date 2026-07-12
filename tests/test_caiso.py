from io import BytesIO
import zipfile

import pandas as pd
import pytest
import requests

import caiso
from caiso import CaisoOasisError, fetch_lmp_data


class MockResponse:
    def __init__(self, content=b"", status_error=None):
        self.content = content
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error


def zipped_file(name, content):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def test_fetch_lmp_data_uses_oasis_and_returns_normalized_dataframe(monkeypatch):
    csv = "\n".join(
        [
            "INTERVALSTARTTIME_GMT,INTERVALENDTIME_GMT,OPR_DT,OPR_HR,OPR_INTERVAL,NODE_ID_XML,MARKET_RUN_ID,LMP_TYPE,LMP_PRC",
            "2025-04-01T07:00:00-00:00,2025-04-01T07:05:00-00:00,2025-04-01,1,1,TH_NP15_GEN-APND,RTM,LMP,22.42",
        ]
    )
    captured = {}

    def mock_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return MockResponse(zipped_file("lmp.csv", csv))

    monkeypatch.setattr(caiso.requests, "get", mock_get)

    df = fetch_lmp_data(
        location="TH_NP15_GEN-APND",
        market="RTM",
        date="2025-04-01",
    )

    assert isinstance(df, pd.DataFrame)
    assert captured["url"] == caiso.CAISO_OASIS_URL
    assert captured["timeout"] == caiso.DEFAULT_TIMEOUT_SECONDS
    assert captured["params"] == {
        "queryname": "PRC_INTVL_LMP",
        "startdatetime": "20250401T07:00-0000",
        "enddatetime": "20250402T07:00-0000",
        "version": "2",
        "resultformat": "6",
        "market_run_id": "RTM",
        "node": "TH_NP15_GEN-APND",
    }
    record = df.to_dict(orient="records")[0]
    assert record["interval_start_gmt"] == "2025-04-01T00:00:00-0700"
    assert record["interval_end_gmt"] == "2025-04-01T00:05:00-0700"
    assert record["timestamp"] == "2025-04-01T00:00:00-0700"
    assert record["lmp_prc"] == 22.42


def test_fetch_lmp_data_normalizes_live_long_form_caiso_columns(monkeypatch):
    csv = "\n".join(
        [
            "INTERVALSTARTTIME_GMT,INTERVALENDTIME_GMT,OPR_DT,OPR_HR,NODE_ID_XML,NODE_ID,NODE,MARKET_RUN_ID,LMP_TYPE,XML_DATA_ITEM,PNODE_RESMRID,GRP_TYPE,POS,VALUE,OPR_INTERVAL,GROUP",
            "2025-07-18T07:00:00-00:00,2025-07-18T07:05:00-00:00,2025-07-18,01,TH_NP15_GEN-APND,TH_NP15_GEN-APND,TH_NP15_GEN-APND,RTM,MCC,LMP_CONG_PRC,TH_NP15_GEN-APND,ALL_APNODES,0,-1.68082,1,1",
            "2025-07-18T07:00:00-00:00,2025-07-18T07:05:00-00:00,2025-07-18,01,TH_NP15_GEN-APND,TH_NP15_GEN-APND,TH_NP15_GEN-APND,RTM,MCE,LMP_ENE_PRC,TH_NP15_GEN-APND,ALL_APNODES,0,48.94640,1,2",
            "2025-07-18T07:00:00-00:00,2025-07-18T07:05:00-00:00,2025-07-18,01,TH_NP15_GEN-APND,TH_NP15_GEN-APND,TH_NP15_GEN-APND,RTM,LMP,LMP_PRC,TH_NP15_GEN-APND,ALL_APNODES,0,50.48609,1,5",
        ]
    )

    monkeypatch.setattr(
        caiso.requests,
        "get",
        lambda url, params, timeout: MockResponse(zipped_file("live_lmp.csv", csv)),
    )

    df = fetch_lmp_data(
        location="TH_NP15_GEN-APND",
        market="RTM",
        date="2025-07-18",
    )

    assert len(df) == 1
    record = df.to_dict(orient="records")[0]
    assert record["xml_data_item"] == "LMP_PRC"
    assert record["lmp_type"] == "LMP"
    assert record["timestamp"] == "2025-07-18T00:00:00-0700"
    assert record["lmp_prc"] == 50.48609


def test_normalization_handles_column_names_case_insensitively():
    df = pd.DataFrame(
        {
            "IntervalStartTime_GMT": ["2025-07-18T07:00:00-00:00"],
            "IntervalEndTime_GMT": ["2025-07-18T07:05:00-00:00"],
            "Xml_Data_Item": ["lmp_prc"],
            "Value": ["50.48609"],
        }
    )

    normalized = caiso._normalize_lmp_frame(df)

    assert normalized.iloc[0]["lmp_prc"] == 50.48609
    assert normalized.iloc[0]["timestamp"] == "2025-07-18T00:00:00-0700"


def test_fetch_lmp_data_keeps_legacy_lmp_market_alias(monkeypatch):
    csv = "\n".join(
        [
            "INTERVALSTARTTIME_GMT,INTERVALENDTIME_GMT,LMP_PRC",
            "2025-04-01T07:00:00-00:00,2025-04-01T07:05:00-00:00,22.42",
        ]
    )
    captured = {}

    def mock_get(url, params, timeout):
        captured["market"] = params["market_run_id"]
        return MockResponse(zipped_file("lmp.csv", csv))

    monkeypatch.setattr(caiso.requests, "get", mock_get)

    fetch_lmp_data(market="LMP", date="2025-04-01")

    assert captured["market"] == "RTM"


def test_fetch_lmp_data_rejects_invalid_date():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        fetch_lmp_data(date="04/01/2025")


def test_fetch_lmp_data_rejects_invalid_market():
    with pytest.raises(ValueError, match="market must be one of"):
        fetch_lmp_data(market="BAD", date="2025-04-01")


def test_fetch_lmp_data_wraps_http_errors(monkeypatch):
    def mock_get(url, params, timeout):
        return MockResponse(
            b"upstream error",
            requests.HTTPError("500 Server Error"),
        )

    monkeypatch.setattr(caiso.requests, "get", mock_get)

    with pytest.raises(CaisoOasisError, match="request failed"):
        fetch_lmp_data(date="2025-04-01")


def test_fetch_lmp_data_wraps_timeouts(monkeypatch):
    def mock_get(url, params, timeout):
        raise requests.Timeout("slow")

    monkeypatch.setattr(caiso.requests, "get", mock_get)

    with pytest.raises(CaisoOasisError, match="timed out"):
        fetch_lmp_data(date="2025-04-01")


def test_fetch_lmp_data_rejects_malformed_zip(monkeypatch):
    def mock_get(url, params, timeout):
        return MockResponse(b"not a zip")

    monkeypatch.setattr(caiso.requests, "get", mock_get)

    with pytest.raises(CaisoOasisError, match="malformed ZIP"):
        fetch_lmp_data(date="2025-04-01")


def test_fetch_lmp_data_reports_oasis_error_payload(monkeypatch):
    def mock_get(url, params, timeout):
        return MockResponse(zipped_file("error.xml", "<error>No data found</error>"))

    monkeypatch.setattr(caiso.requests, "get", mock_get)

    with pytest.raises(CaisoOasisError, match="No data found"):
        fetch_lmp_data(date="2025-04-01")


def test_fetch_lmp_data_rejects_invalid_timestamps(monkeypatch):
    csv = "\n".join(
        [
            "INTERVALSTARTTIME_GMT,INTERVALENDTIME_GMT,LMP_PRC",
            "bad-date,2025-04-01T07:05:00-00:00,22.42",
        ]
    )

    def mock_get(url, params, timeout):
        return MockResponse(zipped_file("lmp.csv", csv))

    monkeypatch.setattr(caiso.requests, "get", mock_get)

    with pytest.raises(CaisoOasisError, match="invalid timestamps"):
        fetch_lmp_data(date="2025-04-01")
