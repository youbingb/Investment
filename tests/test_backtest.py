"""阶段 6 单测：backtest_rules。

覆盖：
- 总根数 / 评估根数统计正确
- warmup 之前的根不参与评估
- confirm=False 的根被跳过
- 每根命中累加到 BacktestResult.signals
- hits_by_rule / hits_by_direction 聚合正确
- rule 抛错被吞，其他规则照常跑
- 空 rules 或不够 warmup → 0 评估
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from investment.runner.backtest import (
    DEFAULT_WARMUP_BARS,
    BacktestResult,
    backtest_rules,
)
from investment.signals.base import Signal, SignalRule


def _df(n: int, confirm: list[bool] | None = None) -> pd.DataFrame:
    """构造 n 行带指标列的 df。"""
    from investment.indicators import compute_all
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    base = np.arange(n, dtype=float) + 100.0
    confirm_col = confirm if confirm is not None else [True] * n
    df = pd.DataFrame({
        "ts": idx, "open": base, "high": base + 1, "low": base - 1,
        "close": base, "vol": np.zeros(n), "vol_ccy": np.zeros(n),
        "vol_ccy_quote": np.zeros(n), "confirm": confirm_col,
    })
    return compute_all(df)


class _CountRule(SignalRule):
    """每根都命中的规则，方便统计评估次数。"""
    name = "count"

    def evaluate(self, df, *, symbol, timeframe):
        last = df.iloc[-1]
        return Signal(
            symbol=symbol, timeframe=timeframe, rule_name=self.name,
            direction="long", bar_ts=last["ts"], price=float(last["close"]),
            message=f"hit@{last['ts']}",
        )


class _NeverRule(SignalRule):
    name = "never"

    def evaluate(self, df, *, symbol, timeframe):
        return None


class _BoomRule(SignalRule):
    name = "boom"

    def evaluate(self, df, *, symbol, timeframe):
        raise RuntimeError("故意爆")


class _AlternateRule(SignalRule):
    """偶数根 long、奇数根 short，方便测 direction 分布。"""
    name = "alt"

    def evaluate(self, df, *, symbol, timeframe):
        last = df.iloc[-1]
        idx = len(df)
        return Signal(
            symbol=symbol, timeframe=timeframe, rule_name=self.name,
            direction="long" if idx % 2 == 0 else "short",
            bar_ts=last["ts"], price=float(last["close"]),
            message="alt",
        )


def test_warmup_skips_early_bars():
    n = DEFAULT_WARMUP_BARS + 5
    df = _df(n)
    r = backtest_rules(df, [_CountRule()], symbol="BTC", timeframe="1H")
    assert r.bars_total == n
    assert r.bars_evaluated == 5
    assert len(r.signals) == 5


def test_not_enough_bars_zero_evaluated():
    df = _df(DEFAULT_WARMUP_BARS)
    r = backtest_rules(df, [_CountRule()], symbol="BTC", timeframe="1H")
    assert r.bars_evaluated == 0
    assert r.signals == []


def test_unconfirmed_bars_skipped():
    n = DEFAULT_WARMUP_BARS + 4
    # 最后两根 confirm=False
    confirm = [True] * (n - 2) + [False, False]
    df = _df(n, confirm=confirm)
    r = backtest_rules(df, [_CountRule()], symbol="BTC", timeframe="1H")
    assert r.bars_evaluated == 2  # 只有前两根 confirmed bar 被评估
    assert len(r.signals) == 2


def test_empty_rules_zero_signals():
    df = _df(DEFAULT_WARMUP_BARS + 5)
    r = backtest_rules(df, [], symbol="BTC", timeframe="1H")
    assert r.bars_evaluated == 0
    assert r.signals == []


def test_hits_by_rule_aggregation():
    df = _df(DEFAULT_WARMUP_BARS + 10)
    r = backtest_rules(
        df,
        [_CountRule(), _NeverRule()],
        symbol="BTC", timeframe="1H",
    )
    assert r.hits_by_rule == {"count": 10}


def test_hits_by_direction():
    df = _df(DEFAULT_WARMUP_BARS + 6)  # 6 bars
    r = backtest_rules(df, [_AlternateRule()], symbol="BTC", timeframe="1H")
    assert sum(r.hits_by_direction.values()) == 6
    # 内部计数器从 warmup+1 开始，根据 idx 奇偶分 long/short
    assert "long" in r.hits_by_direction or "short" in r.hits_by_direction


def test_failing_rule_isolated():
    df = _df(DEFAULT_WARMUP_BARS + 3)
    r = backtest_rules(
        df,
        [_BoomRule(), _CountRule()],
        symbol="BTC", timeframe="1H",
    )
    # boom 全爆，count 全中
    assert r.hits_by_rule == {"count": 3}


def test_result_is_dataclass():
    df = _df(DEFAULT_WARMUP_BARS + 2)
    r = backtest_rules(df, [_CountRule()], symbol="ETH", timeframe="4H")
    assert isinstance(r, BacktestResult)
    assert r.symbol == "ETH"
    assert r.timeframe == "4H"
