"""指标层单元测试 — 不依赖网络、不依赖样本文件，纯逻辑断言。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investment.indicators import MA_PERIODS, compute_all
from investment.indicators.dot_locator import dot_low
from investment.indicators.moving_average import ema, sma


# ---- sma ----

def test_sma_basic():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = sma(s, 3)
    # 前 period-1 行为 NaN
    assert pd.isna(out.iloc[0])
    assert pd.isna(out.iloc[1])
    # SMA(3) at index 2 = mean(1,2,3) = 2
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[3] == pytest.approx(3.0)
    assert out.iloc[4] == pytest.approx(4.0)


def test_sma_rejects_bad_period():
    with pytest.raises(ValueError):
        sma(pd.Series([1.0]), 0)
    with pytest.raises(ValueError):
        sma(pd.Series([1.0]), -5)


# ---- ema ----

def test_ema_recursive_formula_with_adjust_false():
    """验证 EMA 用的是 adjust=False 算法（TradingView ta.ema 兼容）。

    α = 2/(N+1) = 2/4 = 0.5 for N=3
    内部 seed=第一个值，min_periods=3 让前 2 个外显 NaN：
        EMA[0]=1.0 (internal seed)
        EMA[1]=0.5*2 + 0.5*1   = 1.5
        EMA[2]=0.5*3 + 0.5*1.5 = 2.25  ← 第一个外显值
        EMA[3]=0.5*4 + 0.5*2.25 = 3.125
        EMA[4]=0.5*5 + 0.5*3.125 = 4.0625
    """
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ema(s, 3)
    assert pd.isna(out.iloc[0])
    assert pd.isna(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.25)
    assert out.iloc[3] == pytest.approx(3.125)
    assert out.iloc[4] == pytest.approx(4.0625)


def test_ema_differs_from_adjust_true():
    """守门：如果有人误改成 adjust=True，这条会失败。"""
    s = pd.Series(np.arange(1.0, 21.0))
    ours = ema(s, 5)
    pandas_default = s.ewm(span=5, adjust=True, min_periods=5).mean()
    # 两者在 warmup 区差异最明显
    diff = (ours - pandas_default).abs().max()
    assert diff > 0.1, "如果 adjust 配置改了，这里会差不出来 → 算法不再与 TradingView 一致"


def test_ema_rejects_bad_period():
    with pytest.raises(ValueError):
        ema(pd.Series([1.0]), 0)


# ---- dot_low ----

def test_dot_low_shifts_correctly():
    s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    out = dot_low(s, 2)
    assert pd.isna(out.iloc[0])
    assert pd.isna(out.iloc[1])
    assert out.iloc[2] == 10.0
    assert out.iloc[3] == 20.0
    assert out.iloc[4] == 30.0


def test_dot_low_rejects_bad_n():
    with pytest.raises(ValueError):
        dot_low(pd.Series([1.0]), 0)


# ---- compute_all ----

def _make_df(n: int) -> pd.DataFrame:
    """构造长度 n 的合成 OHLC，价格线性递增。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    base = np.arange(n, dtype=float) + 100.0
    return pd.DataFrame({
        "ts": idx,
        "open": base,
        "high": base + 1,
        "low": base - 1,
        "close": base,
    })


def test_compute_all_adds_nine_columns():
    df = _make_df(150)
    out = compute_all(df)
    for p in MA_PERIODS:
        assert f"sma{p}" in out.columns
        assert f"ema{p}" in out.columns
        assert f"dot{p}" in out.columns
    for c in ["ts", "open", "high", "low", "close"]:
        assert c in out.columns


def test_compute_all_does_not_mutate_input():
    df = _make_df(150)
    original_cols = list(df.columns)
    _ = compute_all(df)
    assert list(df.columns) == original_cols


def test_compute_all_dot_equals_shifted_low():
    df = _make_df(150)
    out = compute_all(df)
    # 第 50 行的 dot20 = 第 30 行的 low
    assert out["dot20"].iloc[50] == out["low"].iloc[30]
    assert out["dot60"].iloc[100] == out["low"].iloc[40]
    assert out["dot120"].iloc[130] == out["low"].iloc[10]


def test_compute_all_sma_value_known():
    """合成数据 close=100,101,102,...：SMA(20) 在第 19 行 = mean(100..119) = 109.5"""
    df = _make_df(100)
    out = compute_all(df)
    assert out["sma20"].iloc[19] == pytest.approx(109.5)


def test_compute_all_missing_column_raises():
    df = pd.DataFrame({"open": [1, 2, 3]})
    with pytest.raises(ValueError, match="缺少"):
        compute_all(df)
