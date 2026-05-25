"""示例规则：EMA 上穿/下穿 SMA（经典金叉死叉）。

config/signals.yaml::
    golden_cross:
      enabled: true
      fast: ema20      # 快线列名
      slow: sma60      # 慢线列名

判定：比较最末两根 confirmed bar 的 (fast, slow) 大小关系反转：
- 前 fast<=slow，当前 fast>slow  →  上穿（long）
- 前 fast>=slow，当前 fast<slow  →  下穿（short）

依赖列：df 必须含 fast/slow 指定的两列（compute_all 已经加好）。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from investment.signals.base import Signal, SignalRule


class GoldenCrossRule(SignalRule):
    name = "golden_cross"

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
    ) -> Optional[Signal]:
        fast_col = self.params.get("fast", "ema20")
        slow_col = self.params.get("slow", "sma60")

        for c in (fast_col, slow_col):
            if c not in df.columns:
                return None  # 还没算指标 / 配错了列名

        pair = self.last_two_confirmed(df)
        if pair is None:
            return None
        prev, last = pair
        if pd.isna(prev[fast_col]) or pd.isna(prev[slow_col]):
            return None
        if pd.isna(last[fast_col]) or pd.isna(last[slow_col]):
            return None

        # 上穿
        if prev[fast_col] <= prev[slow_col] and last[fast_col] > last[slow_col]:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                rule_name=self.name,
                direction="long",
                bar_ts=last["ts"],
                price=float(last["close"]),
                message=(
                    f"[{symbol} {timeframe}] 金叉 {fast_col}↑{slow_col}："
                    f"{fast_col}={last[fast_col]:.2f} > {slow_col}={last[slow_col]:.2f}，"
                    f"close={last['close']:.2f}"
                ),
                extra={"fast": float(last[fast_col]), "slow": float(last[slow_col])},
            )

        # 下穿
        if prev[fast_col] >= prev[slow_col] and last[fast_col] < last[slow_col]:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                rule_name=self.name,
                direction="short",
                bar_ts=last["ts"],
                price=float(last["close"]),
                message=(
                    f"[{symbol} {timeframe}] 死叉 {fast_col}↓{slow_col}："
                    f"{fast_col}={last[fast_col]:.2f} < {slow_col}={last[slow_col]:.2f}，"
                    f"close={last['close']:.2f}"
                ),
                extra={"fast": float(last[fast_col]), "slow": float(last[slow_col])},
            )

        return None


__all__ = ["GoldenCrossRule"]
