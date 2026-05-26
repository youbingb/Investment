"""历史回放 + 收益跟踪。

两层 API：

1. ``backtest_rules(df, rules)`` —— 纯信号生成，不算收益。返回 BacktestResult.signals。

2. ``evaluate_outcomes(result, df, horizons, exit_horizon)`` —— 给每个信号算未来 N
   根 K 的收益 / MFE / MAE，附到 BacktestResult.outcomes。

3. ``backtest_with_returns(df, rules, ...)`` —— 一次跑完，CLI 用。

设计要点：
- direction='long'：未来 close 涨即赚；'short'：未来 close 跌即赚；'neutral'：跳过
- horizon i 的收益定义：``(close[t+i] - close[t]) / close[t]``，short 反号
- MFE (Max Favorable Excursion) / MAE (Max Adverse Excursion)：以 entry close 为基准，
  在 ``[t+1, t+exit_horizon]`` 窗口内的最有利 / 最不利浮动收益。short 反号。
- 信号距离数据末尾不足 horizon → 该 horizon 收益记 NaN；exit_horizon 不够 → exit_return=None，
  这条 outcome 不进 equity_curve。
- equity_curve 用最简单的加法叠（每笔权重 1，不考虑复利），方便快速看趋势。要复利的另写。
- 不算手续费 / 滑点（用户阶段 6.5 决策起步先看信号质量）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from investment.logger import logger
from investment.signals.base import Signal, SignalRule

DEFAULT_WARMUP_BARS = 125
DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 10, 20)
DEFAULT_EXIT_HORIZON = 10


@dataclass
class SignalOutcome:
    """一个 Signal 的未来表现。"""
    signal: Signal
    entry_price: float
    exit_horizon: int
    horizon_returns: dict[int, float] = field(default_factory=dict)  # NaN 表数据不足
    mfe_pct: float = float("nan")
    mae_pct: float = float("nan")

    @property
    def exit_return(self) -> Optional[float]:
        """exit_horizon 那个 horizon 的收益；窗口不够时 NaN → None。"""
        r = self.horizon_returns.get(self.exit_horizon)
        if r is None or (isinstance(r, float) and math.isnan(r)):
            return None
        return r

    @property
    def is_win(self) -> Optional[bool]:
        r = self.exit_return
        if r is None:
            return None
        return bool(r > 0)


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    bars_total: int
    bars_evaluated: int
    signals: list[Signal] = field(default_factory=list)
    outcomes: list[SignalOutcome] = field(default_factory=list)

    # ---- 信号层面汇总（不需要 outcomes）----

    @property
    def hits_by_rule(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.signals:
            out[s.rule_name] = out.get(s.rule_name, 0) + 1
        return out

    @property
    def hits_by_direction(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.signals:
            out[s.direction] = out.get(s.direction, 0) + 1
        return out

    # ---- 收益层面汇总（需要 outcomes）----

    def stats_by_rule(self) -> dict[str, dict[str, float]]:
        """按规则汇总：count / trades / wins / win_rate / avg_return / median_return / avg_mfe / avg_mae。

        - count = 命中数
        - trades = 实际有完整 exit_horizon 窗口的数量
        - wins / win_rate 只统计 trades
        - avg_return / median_return / avg_mfe / avg_mae 在 trades 上算
        """
        stats: dict[str, dict[str, float]] = {}
        # 先按 rule 收集 outcomes
        per_rule: dict[str, list[SignalOutcome]] = {}
        for o in self.outcomes:
            per_rule.setdefault(o.signal.rule_name, []).append(o)
        # 没产生 outcome（被 neutral 跳过）的规则也要在表里露出来，从 signals 里补 count
        for s in self.signals:
            per_rule.setdefault(s.rule_name, per_rule.get(s.rule_name, []))

        for name, outs in per_rule.items():
            count = sum(1 for s in self.signals if s.rule_name == name)
            trades = [o for o in outs if o.exit_return is not None]
            n_trades = len(trades)
            wins = sum(1 for o in trades if o.is_win)
            returns = [o.exit_return for o in trades]  # type: ignore[misc]
            mfes = [o.mfe_pct for o in trades if not math.isnan(o.mfe_pct)]
            maes = [o.mae_pct for o in trades if not math.isnan(o.mae_pct)]

            stats[name] = {
                "count": float(count),
                "trades": float(n_trades),
                "wins": float(wins),
                "win_rate": (wins / n_trades) if n_trades else float("nan"),
                "avg_return": (sum(returns) / n_trades) if n_trades else float("nan"),
                "median_return": _median(returns) if n_trades else float("nan"),
                "avg_mfe": (sum(mfes) / len(mfes)) if mfes else float("nan"),
                "avg_mae": (sum(maes) / len(maes)) if maes else float("nan"),
            }
        return stats

    def equity_curve(self) -> list[tuple[pd.Timestamp, float]]:
        """简单累加曲线：每笔权重 1，起始 NAV=1.0。

        只用有完整 exit_return 的 outcomes；按 bar_ts 升序。
        """
        trades = [o for o in self.outcomes if o.exit_return is not None]
        trades.sort(key=lambda o: o.signal.bar_ts)
        nav = 1.0
        curve: list[tuple[pd.Timestamp, float]] = []
        for o in trades:
            nav += o.exit_return  # type: ignore[operator]
            curve.append((o.signal.bar_ts, nav))
        return curve

    @property
    def total_return(self) -> float:
        """累计简单收益（最末 NAV - 1.0）。无 trade 时为 0。"""
        curve = self.equity_curve()
        if not curve:
            return 0.0
        return curve[-1][1] - 1.0

    @property
    def max_drawdown(self) -> float:
        """峰到谷最大跌幅（负数，0 表示无回撤）。"""
        curve = self.equity_curve()
        if not curve:
            return 0.0
        peak = 1.0  # 起始 NAV
        worst = 0.0
        for _, nav in curve:
            if nav > peak:
                peak = nav
            dd = (nav - peak) / peak if peak > 0 else 0.0
            if dd < worst:
                worst = dd
        return worst


def _median(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


# ============================================================
#  主流程
# ============================================================

def backtest_rules(
    df: pd.DataFrame,
    rules: list[SignalRule],
    *,
    symbol: str,
    timeframe: str,
    warmup_bars: int = DEFAULT_WARMUP_BARS,
) -> BacktestResult:
    """对 df 逐根滚动跑 rules，返回所有命中信号（不算收益）。

    rule 抛错被吞掉，按 0 命中处理（和 run_pipeline 行为一致）。
    """
    n = len(df)
    if n <= warmup_bars or not rules:
        return BacktestResult(symbol, timeframe, bars_total=n, bars_evaluated=0)

    signals: list[Signal] = []
    bars_evaluated = 0

    for i in range(warmup_bars, n):
        sub = df.iloc[: i + 1]
        if "confirm" in sub.columns and not bool(sub.iloc[-1]["confirm"]):
            continue
        bars_evaluated += 1
        for rule in rules:
            try:
                sig = rule.evaluate(sub, symbol=symbol, timeframe=timeframe)
            except Exception as e:
                logger.debug(f"backtest 规则 {rule.name} 在第 {i} 根抛错：{e}")
                continue
            if sig is not None:
                signals.append(sig)

    logger.info(
        f"backtest {symbol} {timeframe}: 总 {n} 根 / 评估 {bars_evaluated} 根 / 命中 {len(signals)}"
    )
    return BacktestResult(
        symbol=symbol,
        timeframe=timeframe,
        bars_total=n,
        bars_evaluated=bars_evaluated,
        signals=signals,
    )


def evaluate_outcomes(
    result: BacktestResult,
    df: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    exit_horizon: int = DEFAULT_EXIT_HORIZON,
) -> BacktestResult:
    """给 result.signals 算未来收益，附到 result.outcomes（原地）。

    df 必须含 ts / close / high / low 列，且按 ts 升序。
    df 是回测时用的同一份 df —— 因为信号的 bar_ts 必须在 df 里能找到。

    long 信号收益用 (close[t+i] - close[t]) / close[t]
    short 信号反号
    neutral 信号跳过（不入 outcomes）
    """
    if not result.signals:
        return result
    if exit_horizon not in horizons:
        horizons = tuple(sorted(set(horizons) | {exit_horizon}))

    # 用 ts 建索引，O(1) 查信号在 df 里的行号
    ts_to_idx = {ts: i for i, ts in enumerate(df["ts"])}
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)

    skipped_neutral = 0
    skipped_not_found = 0
    for sig in result.signals:
        if sig.direction not in ("long", "short"):
            skipped_neutral += 1
            continue
        idx = ts_to_idx.get(sig.bar_ts)
        if idx is None:
            skipped_not_found += 1
            continue
        entry = float(closes[idx])
        if entry <= 0:
            continue

        is_long = sig.direction == "long"
        h_returns: dict[int, float] = {}
        for h in horizons:
            if idx + h >= n:
                h_returns[h] = float("nan")
                continue
            raw = (closes[idx + h] - entry) / entry
            h_returns[h] = raw if is_long else -raw

        # MFE / MAE 在 [idx+1, idx+exit_horizon] 窗口内
        end = min(idx + exit_horizon, n - 1)
        if end <= idx:
            mfe = mae = float("nan")
        else:
            window_high = highs[idx + 1 : end + 1].max()
            window_low = lows[idx + 1 : end + 1].min()
            if is_long:
                mfe = (window_high - entry) / entry
                mae = (window_low - entry) / entry
            else:
                # short：价格跌 → 我们赚；MFE = entry 比 low 高多少
                mfe = (entry - window_low) / entry
                mae = (entry - window_high) / entry

        result.outcomes.append(SignalOutcome(
            signal=sig,
            entry_price=entry,
            exit_horizon=exit_horizon,
            horizon_returns=h_returns,
            mfe_pct=mfe,
            mae_pct=mae,
        ))

    if skipped_neutral:
        logger.info(f"evaluate_outcomes 跳过 {skipped_neutral} 个 neutral 信号")
    if skipped_not_found:
        logger.warning(f"evaluate_outcomes 跳过 {skipped_not_found} 个 ts 找不到的信号")
    return result


def backtest_with_returns(
    df: pd.DataFrame,
    rules: list[SignalRule],
    *,
    symbol: str,
    timeframe: str,
    warmup_bars: int = DEFAULT_WARMUP_BARS,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    exit_horizon: int = DEFAULT_EXIT_HORIZON,
) -> BacktestResult:
    """便捷封装：backtest_rules + evaluate_outcomes 一次跑完。"""
    result = backtest_rules(
        df, rules,
        symbol=symbol, timeframe=timeframe,
        warmup_bars=warmup_bars,
    )
    return evaluate_outcomes(
        result, df,
        horizons=horizons, exit_horizon=exit_horizon,
    )


__all__ = [
    "backtest_rules", "evaluate_outcomes", "backtest_with_returns",
    "BacktestResult", "SignalOutcome",
    "DEFAULT_WARMUP_BARS", "DEFAULT_HORIZONS", "DEFAULT_EXIT_HORIZON",
]
