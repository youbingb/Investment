"""简易历史回放：在已收盘 K 线上滚动跑信号规则，统计命中。

设计：
- 输入是已带指标列的 df（用 compute_all 算好）
- 从 ``warmup`` 根 K 开始，逐根把 ``df.iloc[:i+1]`` 喂给每个 rule.evaluate
- 命中即记下 Signal；不做盈亏统计（避免回测变重）
- 同一 (rule, bar_ts) 不去重 —— 这里就是想看每根 K 是否命中

返回结构方便 CLI 直接打印；可选导出 CSV。

回测 != 实时：rule 的 ``last_two_confirmed`` 拿到的"最末根"在每一步都不同，
所以同一条规则在历史上可能多次命中。这是预期行为。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from investment.logger import logger
from investment.signals.base import Signal, SignalRule

# 经验值：均线最长 120，dot 也是 120，再多 5 根防御
DEFAULT_WARMUP_BARS = 125


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    bars_total: int
    bars_evaluated: int
    signals: list[Signal] = field(default_factory=list)

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


def backtest_rules(
    df: pd.DataFrame,
    rules: list[SignalRule],
    *,
    symbol: str,
    timeframe: str,
    warmup_bars: int = DEFAULT_WARMUP_BARS,
) -> BacktestResult:
    """对 df 逐根滚动跑 rules，返回所有命中信号。

    Args:
        df: 已 compute_all 加好指标列的 K 线 df（升序 ts）
        rules: 实例化好的规则列表
        symbol, timeframe: 仅用作日志 + 结果元数据
        warmup_bars: 前 N 根跳过（指标 NaN）

    rule 抛错被吞掉，按 0 命中处理（和 run_pipeline 行为一致）。
    """
    n = len(df)
    if n <= warmup_bars or not rules:
        return BacktestResult(symbol, timeframe, bars_total=n, bars_evaluated=0)

    signals: list[Signal] = []
    bars_evaluated = 0

    # 只对 confirm=True 的 bar 当作 "最末根" 来回测
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


__all__ = ["backtest_rules", "BacktestResult", "DEFAULT_WARMUP_BARS"]
