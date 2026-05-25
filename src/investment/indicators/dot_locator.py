"""圆点定位 — Pine Script ``bl[N]`` 的 Python 等价。

Pine Script 的 ``bl = low; bl[20]`` 表示"当前 bar 向前数 20 根的 low 值"。
等价于 pandas 的 ``df['low'].shift(20)``。

应用场景：当前 bar 的 dot60 值常用作"60 根前的支撑/压力位"，
价格回踩到这个值附近常作为回踩入场信号（见 signals/examples/dot_pullback.py，阶段 3）。
"""
from __future__ import annotations

import pandas as pd


def dot_low(low_series: pd.Series, n: int) -> pd.Series:
    """N 根前的 low；前 N 行为 NaN。"""
    if n < 1:
        raise ValueError(f"n 必须 >= 1，实际 {n}")
    return low_series.shift(n)


__all__ = ["dot_low"]
