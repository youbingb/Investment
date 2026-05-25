"""阶段 3 信号引擎单元测试 — 规则逻辑、loader 装配。"""
from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from investment.signals.base import Signal, SignalRule
from investment.signals.examples.dot_pullback import DotPullbackRule
from investment.signals.examples.golden_cross import GoldenCrossRule
from investment.signals.loader import REGISTRY, load_rules


# ---- helper：构造一根包含完整指标列的 DataFrame ----

def _make_df_with_indicators(
    n: int,
    fast_vals: list[float],
    slow_vals: list[float],
    dot60_vals: list[float] | None = None,
    low_vals: list[float] | None = None,
    confirm_last: bool = True,
) -> pd.DataFrame:
    """构造一个最小的 df，含 evaluate 需要的所有列。

    fast_vals / slow_vals / dot60_vals / low_vals 必须等长 n。
    """
    assert len(fast_vals) == n
    assert len(slow_vals) == n
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame({
        "ts": idx,
        "open": np.zeros(n),
        "high": np.zeros(n),
        "low": low_vals if low_vals is not None else np.zeros(n),
        "close": np.array(slow_vals) + 1.0,  # 任意，仅用于 message
        "vol": np.zeros(n),
        "ema20": fast_vals,
        "sma60": slow_vals,
        "dot60": dot60_vals if dot60_vals is not None else [np.nan] * n,
        "confirm": [True] * (n - 1) + [confirm_last],
    })
    return df


# ============================================================
#  GoldenCrossRule
# ============================================================

def test_golden_cross_hit_long():
    df = _make_df_with_indicators(
        n=3,
        fast_vals=[10.0, 10.0, 12.0],   # 倒数第 2 fast=10, 最末 fast=12
        slow_vals=[11.0, 11.0, 11.0],   # 倒数第 2 fast<slow, 最末 fast>slow → 上穿
    )
    rule = GoldenCrossRule()
    sig = rule.evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None
    assert sig.direction == "long"
    assert sig.rule_name == "golden_cross"
    assert "金叉" in sig.message


def test_golden_cross_hit_short():
    df = _make_df_with_indicators(
        n=3,
        fast_vals=[12.0, 12.0, 10.0],   # 倒数第 2 fast>slow, 最末 fast<slow → 下穿
        slow_vals=[11.0, 11.0, 11.0],
    )
    rule = GoldenCrossRule()
    sig = rule.evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None
    assert sig.direction == "short"
    assert "死叉" in sig.message


def test_golden_cross_no_cross_returns_none():
    # 始终 fast > slow，不构成新的上穿（prev 已经满足 fast>slow）
    df = _make_df_with_indicators(
        n=3,
        fast_vals=[12.0, 12.5, 13.0],
        slow_vals=[11.0, 11.0, 11.0],
    )
    rule = GoldenCrossRule()
    assert rule.evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_golden_cross_skips_unconfirmed_last_bar():
    # 即使数值满足上穿，最末 bar confirm=False 不应触发
    df = _make_df_with_indicators(
        n=3,
        fast_vals=[10.0, 10.0, 12.0],
        slow_vals=[11.0, 11.0, 11.0],
        confirm_last=False,
    )
    # confirm_last=False 后，confirmed 只剩 2 根，需要 ≥2 根
    # 但前 2 根没有形成交叉 → None
    rule = GoldenCrossRule()
    assert rule.evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_golden_cross_nan_skipped():
    df = _make_df_with_indicators(
        n=3,
        fast_vals=[np.nan, 10.0, 12.0],
        slow_vals=[11.0, 11.0, 11.0],
    )
    # 倒数第 2 fast=10, slow=11; 最末 fast=12, slow=11 → 仍然会上穿
    # NaN 在更早的位置，不影响 last_two
    rule = GoldenCrossRule()
    assert rule.evaluate(df, symbol="BTC-USDT", timeframe="1H") is not None


def test_golden_cross_missing_column_returns_none():
    df = _make_df_with_indicators(
        n=3,
        fast_vals=[10.0, 11.0, 12.0],
        slow_vals=[11.0, 11.0, 11.0],
    ).drop(columns=["sma60"])
    rule = GoldenCrossRule()
    assert rule.evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


# ============================================================
#  DotPullbackRule
# ============================================================

def test_dot_pullback_hit_when_low_equals_dot():
    # 最末根 low=100, dot60=100 → 偏离 0% ≤ 阈值
    df = _make_df_with_indicators(
        n=2,
        fast_vals=[0, 0],
        slow_vals=[0, 0],
        dot60_vals=[99.0, 100.0],
        low_vals=[99.0, 100.0],
    )
    rule = DotPullbackRule()
    sig = rule.evaluate(df, symbol="BTC-USDT", timeframe="1H")
    assert sig is not None
    assert sig.direction == "long"
    assert sig.extra["deviation_pct"] == 0.0


def test_dot_pullback_misses_when_far_away():
    # low=110, dot60=100 → 偏离 10% > 0.5%
    df = _make_df_with_indicators(
        n=2,
        fast_vals=[0, 0],
        slow_vals=[0, 0],
        dot60_vals=[99.0, 100.0],
        low_vals=[105.0, 110.0],
    )
    rule = DotPullbackRule()
    assert rule.evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


def test_dot_pullback_tolerance_param_works():
    # 偏离 0.4%，默认 0.5% 命中；改成 0.3% 不命中
    df = _make_df_with_indicators(
        n=2,
        fast_vals=[0, 0],
        slow_vals=[0, 0],
        dot60_vals=[100.0, 100.0],
        low_vals=[100.0, 100.4],
    )
    assert DotPullbackRule().evaluate(df, symbol="BTC-USDT", timeframe="1H") is not None
    assert DotPullbackRule(params={"tolerance_pct": 0.3}).evaluate(
        df, symbol="BTC-USDT", timeframe="1H"
    ) is None


def test_dot_pullback_nan_dot_returns_none():
    df = _make_df_with_indicators(
        n=2,
        fast_vals=[0, 0],
        slow_vals=[0, 0],
        dot60_vals=[np.nan, np.nan],
        low_vals=[100.0, 100.0],
    )
    rule = DotPullbackRule()
    assert rule.evaluate(df, symbol="BTC-USDT", timeframe="1H") is None


# ============================================================
#  load_rules
# ============================================================

def test_load_rules_default_config_empty():
    """默认 config/signals.yaml 中两条规则都 enabled=false，应返回空列表。"""
    rules = load_rules()
    assert rules == []


def test_load_rules_enabled_from_temp_yaml(tmp_path: Path):
    cfg = tmp_path / "signals.yaml"
    cfg.write_text(
        textwrap.dedent("""
            rules:
              golden_cross:
                enabled: true
                fast: ema20
                slow: sma60
              dot_pullback:
                enabled: false
        """).strip(),
        encoding="utf-8",
    )
    rules = load_rules(config_path=cfg)
    assert len(rules) == 1
    assert rules[0].name == "golden_cross"
    assert rules[0].params["fast"] == "ema20"


def test_load_rules_unknown_rule_is_skipped(tmp_path: Path):
    cfg = tmp_path / "signals.yaml"
    cfg.write_text(
        textwrap.dedent("""
            rules:
              imaginary_rule:
                enabled: true
              golden_cross:
                enabled: true
        """).strip(),
        encoding="utf-8",
    )
    rules = load_rules(config_path=cfg)
    assert len(rules) == 1
    assert rules[0].name == "golden_cross"


def test_load_rules_missing_file_returns_empty(tmp_path: Path):
    rules = load_rules(config_path=tmp_path / "nope.yaml")
    assert rules == []


def test_registry_contains_examples():
    assert "golden_cross" in REGISTRY
    assert "dot_pullback" in REGISTRY


# ============================================================
#  Signal dataclass
# ============================================================

def test_signal_dedup_key():
    ts = pd.Timestamp("2024-01-01", tz="UTC")
    s = Signal(
        symbol="BTC-USDT", timeframe="1H",
        rule_name="golden_cross", direction="long",
        bar_ts=ts, price=100.0, message="x",
    )
    assert s.dedup_key() == ("BTC-USDT", "1H", "golden_cross", ts)
