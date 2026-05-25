"""OKXClient 单元测试 — 不依赖网络。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from investment.data.okx_client import CANDLES_COLS, OKXClient, VALID_BARS

SAMPLE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "samples" / "okx_response_sample.json"
)


@pytest.fixture
def sample_payload() -> dict:
    with open(SAMPLE_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---- _parse_candles ----

def test_parse_returns_ascending_ts(sample_payload):
    df = OKXClient._parse_candles(sample_payload["data"])
    assert len(df) == 3
    assert list(df.columns) == CANDLES_COLS
    assert df["ts"].is_monotonic_increasing
    assert df["ts"].iloc[0] == pd.Timestamp("2024-05-23 16:00:00", tz="UTC")


def test_parse_dtypes(sample_payload):
    df = OKXClient._parse_candles(sample_payload["data"])
    for col in ["open", "high", "low", "close", "vol", "vol_ccy", "vol_ccy_quote"]:
        assert df[col].dtype == float, f"{col} should be float"
    assert df["confirm"].dtype == bool


def test_parse_confirm_string_to_bool(sample_payload):
    df = OKXClient._parse_candles(sample_payload["data"])
    # ts-asc order: confirm = 1, 1, 0
    assert df["confirm"].tolist() == [True, True, False]


def test_parse_empty_input():
    df = OKXClient._parse_candles([])
    assert df.empty
    assert list(df.columns) == CANDLES_COLS


def test_parse_legacy_8_columns_fills_vol_ccy_quote():
    raw = [
        ["1716480000000", "67800.0", "67900.0", "67750.0", "67890.0",
         "1234.5", "83792000", "1"]
    ]
    df = OKXClient._parse_candles(raw)
    assert len(df) == 1
    assert df["vol_ccy"].iloc[0] == df["vol_ccy_quote"].iloc[0] == 83792000.0


# ---- _validate_bar ----

@pytest.mark.parametrize("bar", ["1m", "5m", "15m", "1H", "4H", "1D"])
def test_validate_bar_accepts_valid(bar):
    OKXClient._validate_bar(bar)


@pytest.mark.parametrize("bad", ["1h", "1d", "60m", "1hour", ""])
def test_validate_bar_rejects_invalid(bad):
    with pytest.raises(ValueError, match="非法 bar"):
        OKXClient._validate_bar(bad)


def test_VALID_BARS_contains_common():
    for bar in ["1m", "5m", "15m", "30m", "1H", "4H", "1D"]:
        assert bar in VALID_BARS


# ---- fetch_candles param validation ----

def test_fetch_candles_limit_out_of_range():
    client = OKXClient()
    with pytest.raises(ValueError, match="limit"):
        client.fetch_candles("BTC-USDT", "1H", limit=0)
    with pytest.raises(ValueError, match="limit"):
        client.fetch_candles("BTC-USDT", "1H", limit=301)


# ---- business error & retry ----

def _mock_resp(payload: dict) -> MagicMock:
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = payload
    return m


def test_fetch_candles_business_error_raises(monkeypatch):
    client = OKXClient()
    bad_payload = {"code": "51001", "msg": "instId not found", "data": []}
    monkeypatch.setattr(client.session, "get", lambda *a, **kw: _mock_resp(bad_payload))
    monkeypatch.setattr("investment.data.okx_client.time.sleep", lambda *a, **kw: None)

    with pytest.raises(RuntimeError, match="重试.*仍失败"):
        client.fetch_candles("XX-YY", "1H", limit=10)


def test_fetch_candles_succeeds_after_retry(monkeypatch, sample_payload):
    client = OKXClient()
    call_count = {"n": 0}

    def fake_get(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RequestsConnectionError("network down")
        return _mock_resp(sample_payload)

    monkeypatch.setattr(client.session, "get", fake_get)
    monkeypatch.setattr("investment.data.okx_client.time.sleep", lambda *a, **kw: None)

    df = client.fetch_candles("BTC-USDT", "1H", limit=10)
    assert len(df) == 3
    assert call_count["n"] == 2


def test_fetch_candles_exhausts_retries(monkeypatch):
    client = OKXClient()

    def always_fail(*args, **kwargs):
        raise RequestsConnectionError("forever down")

    monkeypatch.setattr(client.session, "get", always_fail)
    monkeypatch.setattr("investment.data.okx_client.time.sleep", lambda *a, **kw: None)

    with pytest.raises(RuntimeError, match="重试.*仍失败"):
        client.fetch_candles("BTC-USDT", "1H", limit=10)
