"""规则：均线发散后首次回踩 20 均线不破（双均线交易系统 · 开仓方法 B）。

来源：YouTube《我的第一个100W来源，双均线交易系统实战》(币哥)。
6 条均线 (SMA/EMA 20-60-120) 已经发散开 → 趋势明确。价格在趋势中回踩 20 均线
(SMA20 或 EMA20)，触碰但收盘没有有效跌破/突破 20 均线 → 顺势开仓。

config/signals.yaml::

    ma20_pullback:
      enabled: true
      ma_col: ema20             # 用 ema20 或 sma20 作为 "20 均线"
      tolerance_pct: 0.3        # 当根 wick 距 ma20 在 ±此值内视为触碰
      min_spread_pct: 1.0       # 上根 bar 6MA (max-min)/avg ≥ 此值视为发散
      require_trend_align: true # 是否要求 ema20/ema60/ema120 完全单调对齐趋势方向

判定（只看最末根 confirmed bar，上一根用于检查趋势是否已发散）：

- 上根 bar 6MA 极差/均值*100 ≥ min_spread_pct（已发散）
- 趋势方向：
    - 上升：ema20 > ema60 > ema120（require_trend_align 时强校验）+ close > ma_col
    - 下降：ema20 < ema60 < ema120 + close < ma_col
- 上升趋势 + 当根 low ∈ [ma_col*(1-tol), ma_col*(1+tol)] + close > ma_col
  → 开多
- 下降趋势 + 当根 high ∈ [ma_col*(1-tol), ma_col*(1+tol)] + close < ma_col
  → 开空

止损位（写在 extra 里）：
- 多 → ma_col * (1 - tolerance_pct/100)
- 空 → ma_col * (1 + tolerance_pct/100)

依赖列：ma_col、close、high、low、ts、confirm、（趋势校验时还需 ema60/ema120）。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from investment.signals.base import Signal, SignalRule
from investment.signals.examples.ma_cluster_breakout import MA_COLS


class Ma20PullbackRule(SignalRule):
    name = "ma20_pullback"

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
    ) -> Optional[Signal]:
        ma_col = self.params.get("ma_col", "ema20")
        tolerance_pct = float(self.params.get("tolerance_pct", 0.3))
        min_spread_pct = float(self.params.get("min_spread_pct", 1.0))
        require_trend_align = bool(self.params.get("require_trend_align", True))

        required_cols = {ma_col, "ema60", "ema120", "close", "high", "low"}
        if not required_cols.issubset(df.columns):
            return None
        for c in MA_COLS:
            if c not in df.columns:
                return None

        pair = self.last_two_confirmed(df)
        if pair is None:
            return None
        prev, last = pair

        # 上一根 6MA 必须已经发散
        prev_mas = [prev[c] for c in MA_COLS]
        if any(pd.isna(v) for v in prev_mas):
            return None
        prev_avg = sum(prev_mas) / len(prev_mas)
        if prev_avg <= 0:
            return None
        prev_spread_pct = (max(prev_mas) - min(prev_mas)) / prev_avg * 100
        if prev_spread_pct < min_spread_pct:
            return None

        # 当前根所有判定列都得有值
        ma_val = last[ma_col]
        c, h, l = last["close"], last["high"], last["low"]
        e60, e120 = last["ema60"], last["ema120"]
        if any(pd.isna(v) for v in (ma_val, c, h, l, e60, e120)):
            return None
        ma_val = float(ma_val)
        if ma_val <= 0:
            return None

        upper = ma_val * (1 + tolerance_pct / 100)
        lower = ma_val * (1 - tolerance_pct / 100)
        ema20_val = float(last["ema20"])

        # 上升趋势：ema20 > ema60 > ema120 + close > ma_col + low 触及 ma_col 附近
        uptrend = ema20_val > float(e60) > float(e120) if require_trend_align else (c > ma_val)
        if uptrend and c > ma_val and lower <= float(l) <= upper:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                rule_name=self.name,
                direction="long",
                bar_ts=last["ts"],
                price=float(c),
                message=(
                    f"[{symbol} {timeframe}] 回踩 {ma_col} 不破（多）："
                    f"6MA发散={prev_spread_pct:.2f}% ≥ {min_spread_pct}%，"
                    f"low={float(l):.4f} 触及 {ma_col}={ma_val:.4f}，"
                    f"close={float(c):.4f} 收回均线上方。建议止损 {lower:.4f}"
                ),
                extra={
                    "spread_pct": prev_spread_pct,
                    "ma_value": ma_val,
                    "low": float(l),
                    "suggested_stop": lower,
                },
            )

        # 下降趋势：ema20 < ema60 < ema120 + close < ma_col + high 触及 ma_col 附近
        downtrend = ema20_val < float(e60) < float(e120) if require_trend_align else (c < ma_val)
        if downtrend and c < ma_val and lower <= float(h) <= upper:
            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                rule_name=self.name,
                direction="short",
                bar_ts=last["ts"],
                price=float(c),
                message=(
                    f"[{symbol} {timeframe}] 回踩 {ma_col} 不破（空）："
                    f"6MA发散={prev_spread_pct:.2f}% ≥ {min_spread_pct}%，"
                    f"high={float(h):.4f} 触及 {ma_col}={ma_val:.4f}，"
                    f"close={float(c):.4f} 收回均线下方。建议止损 {upper:.4f}"
                ),
                extra={
                    "spread_pct": prev_spread_pct,
                    "ma_value": ma_val,
                    "high": float(h),
                    "suggested_stop": upper,
                },
            )

        return None


__all__ = ["Ma20PullbackRule"]
