"""TradeExecutor 单元测试。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from investment.signals.base import Signal
from investment.trader.executor import TradeExecutor
from investment.trader.paper_account import PaperAccount


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "paper_account.json"


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "trading.yaml"
    cfg.write_text(
        yaml.dump({
            "enabled": True,
            "initial_balance": 10000,
            "position": {
                "size_pct": 0.10,
                "max_amount": 5000,
                "min_amount": 50,
            },
            "risk": {
                "stop_loss_pct": 3.0,
                "take_profit_pct": 6.0,
                "max_open_positions": 3,
                "max_positions_per_symbol": 1,
            },
            "exit_strategy": {
                "method": [{"name": "fixed_odds", "odds_ratio": 3.0}],
                "fixed_odds": {"odds_ratio": 3.0},
            },
            "rules": {"allow": [], "deny": []},
            "directions": {"long": True, "short": True},
        }),
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def account(tmp_state: Path) -> PaperAccount:
    return PaperAccount(initial_balance=10000.0, state_path=tmp_state)


@pytest.fixture
def executor(account: PaperAccount, tmp_config: Path) -> TradeExecutor:
    return TradeExecutor(account, config_path=tmp_config)


def _make_signal(
    symbol: str = "BTC-USDT",
    direction: str = "long",
    rule_name: str = "golden_cross",
    price: float = 50000.0,
    bar_ts: Any = None,
) -> Signal:
    import pandas as pd
    return Signal(
        symbol=symbol,
        timeframe="1H",
        rule_name=rule_name,
        direction=direction,
        bar_ts=bar_ts or pd.Timestamp("2026-01-01", tz="UTC"),
        price=price,
        message=f"{direction.upper()} {symbol} @ {price}",
    )


class TestProcessSignals:
    def test_basic_long_signal(self, executor: TradeExecutor, account: PaperAccount) -> None:
        sig = _make_signal(direction="long", price=50000.0)
        results = executor.process_signals([sig], {"BTC-USDT": 50000.0})

        assert len(results) == 1
        r = results[0]
        assert r["action"] == "open"
        assert r["direction"] == "long"
        assert r["symbol"] == "BTC-USDT"
        assert r["quantity"] > 0
        assert account.has_position("BTC-USDT", "long")

    def test_short_signal(self, executor: TradeExecutor, account: PaperAccount) -> None:
        sig = _make_signal(direction="short", price=3000.0)
        results = executor.process_signals([sig], {"BTC-USDT": 3000.0})

        assert results[0]["action"] == "open"
        assert account.has_position("BTC-USDT", "short")

    def test_neutral_signal_skipped(self, executor: TradeExecutor) -> None:
        sig = _make_signal(direction="neutral")
        results = executor.process_signals([sig])
        assert results[0]["action"] == "skip"

    def test_reverse_signal_closes_old(self, executor: TradeExecutor, account: PaperAccount) -> None:
        # 先开多
        sig1 = _make_signal(direction="long", price=50000.0)
        executor.process_signals([sig1], {"BTC-USDT": 50000.0})
        assert account.has_position("BTC-USDT", "long")

        # 反向信号 → 先平多，再开空
        sig2 = _make_signal(direction="short", price=48000.0)
        results = executor.process_signals([sig2], {"BTC-USDT": 48000.0})

        assert "closed_position" in results[0]
        assert results[0]["action"] == "open"
        assert account.has_position("BTC-USDT", "short")
        assert not account.has_position("BTC-USDT", "long")

    def test_add_position(self, executor: TradeExecutor, account: PaperAccount) -> None:
        sig1 = _make_signal(direction="long", price=50000.0)
        executor.process_signals([sig1], {"BTC-USDT": 50000.0})

        # 同向信号 → 加仓（max_positions_per_symbol 只阻止新开，不阻止加仓）
        sig2 = _make_signal(direction="long", price=51000.0)
        results = executor.process_signals([sig2], {"BTC-USDT": 51000.0})
        assert results[0]["action"] == "add_position"

    def test_max_positions_per_symbol(self, executor: TradeExecutor, account: PaperAccount) -> None:
        """先开多，平仓，再用新信号开空 — 验证 max_positions_per_symbol 限制。"""
        sig1 = _make_signal(direction="long", price=50000.0)
        executor.process_signals([sig1], {"BTC-USDT": 50000.0})

        # 平掉多仓
        account.close_position("BTC-USDT", "long", 51000.0, "signal")

        # 再开多 — 应该允许，因为没有持仓了
        sig2 = _make_signal(direction="long", price=52000.0)
        results = executor.process_signals([sig2], {"BTC-USDT": 52000.0})
        assert results[0]["action"] == "open"


class TestRiskManagement:
    def test_max_open_positions(self, executor: TradeExecutor, account: PaperAccount) -> None:
        """max_open_positions=3，第 4 个信号应该被跳过。"""
        for i, sym in enumerate(["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"]):
            sig = _make_signal(symbol=sym, direction="long", price=1000.0 * (i + 1))
            results = executor.process_signals([sig], {sym: 1000.0 * (i + 1)})
            if i < 3:
                assert results[0]["action"] == "open"
            else:
                assert results[0]["action"] == "skip"
                assert "最大持仓数" in results[0]["reason"]

    def test_rule_filter_allow(self, account: PaperAccount, tmp_config: Path) -> None:
        # 只允许 golden_cross
        cfg = yaml.safe_load(tmp_config.read_text(encoding="utf-8"))
        cfg["rules"]["allow"] = ["golden_cross"]
        tmp_config.write_text(yaml.dump(cfg), encoding="utf-8")

        executor = TradeExecutor(account, config_path=tmp_config)

        # 允许的规则
        sig1 = _make_signal(rule_name="golden_cross", price=50000.0)
        r1 = executor.process_signals([sig1], {"BTC-USDT": 50000.0})
        assert r1[0]["action"] == "open"

        # 不允许的规则
        sig2 = _make_signal(rule_name="dot_pullback", price=50000.0)
        r2 = executor.process_signals([sig2], {"BTC-USDT": 50000.0})
        assert r2[0]["action"] == "skip"

    def test_rule_filter_deny(self, account: PaperAccount, tmp_config: Path) -> None:
        cfg = yaml.safe_load(tmp_config.read_text(encoding="utf-8"))
        cfg["rules"]["deny"] = ["golden_cross"]
        tmp_config.write_text(yaml.dump(cfg), encoding="utf-8")

        executor = TradeExecutor(account, config_path=tmp_config)

        sig = _make_signal(rule_name="golden_cross", price=50000.0)
        r = executor.process_signals([sig], {"BTC-USDT": 50000.0})
        assert r[0]["action"] == "skip"

    def test_direction_filter(self, account: PaperAccount, tmp_config: Path) -> None:
        cfg = yaml.safe_load(tmp_config.read_text(encoding="utf-8"))
        cfg["directions"]["short"] = False
        tmp_config.write_text(yaml.dump(cfg), encoding="utf-8")

        executor = TradeExecutor(account, config_path=tmp_config)

        sig = _make_signal(direction="short", price=50000.0)
        r = executor.process_signals([sig], {"BTC-USDT": 50000.0})
        assert r[0]["action"] == "skip"


class TestStopLossCalculation:
    def test_long_stop_loss_take_profit(self, executor: TradeExecutor) -> None:
        sig = _make_signal(direction="long", price=50000.0)
        results = executor.process_signals([sig], {"BTC-USDT": 50000.0})
        r = results[0]
        # stop_loss_pct=3% → 48500
        # fixed_odds 1:3 → risk=1500, reward=4500, tp=54500
        assert r["stop_loss"] == pytest.approx(48500.0)
        assert r["take_profit"] == pytest.approx(54500.0)
        assert r["exit_strategy"] == "fixed_odds"
        assert "1:3.0" in r["odds_ratio"]

    def test_short_stop_loss_take_profit(self, executor: TradeExecutor) -> None:
        sig = _make_signal(direction="short", price=50000.0)
        results = executor.process_signals([sig], {"BTC-USDT": 50000.0})
        r = results[0]
        # stop_loss_pct=3% → 51500
        # fixed_odds 1:3 → risk=1500, reward=4500, tp=45500
        assert r["stop_loss"] == pytest.approx(51500.0)
        assert r["take_profit"] == pytest.approx(45500.0)

    def test_custom_odds_ratio(self, account: PaperAccount, tmp_config: Path) -> None:
        """自定义赔率 1:5。"""
        cfg = yaml.safe_load(tmp_config.read_text(encoding="utf-8"))
        cfg["exit_strategy"] = {
            "method": [{"name": "fixed_odds", "odds_ratio": 5.0}],
        }
        tmp_config.write_text(yaml.dump(cfg), encoding="utf-8")
        executor = TradeExecutor(account, config_path=tmp_config)

        sig = _make_signal(direction="long", price=50000.0)
        results = executor.process_signals([sig], {"BTC-USDT": 50000.0})
        r = results[0]
        # risk=1500, reward=1500*5=7500, tp=57500
        assert r["take_profit"] == pytest.approx(57500.0)


class TestCheckPositions:
    def test_trigger_stop_loss(self, executor: TradeExecutor, account: PaperAccount) -> None:
        sig = _make_signal(direction="long", price=50000.0)
        executor.process_signals([sig], {"BTC-USDT": 50000.0})

        # 价格跌破止损
        results = executor.check_positions({"BTC-USDT": 48000.0})
        assert len(results) == 1
        assert results[0]["action"] == "close"
        assert results[0]["reason"] == "stop_loss/take_profit"
        assert not account.has_position("BTC-USDT", "long")

    def test_trigger_take_profit(self, executor: TradeExecutor, account: PaperAccount) -> None:
        sig = _make_signal(direction="long", price=50000.0)
        executor.process_signals([sig], {"BTC-USDT": 50000.0})

        # 止盈 54500，55000 足够触发
        results = executor.check_positions({"BTC-USDT": 55000.0})
        assert len(results) == 1
        assert not account.has_position("BTC-USDT", "long")


class TestDisabledTrading:
    def test_disabled(self, account: PaperAccount, tmp_config: Path) -> None:
        cfg = yaml.safe_load(tmp_config.read_text(encoding="utf-8"))
        cfg["enabled"] = False
        tmp_config.write_text(yaml.dump(cfg), encoding="utf-8")

        executor = TradeExecutor(account, config_path=tmp_config)
        sig = _make_signal()
        results = executor.process_signals([sig], {"BTC-USDT": 50000.0})
        assert results == []
