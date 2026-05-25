"""阶段 4 调度层单测 — pipeline + scheduler trigger 映射。"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from investment.runner.pipeline import (
    PipelineResult, WatchItem, load_watchlist, run_pipeline,
)
from investment.runner.scheduler import trigger_for_timeframe
from investment.signals.base import Signal, SignalRule


# ============================================================
#  load_watchlist
# ============================================================

def test_load_watchlist_default():
    """默认 config/symbols.yaml 应展开成 4 个组合：BTC/ETH × 1H/4H。"""
    items = load_watchlist()
    syms = {(i.symbol, i.timeframe) for i in items}
    assert ("BTC-USDT", "1H") in syms
    assert ("BTC-USDT", "4H") in syms
    assert ("ETH-USDT", "1H") in syms
    assert ("ETH-USDT", "4H") in syms


def test_load_watchlist_disabled_entry_skipped(tmp_path: Path):
    cfg = tmp_path / "symbols.yaml"
    cfg.write_text(textwrap.dedent("""
        watchlist:
          - symbol: BTC-USDT
            timeframes: ["1H"]
            enabled: true
          - symbol: ETH-USDT
            timeframes: ["1H"]
            enabled: false
        fetch:
          history_bars: 100
    """).strip(), encoding="utf-8")
    items = load_watchlist(config_path=cfg)
    assert len(items) == 1
    assert items[0].symbol == "BTC-USDT"
    assert items[0].history_bars == 100


def test_load_watchlist_missing_file_returns_empty(tmp_path: Path):
    assert load_watchlist(config_path=tmp_path / "nope.yaml") == []


def test_load_watchlist_expands_timeframes(tmp_path: Path):
    cfg = tmp_path / "symbols.yaml"
    cfg.write_text(textwrap.dedent("""
        watchlist:
          - symbol: BTC-USDT
            timeframes: ["1H", "4H", "1D"]
    """).strip(), encoding="utf-8")
    items = load_watchlist(config_path=cfg)
    assert {i.timeframe for i in items} == {"1H", "4H", "1D"}


# ============================================================
#  run_pipeline
# ============================================================

class _FakeStore:
    def __init__(self, df: pd.DataFrame):
        self.df = df

    def get_or_fetch(self, client, symbol, timeframe, n):
        return self.df.copy()


class _FakeClient:
    pass


def _make_df_with_full_indicators(n: int) -> pd.DataFrame:
    """构造 n 行有完整指标列的 df（用 compute_all 自然生成）。"""
    from investment.indicators import compute_all
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    base = np.arange(n, dtype=float) + 100.0
    df = pd.DataFrame({
        "ts": idx, "open": base, "high": base + 1, "low": base - 1,
        "close": base, "vol": np.zeros(n), "vol_ccy": np.zeros(n),
        "vol_ccy_quote": np.zeros(n), "confirm": [True] * n,
    })
    return compute_all(df)


class _AlwaysHitRule(SignalRule):
    name = "always"

    def evaluate(self, df, *, symbol, timeframe):
        last = df.iloc[-1]
        return Signal(
            symbol=symbol, timeframe=timeframe, rule_name=self.name,
            direction="long", bar_ts=last["ts"], price=float(last["close"]),
            message=f"always hit on {symbol} {timeframe}",
        )


class _NeverHitRule(SignalRule):
    name = "never"

    def evaluate(self, df, *, symbol, timeframe):
        return None


class _BoomRule(SignalRule):
    name = "boom"

    def evaluate(self, df, *, symbol, timeframe):
        raise RuntimeError("规则故意爆")


def test_run_pipeline_collects_signals():
    df = _make_df_with_full_indicators(150)
    result = run_pipeline(
        symbol="BTC-USDT", timeframe="1H",
        rules=[_AlwaysHitRule(), _NeverHitRule()],
        client=_FakeClient(), store=_FakeStore(df),
    )
    assert isinstance(result, PipelineResult)
    assert result.rows == 150
    assert len(result.signals) == 1
    assert result.signals[0].rule_name == "always"
    assert result.hit is True


def test_run_pipeline_isolates_failing_rule():
    """一条规则抛错不应让整个 pipeline 死。"""
    df = _make_df_with_full_indicators(150)
    result = run_pipeline(
        symbol="BTC-USDT", timeframe="1H",
        rules=[_BoomRule(), _AlwaysHitRule()],
        client=_FakeClient(), store=_FakeStore(df),
    )
    assert len(result.signals) == 1
    assert result.signals[0].rule_name == "always"


def test_run_pipeline_empty_data_returns_empty():
    result = run_pipeline(
        symbol="BTC-USDT", timeframe="1H",
        rules=[_AlwaysHitRule()],
        client=_FakeClient(),
        store=_FakeStore(pd.DataFrame(columns=["ts", "open", "high", "low", "close"])),
    )
    assert result.rows == 0
    assert result.signals == []
    assert result.hit is False


# ============================================================
#  trigger_for_timeframe
# ============================================================

def test_trigger_1H():
    t = trigger_for_timeframe("1H")
    # 每小时 :01:00
    fields = {f.name: str(f) for f in t.fields}
    assert fields["minute"] == "1"


def test_trigger_4H():
    t = trigger_for_timeframe("4H")
    fields = {f.name: str(f) for f in t.fields}
    assert fields["hour"] == "*/4"
    assert fields["minute"] == "1"


def test_trigger_1D():
    t = trigger_for_timeframe("1D")
    fields = {f.name: str(f) for f in t.fields}
    assert fields["hour"] == "0"
    assert fields["minute"] == "1"


def test_trigger_5m():
    t = trigger_for_timeframe("5m")
    fields = {f.name: str(f) for f in t.fields}
    assert fields["minute"] == "*/5"


@pytest.mark.parametrize("bad", ["7H", "17m", "3D", "weird", ""])
def test_trigger_invalid_raises(bad):
    with pytest.raises(ValueError):
        trigger_for_timeframe(bad)
