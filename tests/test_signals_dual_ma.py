"""双均线交易系统两条规则的单元测试。

ma_cluster_breakout — 均线密集后突破
ma20_pullback       — 均线发散后回踩 20 均线不破
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investment.signals.examples.ma20_pullback import Ma20PullbackRule
from investment.signals.examples.ma_cluster_breakout import (
    MA_COLS,
    MaClusterBreakoutRule,
)
from investment.signals.loader import REGISTRY


def _make_df(
    rows: list[dict],
    confirm_last: bool = True,
) -> pd.DataFrame:
    """每行 dict 必须包含：close, high, low, sma20/60/120, ema20/60/120。

    最末行 confirm 由 confirm_last 控制，其他行均 True。
    """
    n = len(rows)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame(rows)
    df["ts"] = idx
    df["open"] = df["close"]
    df["vol"] = 0.0
    df["confirm"] = [True] * (n - 1) + [confirm_last]
    return df


def _make_cluster_row(center: float, high: float = None, low: float = None, close: float = None) -> dict:
    """构造 6 条均线全部 = center 的 "完全密集" 一行。"""
    row = {c: center for c in MA_COLS}
    row["close"] = center if close is None else close
    row["high"] = (close if close is not None else center) + 1 if high is None else high
    row["low"] = (close if close is not None else center) - 1 if low is None else low
    return row


# ============================================================
#  MaClusterBreakoutRule
# ============================================================

def test_ma_cluster_breakout_long_hit():
    """上根紧密 (6MA 都 100)，当根 close 突破簇顶 → 多。"""
    prev = _make_cluster_row(100.0, close=99.0)
    last = _make_cluster_row(100.0, close=101.0)
    df = _make_df([prev, last])
    sig = MaClusterBreakoutRule().evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None
    assert sig.direction == "long"
    assert "上破" in sig.message
    assert "suggested_stop" in sig.extra


def test_ma_cluster_breakout_short_hit():
    """上根紧密，当根 close 跌破簇底 → 空。"""
    prev = _make_cluster_row(100.0, close=100.5)
    last = _make_cluster_row(100.0, close=99.0)
    df = _make_df([prev, last])
    sig = MaClusterBreakoutRule().evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None
    assert sig.direction == "short"
    assert "下破" in sig.message


def test_ma_cluster_breakout_miss_when_not_tight():
    """上根 6MA 极差太大（不密集），即使有突破也跳过。"""
    prev = {
        "sma20": 100, "sma60": 105, "sma120": 110,
        "ema20": 101, "ema60": 106, "ema120": 111,  # max-min = 11, /avg ≈ 10%
        "close": 100, "high": 102, "low": 99,
    }
    last = {
        "sma20": 100, "sma60": 105, "sma120": 110,
        "ema20": 101, "ema60": 106, "ema120": 111,
        "close": 115, "high": 116, "low": 100,
    }
    df = _make_df([prev, last])
    assert MaClusterBreakoutRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_ma_cluster_breakout_miss_when_no_breakout():
    """上根紧密，但当根 close 仍在簇内 → 无信号。"""
    prev = _make_cluster_row(100.0, close=99.5)
    last = _make_cluster_row(100.0, close=100.0)
    df = _make_df([prev, last])
    assert MaClusterBreakoutRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_ma_cluster_breakout_nan_skipped():
    prev = _make_cluster_row(100.0, close=99.0)
    prev["sma120"] = np.nan
    last = _make_cluster_row(100.0, close=101.0)
    df = _make_df([prev, last])
    assert MaClusterBreakoutRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_ma_cluster_breakout_custom_width_param():
    """width 阈值收紧到 0.05% 后，原来 0.5% 的密集也被排除。"""
    prev = {
        "sma20": 100, "sma60": 100.3, "sma120": 100.5,  # max-min=0.5
        "ema20": 100.1, "ema60": 100.2, "ema120": 100.4,
        "close": 100, "high": 100.5, "low": 99.5,
    }
    last = {**prev, "close": 101}
    df = _make_df([prev, last])
    # 默认 cluster_width_pct=0.6 — 命中
    assert MaClusterBreakoutRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is not None
    # 收紧到 0.05% — 跳过
    rule = MaClusterBreakoutRule(params={"cluster_width_pct": 0.05})
    assert rule.evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_ma_cluster_breakout_missing_column():
    df = _make_df([_make_cluster_row(100.0, close=99.0), _make_cluster_row(100.0, close=101.0)])
    df = df.drop(columns=["ema120"])
    assert MaClusterBreakoutRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


# ============================================================
#  Ma20PullbackRule
# ============================================================

def _make_spread_row(
    ma20: float, ma60: float, ma120: float,
    close: float, high: float, low: float,
    sma20_offset: float = 0.0,
) -> dict:
    """构造一行：ema20/60/120 给定，sma20 ~= ma20 (有小 offset)，
    sma60/sma120 跟 ema 同值（不参与趋势校验）。"""
    return {
        "ema20": ma20, "ema60": ma60, "ema120": ma120,
        "sma20": ma20 + sma20_offset, "sma60": ma60, "sma120": ma120,
        "close": close, "high": high, "low": low,
    }


def test_ma20_pullback_long_hit():
    """ema20>60>120 上升趋势，当根 low 触 ema20，close > ema20 → 多。"""
    # 上根 6MA 极差 (110-90)/100*100 = 20% > 1%（发散）
    prev = _make_spread_row(110, 100, 90, close=112, high=113, low=109)
    # 当根：ema20=110, low=110 (触碰), close=111 (收回上方)
    last = _make_spread_row(110, 100, 90, close=111, high=112, low=110)
    df = _make_df([prev, last])
    sig = Ma20PullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None
    assert sig.direction == "long"
    assert "多" in sig.message
    assert sig.extra["ma_value"] == 110.0


def test_ma20_pullback_short_hit():
    """ema20<60<120 下降趋势，当根 high 触 ema20，close < ema20 → 空。"""
    prev = _make_spread_row(90, 100, 110, close=88, high=89, low=87)
    last = _make_spread_row(90, 100, 110, close=89, high=90, low=88)
    df = _make_df([prev, last])
    sig = Ma20PullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None
    assert sig.direction == "short"
    assert "空" in sig.message


def test_ma20_pullback_miss_when_no_spread():
    """上根 6MA 完全粘在一起 → 视为未发散 → 跳过。"""
    prev = _make_spread_row(100, 100, 100, close=101, high=102, low=99)
    last = _make_spread_row(100, 100, 100, close=101, high=102, low=100)
    df = _make_df([prev, last])
    assert Ma20PullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_ma20_pullback_miss_when_trend_not_aligned():
    """ema20>120 但 ema60 不在中间 → 趋势不对齐（require_trend_align=True 默认）。"""
    # ema20=110, ema60=85 (太低), ema120=90 → 不满足 20>60>120
    prev = _make_spread_row(110, 85, 90, close=112, high=113, low=109)
    last = _make_spread_row(110, 85, 90, close=111, high=112, low=110)
    df = _make_df([prev, last])
    assert Ma20PullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None
    # 关闭趋势对齐校验 → 命中
    rule = Ma20PullbackRule(params={"require_trend_align": False})
    sig = rule.evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None and sig.direction == "long"


def test_ma20_pullback_miss_when_wick_too_far():
    """当根 low 距 ema20 超过 tolerance_pct → 跳过。"""
    # ema20=110, low=115 偏离 ≈4.5% > 0.3%
    prev = _make_spread_row(110, 100, 90, close=120, high=121, low=119)
    last = _make_spread_row(110, 100, 90, close=120, high=121, low=115)
    df = _make_df([prev, last])
    assert Ma20PullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_ma20_pullback_miss_when_close_breaks_ma():
    """low 触 ema20 但 close 也跌破 ema20 → 不算 "不破"。"""
    # ema20=110, low=110, close=109 (低于 ema20)
    prev = _make_spread_row(110, 100, 90, close=112, high=113, low=109)
    last = _make_spread_row(110, 100, 90, close=109, high=110.5, low=110)
    df = _make_df([prev, last])
    # close < ma_val 但 ema20>60>120 仍为 uptrend；条件 c > ma_val 不满足 → 不是多
    # 下跌趋势分支需要 ema20<60<120，也不满足 → None
    assert Ma20PullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_ma20_pullback_tolerance_param():
    """收紧 tolerance_pct 到 0.05% 后，偏离 0.18% 的触碰被排除。"""
    # ema20=110, low=110.2 → 偏离 0.18%
    prev = _make_spread_row(110, 100, 90, close=112, high=113, low=109)
    last = _make_spread_row(110, 100, 90, close=111, high=112, low=110.2)
    df = _make_df([prev, last])
    # 默认 tol=0.3 → 命中
    assert Ma20PullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is not None
    # 收紧到 0.05 → 跳过
    rule = Ma20PullbackRule(params={"tolerance_pct": 0.05})
    assert rule.evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_ma20_pullback_uses_sma20_when_configured():
    """ma_col=sma20 时，触碰的是 sma20 值。"""
    # ema20=110, sma20=108（差异 2%），用 sma20 作为触碰目标
    prev = _make_spread_row(110, 100, 90, close=112, high=113, low=109, sma20_offset=-2)
    last = _make_spread_row(110, 100, 90, close=109, high=110, low=108, sma20_offset=-2)
    df = _make_df([prev, last])
    # 用 ema20 (110) → low=108 偏离 ≈1.8% > 0.3% → 跳过
    assert Ma20PullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is None
    # 用 sma20 (108) → low=108 ≈ sma20，close=109 > sma20 → 命中
    rule = Ma20PullbackRule(params={"ma_col": "sma20"})
    sig = rule.evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None
    assert sig.direction == "long"
    assert sig.extra["ma_value"] == 108.0


# ============================================================
#  Registry
# ============================================================

def test_registry_contains_new_rules():
    assert "ma_cluster_breakout" in REGISTRY
    assert "ma20_pullback" in REGISTRY
