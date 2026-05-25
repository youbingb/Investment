"""指标层入口。

主要 API：
    from investment.indicators import compute_all, MA_PERIODS, sma, ema, dot_low

``compute_all(df)`` 给阶段 1 拿到的 K 线 DataFrame 追加 9 列指标，
直接对应 [docs/PINE_SCRIPT_MAPPING.md](../../../docs/PINE_SCRIPT_MAPPING.md)
里 6 条均线 + 3 个圆点。
"""
from __future__ import annotations

import pandas as pd

from investment.indicators.dot_locator import dot_low
from investment.indicators.moving_average import ema, sma

#: 复刻 Pine Script 的三组周期：20 / 60 / 120
MA_PERIODS: tuple[int, ...] = (20, 60, 120)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """给一个含 ts/open/high/low/close 列的 DataFrame 追加 9 列指标。

    Args:
        df: 至少含 ``close`` 和 ``low`` 两列；ts 升序最好（不强制）。

    Returns:
        新 DataFrame（不原地修改）。新增列：
        - ``sma20``, ``sma60``, ``sma120``
        - ``ema20``, ``ema60``, ``ema120``
        - ``dot20``, ``dot60``, ``dot120``

    前 ``max(MA_PERIODS)=120`` 行某些指标会是 NaN，信号判定时要跳过。
    """
    required = {"close", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"compute_all 需要列 {required}，缺少 {missing}")

    out = df.copy()
    for p in MA_PERIODS:
        out[f"sma{p}"] = sma(out["close"], p)
        out[f"ema{p}"] = ema(out["close"], p)
        out[f"dot{p}"] = dot_low(out["low"], p)
    return out


__all__ = ["compute_all", "sma", "ema", "dot_low", "MA_PERIODS"]
