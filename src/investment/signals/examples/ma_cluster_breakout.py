"""规则：均线密集后突破（双均线交易系统 · 开仓方法 A）。

来源：YouTube《我的第一个100W来源，双均线交易系统实战》(币哥)。
6 条均线 (SMA/EMA 20-60-120) 紧密缠绕在一起后，价格向上突破或向下跌破整个簇，
作为顺势开仓信号。

config/signals.yaml::

    ma_cluster_breakout:
      enabled: true
      cluster_width_pct: 0.6     # 6 条均线极差占均值的百分比 ≤ 此值视为密集
      breakout_buffer_pct: 0.0   # 收盘价需要超出簇 max/min 的额外缓冲（0 = 紧贴）

判定（只看最末两根 confirmed bar）：

- 上根 bar：6 条均线 (max-min)/avg*100 ≤ cluster_width_pct（处于密集态）
- 当前 bar：
    - close > max(6MA) * (1 + buffer)  且  上根 bar close <= 上根 bar max(6MA)
      → 上破开多
    - close < min(6MA) * (1 - buffer)  且  上根 bar close >= 上根 bar min(6MA)
      → 下破开空

止损位（写在 extra 里供下游用）：
- 多 → 上根 bar 6 条均线 min
- 空 → 上根 bar 6 条均线 max

依赖列：sma20/60/120、ema20/60/120、close、ts、confirm。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from investment.signals.base import Signal, SignalRule

MA_COLS: tuple[str, ...] = ("sma20", "sma60", "sma120", "ema20", "ema60", "ema120")


class MaClusterBreakoutRule(SignalRule):
    name = "ma_cluster_breakout"

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
    ) -> Optional[Signal]:
        cluster_width_pct = float(self.params.get("cluster_width_pct", 0.6))
        buffer_pct = float(self.params.get("breakout_buffer_pct", 0.0))

        for c in MA_COLS:
            if c not in df.columns:
                return None
        if "close" not in df.columns:
            return None

        pair = self.last_two_confirmed(df)
        if pair is None:
            return None
        prev, last = pair

        prev_mas = [prev[c] for c in MA_COLS]
        last_mas = [last[c] for c in MA_COLS]
        if any(pd.isna(v) for v in prev_mas + last_mas):
            return None
        if pd.isna(prev["close"]) or pd.isna(last["close"]):
            return None

        prev_max, prev_min = max(prev_mas), min(prev_mas)
        prev_avg = sum(prev_mas) / len(prev_mas)
        if prev_avg <= 0:
            return None
        prev_width_pct = (prev_max - prev_min) / prev_avg * 100
        if prev_width_pct > cluster_width_pct:
            return None  # 上根 bar 还不是密集态，跳过

        last_max, last_min = max(last_mas), min(last_mas)
        prev_close = float(prev["close"])
        last_close = float(last["close"])

        # 上破：上根 bar close 在簇内或下方，当前 bar close 突破簇顶
        if prev_close <= prev_max and last_close > last_max * (1 + buffer_pct / 100):
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                rule_name=self.name,
                direction="long",
                bar_ts=last["ts"],
                price=last_close,
                message=(
                    f"[{symbol} {timeframe}] 均线密集后上破："
                    f"6MA密度={prev_width_pct:.3f}% ≤ {cluster_width_pct}%，"
                    f"close={last_close:.4f} > 簇顶={last_max:.4f}。"
                    f"建议止损 {prev_min:.4f}"
                ),
                extra={
                    "cluster_width_pct": prev_width_pct,
                    "cluster_top": last_max,
                    "cluster_bottom": last_min,
                    "suggested_stop": prev_min,
                },
            )

        # 下破：上根 bar close 在簇内或上方，当前 bar close 跌破簇底
        if prev_close >= prev_min and last_close < last_min * (1 - buffer_pct / 100):
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                rule_name=self.name,
                direction="short",
                bar_ts=last["ts"],
                price=last_close,
                message=(
                    f"[{symbol} {timeframe}] 均线密集后下破："
                    f"6MA密度={prev_width_pct:.3f}% ≤ {cluster_width_pct}%，"
                    f"close={last_close:.4f} < 簇底={last_min:.4f}。"
                    f"建议止损 {prev_max:.4f}"
                ),
                extra={
                    "cluster_width_pct": prev_width_pct,
                    "cluster_top": last_max,
                    "cluster_bottom": last_min,
                    "suggested_stop": prev_max,
                },
            )

        return None


__all__ = ["MaClusterBreakoutRule", "MA_COLS"]
