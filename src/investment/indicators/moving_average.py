"""SMA / EMA 实现。

复刻用户 Pine Script 的 `ta.sma(close, N)` 与 `ta.ema(close, N)`。

关键点：**EMA 必须用 ``adjust=False``**。
- ``ewm(span=N, adjust=False)`` = TradingView ta.ema 算法（递归型）
- ``ewm(span=N, adjust=True)`` = pandas 默认（加权统计型），数值会差几个 BP
"""
from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均。前 ``period-1`` 行返回 NaN。"""
    if period < 1:
        raise ValueError(f"period 必须 >= 1，实际 {period}")
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均，与 TradingView ta.ema 数值兼容。"""
    if period < 1:
        raise ValueError(f"period 必须 >= 1，实际 {period}")
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


__all__ = ["sma", "ema"]
