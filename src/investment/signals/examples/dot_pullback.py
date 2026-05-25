"""示例规则：当前 K 线 low 接近某条 dot 线（圆点回踩支撑）。

config/signals.yaml::
    dot_pullback:
      enabled: true
      dot: dot60              # 用哪条圆点：dot20 / dot60 / dot120
      tolerance_pct: 0.5      # 当前 low 距离 dot 值的百分比阈值

判定：仅看最末根 confirmed bar：
    |low - dot| / dot * 100 <= tolerance_pct

含义：N 根前的 low 是个历史支撑位，价格回踩到这附近常作为做多入场参考。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from investment.signals.base import Signal, SignalRule


class DotPullbackRule(SignalRule):
    name = "dot_pullback"

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
    ) -> Optional[Signal]:
        dot_col = self.params.get("dot", "dot60")
        tolerance_pct = float(self.params.get("tolerance_pct", 0.5))

        if dot_col not in df.columns or "low" not in df.columns:
            return None

        confirmed = self.confirmed(df)
        if confirmed.empty:
            return None
        last = confirmed.iloc[-1]

        if pd.isna(last[dot_col]) or pd.isna(last["low"]):
            return None

        dot_val = float(last[dot_col])
        if dot_val == 0:
            return None

        deviation_pct = abs(float(last["low"]) - dot_val) / dot_val * 100
        if deviation_pct > tolerance_pct:
            return None

        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            rule_name=self.name,
            direction="long",
            bar_ts=last["ts"],
            price=float(last["close"]),
            message=(
                f"[{symbol} {timeframe}] 回踩 {dot_col}："
                f"low={last['low']:.2f} ≈ {dot_col}={dot_val:.2f} "
                f"(偏离 {deviation_pct:.3f}%, 阈值 {tolerance_pct}%)"
            ),
            extra={
                "dot_value": dot_val,
                "low": float(last["low"]),
                "deviation_pct": deviation_pct,
            },
        )


__all__ = ["DotPullbackRule"]
