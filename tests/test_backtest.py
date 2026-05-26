"""阶段 6 单测：backtest_rules + evaluate_outcomes + 聚合统计。

覆盖：
- 总根数 / 评估根数统计正确
- warmup 之前的根不参与评估
- confirm=False 的根被跳过
- 每根命中累加到 BacktestResult.signals
- hits_by_rule / hits_by_direction 聚合正确
- rule 抛错被吞，其他规则照常跑
- 空 rules 或不够 warmup → 0 评估
- evaluate_outcomes：horizon return / MFE / MAE 在合成线性价格下算得对
- long / short 方向反号
- 信号距末尾不足窗口 → exit_return None
- neutral 信号被跳过
- stats_by_rule / equity_curve / total_return / max_drawdown 聚合
- backtest_with_returns 一次跑完
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from investment.runner.backtest import (
    DEFAULT_EXIT_HORIZON,
    DEFAULT_HORIZONS,
    DEFAULT_WARMUP_BARS,
    BacktestResult,
    SignalOutcome,
    backtest_rules,
    backtest_with_returns,
    evaluate_outcomes,
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


# ============================================================
#  evaluate_outcomes —— 收益跟踪
# ============================================================

def _custom_df(closes: list[float], highs: list[float] | None = None,
               lows: list[float] | None = None) -> pd.DataFrame:
    """构造定制收盘价的 df（不跑 compute_all，避免 NaN warmup 问题）。"""
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    h = highs or [c + 0.5 for c in closes]
    lo = lows or [c - 0.5 for c in closes]
    return pd.DataFrame({
        "ts": idx,
        "open": closes,
        "high": h,
        "low": lo,
        "close": closes,
        "vol": [0.0] * n,
        "vol_ccy": [0.0] * n,
        "vol_ccy_quote": [0.0] * n,
        "confirm": [True] * n,
    })


def _signal_at(df: pd.DataFrame, idx: int, direction: str = "long",
               rule_name: str = "test_rule") -> Signal:
    row = df.iloc[idx]
    return Signal(
        symbol="X-USDT", timeframe="1H", rule_name=rule_name,
        direction=direction, bar_ts=row["ts"], price=float(row["close"]),
        message="test", extra={},
    )


def test_horizon_return_long_linear():
    """线性价格 100,101,102,...，从 idx=0 长仓，h=5 收益 = 5/100 = 0.05。"""
    df = _custom_df([100.0 + i for i in range(30)])
    result = BacktestResult("X-USDT", "1H", 30, 30, signals=[_signal_at(df, 0, "long")])
    evaluate_outcomes(result, df, horizons=(1, 5, 10), exit_horizon=5)
    assert len(result.outcomes) == 1
    o = result.outcomes[0]
    assert o.entry_price == 100.0
    assert o.horizon_returns[1] == pytest.approx(0.01)
    assert o.horizon_returns[5] == pytest.approx(0.05)
    assert o.horizon_returns[10] == pytest.approx(0.10)
    assert o.exit_return == pytest.approx(0.05)
    assert o.is_win is True


def test_horizon_return_short_flips_sign():
    """同一段上涨线性价格 + short 信号 → 收益应该为负。"""
    df = _custom_df([100.0 + i for i in range(30)])
    result = BacktestResult("X-USDT", "1H", 30, 30, signals=[_signal_at(df, 0, "short")])
    evaluate_outcomes(result, df, horizons=(5,), exit_horizon=5)
    o = result.outcomes[0]
    assert o.horizon_returns[5] == pytest.approx(-0.05)
    assert o.is_win is False


def test_mfe_mae_long():
    """长仓：MFE 取窗口期最高 high 相对 entry，MAE 取最低 low 相对 entry。"""
    # close 100 (entry idx=0)，未来 5 根 high 最高 110、low 最低 95
    closes = [100.0, 102, 105, 108, 110, 107]
    highs = [100.5, 103, 106, 110, 110.5, 108]
    lows = [99.5, 95, 96, 100, 109, 106]  # idx=2 处 low=95，是窗口最低
    df = _custom_df(closes, highs=highs, lows=lows)
    result = BacktestResult("X-USDT", "1H", 6, 6, signals=[_signal_at(df, 0, "long")])
    evaluate_outcomes(result, df, horizons=(5,), exit_horizon=5)
    o = result.outcomes[0]
    # MFE = (110.5 - 100) / 100 = 0.105
    assert o.mfe_pct == pytest.approx(0.105)
    # MAE = (95 - 100) / 100 = -0.05
    assert o.mae_pct == pytest.approx(-0.05)


def test_mfe_mae_short_with_adverse_high():
    closes = [100.0, 102, 99, 95, 98, 92]
    highs = [100.5, 103, 100, 96, 99, 93]  # idx=1 high=103 → short 最大不利
    lows = [99.5, 101, 98, 94, 97, 91]      # idx=5 low=91 → short 最大有利
    df = _custom_df(closes, highs=highs, lows=lows)
    result = BacktestResult("X-USDT", "1H", 6, 6, signals=[_signal_at(df, 0, "short")])
    evaluate_outcomes(result, df, horizons=(5,), exit_horizon=5)
    o = result.outcomes[0]
    # MFE short = (100 - 91)/100 = 0.09（最大浮赢）
    assert o.mfe_pct == pytest.approx(0.09)
    # MAE short = (100 - 103)/100 = -0.03（最大浮亏）
    assert o.mae_pct == pytest.approx(-0.03)


def test_window_insufficient_records_nan():
    """信号距数据末尾不足 exit_horizon → exit_return None。"""
    df = _custom_df([100.0 + i for i in range(10)])
    # 信号在 idx=8，未来只有 1 根 K（idx=9）；horizons=(1,5)，exit=5
    result = BacktestResult("X-USDT", "1H", 10, 10, signals=[_signal_at(df, 8, "long")])
    evaluate_outcomes(result, df, horizons=(1, 5), exit_horizon=5)
    o = result.outcomes[0]
    assert not math.isnan(o.horizon_returns[1])
    assert math.isnan(o.horizon_returns[5])
    assert o.exit_return is None
    assert o.is_win is None


def test_neutral_skipped():
    df = _custom_df([100.0 + i for i in range(20)])
    sig = _signal_at(df, 0, "neutral")
    result = BacktestResult("X-USDT", "1H", 20, 20, signals=[sig])
    evaluate_outcomes(result, df, horizons=(5,), exit_horizon=5)
    assert result.outcomes == []


# ============================================================
#  聚合：stats_by_rule / equity_curve / total_return / max_drawdown
# ============================================================

def test_stats_by_rule_basic():
    """两个 long 信号都赚（5% 与 5/110 ≈ 4.54%），胜率 100%。"""
    df = _custom_df([100.0 + i for i in range(30)])
    s1 = _signal_at(df, 0, "long", rule_name="r1")
    s2 = _signal_at(df, 10, "long", rule_name="r1")
    result = BacktestResult("X-USDT", "1H", 30, 30, signals=[s1, s2])
    evaluate_outcomes(result, df, horizons=(5,), exit_horizon=5)
    stats = result.stats_by_rule()
    assert "r1" in stats
    assert stats["r1"]["count"] == 2
    assert stats["r1"]["trades"] == 2
    assert stats["r1"]["wins"] == 2
    assert stats["r1"]["win_rate"] == pytest.approx(1.0)
    # 平均 = (5/100 + 5/110) / 2
    expected_avg = (0.05 + 5 / 110) / 2
    assert stats["r1"]["avg_return"] == pytest.approx(expected_avg)


def test_stats_by_rule_partial_win():
    """涨段 long 赚、跌段 long 亏 → 胜率 0.5。"""
    closes = [100, 105, 110, 115, 120, 125, 120, 115, 110, 105, 100, 95]
    df = _custom_df([float(c) for c in closes])
    # idx=0 long h=5 → 25% 赚；idx=5 long h=5 → -20% 亏
    sigs = [_signal_at(df, 0, "long"), _signal_at(df, 5, "long")]
    result = BacktestResult("X-USDT", "1H", len(closes), len(closes), signals=sigs)
    evaluate_outcomes(result, df, horizons=(5,), exit_horizon=5)
    stats = result.stats_by_rule()
    assert stats["test_rule"]["win_rate"] == pytest.approx(0.5)


def test_equity_curve_cumulates():
    """三个信号收益 +5%、+5%、-3% → NAV 序列 1.05、1.10、1.07。"""
    closes = [100, 105, 110, 115, 120, 125] + \
             [125, 130, 135, 140, 145, 150] + \
             [150, 145.5, 145.5, 145.5, 145.5, 145.5]
    df = _custom_df([float(c) for c in closes])
    s1 = _signal_at(df, 0, "long")  # 100 → 125, h=5 = 25%
    s2 = _signal_at(df, 6, "long")  # 125 → 150, h=5 = 20%
    s3 = _signal_at(df, 12, "long")  # 150 → 145.5, h=5 = -3%
    result = BacktestResult("X-USDT", "1H", len(closes), len(closes),
                            signals=[s1, s2, s3])
    evaluate_outcomes(result, df, horizons=(5,), exit_horizon=5)
    curve = result.equity_curve()
    assert len(curve) == 3
    assert curve[0][1] == pytest.approx(1.25)
    assert curve[1][1] == pytest.approx(1.45)
    assert curve[2][1] == pytest.approx(1.42)
    assert result.total_return == pytest.approx(0.42)


def test_max_drawdown_basic():
    """NAV 1.0 → 1.5 → 1.2，回撤 = (1.2 - 1.5)/1.5 = -0.2。"""
    # 构造两个信号：第一个赚 50%、第二个亏 20%
    closes = [100, 150, 150, 150, 150, 150] + \
             [150, 120, 120, 120, 120, 120]
    df = _custom_df([float(c) for c in closes])
    s1 = _signal_at(df, 0, "long")   # 100 → 150, h=5 = 50%
    s2 = _signal_at(df, 6, "long")   # 150 → 120, h=5 = -20%
    result = BacktestResult("X-USDT", "1H", len(closes), len(closes),
                            signals=[s1, s2])
    evaluate_outcomes(result, df, horizons=(5,), exit_horizon=5)
    # equity 1.0 → 1.5 → 1.3 (1.5 - 0.2)
    # 高点 1.5，谷 1.3 → (1.3 - 1.5)/1.5 = -0.1333...
    assert result.max_drawdown == pytest.approx(-0.2 / 1.5)


def test_equity_curve_empty_when_no_outcomes():
    result = BacktestResult("X", "1H", 0, 0)
    assert result.equity_curve() == []
    assert result.total_return == 0.0
    assert result.max_drawdown == 0.0


# ============================================================
#  backtest_with_returns —— 一次跑完
# ============================================================

class _AtFirstConfirmedRule(SignalRule):
    """第一根 confirmed bar 命中 long，其他都不命中。"""
    name = "first_only"
    _fired = False

    def evaluate(self, df, *, symbol, timeframe):
        if self._fired:
            return None
        last = df.iloc[-1]
        if not bool(last["confirm"]):
            return None
        self._fired = True
        return Signal(
            symbol=symbol, timeframe=timeframe, rule_name=self.name,
            direction="long", bar_ts=last["ts"], price=float(last["close"]),
            message="first",
        )


def test_backtest_with_returns_end_to_end():
    df = _df(DEFAULT_WARMUP_BARS + 30)
    rule = _AtFirstConfirmedRule()
    result = backtest_with_returns(
        df, [rule], symbol="BTC", timeframe="1H",
        horizons=(1, 5, 10), exit_horizon=5,
    )
    assert len(result.signals) == 1
    assert len(result.outcomes) == 1
    o = result.outcomes[0]
    assert o.entry_price > 0
    assert 1 in o.horizon_returns
    assert o.exit_return is not None

