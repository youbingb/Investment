"""PaperAccount 单元测试。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from investment.trader.paper_account import PaperAccount
from investment.trader.order import Order, Position, Trade


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "paper_account.json"


@pytest.fixture
def account(tmp_state: Path) -> PaperAccount:
    return PaperAccount(initial_balance=10000.0, state_path=tmp_state)


class TestPaperAccountInit:
    def test_new_account(self, account: PaperAccount) -> None:
        assert account.balance == 10000.0
        assert account.positions == {}
        assert account.trades == []
        assert account.orders == []

    def test_persistence_on_init(self, tmp_state: Path) -> None:
        # 新建时自动保存
        PaperAccount(initial_balance=5000.0, state_path=tmp_state)
        assert tmp_state.exists()
        data = json.loads(tmp_state.read_text(encoding="utf-8"))
        assert data["balance"] == 5000.0

    def test_restore_from_file(self, tmp_state: Path) -> None:
        # 先建一个并开仓
        acc1 = PaperAccount(initial_balance=10000.0, state_path=tmp_state)
        acc1.open_position("BTC-USDT", "long", 0.1, 50000.0)
        assert acc1.balance == 5000.0

        # 从文件恢复
        acc2 = PaperAccount(initial_balance=99999.0, state_path=tmp_state)
        assert acc2.balance == 5000.0  # 从文件恢复，不是 99999
        assert acc2.has_position("BTC-USDT", "long")


class TestOpenPosition:
    def test_basic_open(self, account: PaperAccount) -> None:
        order = account.open_position(
            "BTC-USDT", "long", 0.1, 50000.0,
            stop_loss_price=48000.0, take_profit_price=55000.0,
        )
        assert order.status.value == "filled"
        assert account.balance == 5000.0  # 10000 - 0.1*50000
        assert account.has_position("BTC-USDT", "long")

        pos = account.get_position("BTC-USDT", "long")
        assert pos is not None
        assert pos.quantity == 0.1
        assert pos.avg_entry_price == 50000.0
        assert pos.stop_loss_price == 48000.0
        assert pos.take_profit_price == 55000.0

    def test_insufficient_balance(self, account: PaperAccount) -> None:
        with pytest.raises(ValueError, match="余额不足"):
            account.open_position("BTC-USDT", "long", 1.0, 50000.0)

    def test_add_position(self, account: PaperAccount) -> None:
        account.open_position("BTC-USDT", "long", 0.1, 50000.0)
        account.open_position("BTC-USDT", "long", 0.05, 60000.0)

        pos = account.get_position("BTC-USDT", "long")
        assert pos is not None
        assert pos.quantity == pytest.approx(0.15)
        # 加权均价: (50000*0.1 + 60000*0.05) / 0.15 = 53333.33
        assert pos.avg_entry_price == pytest.approx(53333.33, rel=1e-3)

    def test_short_position(self, account: PaperAccount) -> None:
        order = account.open_position("ETH-USDT", "short", 1.0, 3000.0)
        assert order.side.value == "sell"
        assert account.balance == 7000.0  # 10000 - 1*3000
        assert account.has_position("ETH-USDT", "short")


class TestClosePosition:
    def test_close_long_profit(self, account: PaperAccount) -> None:
        account.open_position("BTC-USDT", "long", 0.1, 50000.0)
        trade = account.close_position("BTC-USDT", "long", 55000.0, "signal")

        assert trade is not None
        assert trade.pnl == pytest.approx(500.0)  # (55000-50000)*0.1
        assert trade.pnl_pct == pytest.approx(0.1)  # 10%
        assert trade.is_win
        assert account.balance == pytest.approx(10500.0)  # 5000 + 0.1*55000
        assert not account.has_position("BTC-USDT", "long")

    def test_close_long_loss(self, account: PaperAccount) -> None:
        account.open_position("BTC-USDT", "long", 0.1, 50000.0)
        trade = account.close_position("BTC-USDT", "long", 45000.0, "stop_loss")

        assert trade is not None
        assert trade.pnl == pytest.approx(-500.0)  # (45000-50000)*0.1
        assert not trade.is_win
        assert trade.exit_reason == "stop_loss"
        assert account.balance == pytest.approx(9500.0)

    def test_close_short_profit(self, account: PaperAccount) -> None:
        account.open_position("ETH-USDT", "short", 1.0, 3000.0)
        trade = account.close_position("ETH-USDT", "short", 2500.0, "signal")

        assert trade is not None
        assert trade.pnl == pytest.approx(500.0)  # (3000-2500)*1
        assert trade.is_win

    def test_close_nonexistent(self, account: PaperAccount) -> None:
        trade = account.close_position("BTC-USDT", "long", 50000.0)
        assert trade is None


class TestStopLossTakeProfit:
    def test_long_stop_loss(self, account: PaperAccount) -> None:
        account.open_position(
            "BTC-USDT", "long", 0.1, 50000.0,
            stop_loss_price=48000.0,
        )
        triggered = account.check_stop_loss_take_profit("BTC-USDT", 47000.0)
        assert len(triggered) == 1
        assert triggered[0] == ("BTC-USDT", "long", 47000.0)

    def test_long_take_profit(self, account: PaperAccount) -> None:
        account.open_position(
            "BTC-USDT", "long", 0.1, 50000.0,
            take_profit_price=55000.0,
        )
        triggered = account.check_stop_loss_take_profit("BTC-USDT", 56000.0)
        assert len(triggered) == 1

    def test_no_trigger_within_range(self, account: PaperAccount) -> None:
        account.open_position(
            "BTC-USDT", "long", 0.1, 50000.0,
            stop_loss_price=48000.0, take_profit_price=55000.0,
        )
        triggered = account.check_stop_loss_take_profit("BTC-USDT", 50000.0)
        assert len(triggered) == 0

    def test_short_stop_loss(self, account: PaperAccount) -> None:
        account.open_position(
            "ETH-USDT", "short", 1.0, 3000.0,
            stop_loss_price=3200.0,
        )
        triggered = account.check_stop_loss_take_profit("ETH-USDT", 3300.0)
        assert len(triggered) == 1

    def test_wrong_symbol_no_trigger(self, account: PaperAccount) -> None:
        account.open_position(
            "BTC-USDT", "long", 0.1, 50000.0,
            stop_loss_price=48000.0,
        )
        triggered = account.check_stop_loss_take_profit("ETH-USDT", 47000.0)
        assert len(triggered) == 0


class TestSnapshot:
    def test_snapshot_basic(self, account: PaperAccount) -> None:
        snap = account.snapshot()
        assert snap.balance == 10000.0
        assert snap.total_trades == 0
        assert snap.win_rate == 0.0
        assert snap.open_positions_count == 0

    def test_snapshot_with_positions(self, account: PaperAccount) -> None:
        account.open_position("BTC-USDT", "long", 0.1, 50000.0)
        snap = account.snapshot({"BTC-USDT": 52000.0})
        assert snap.open_positions_count == 1
        assert snap.unrealized_pnl == pytest.approx(200.0)  # (52000-50000)*0.1

    def test_snapshot_with_trades(self, account: PaperAccount) -> None:
        account.open_position("BTC-USDT", "long", 0.1, 50000.0)
        account.close_position("BTC-USDT", "long", 55000.0, "signal")
        snap = account.snapshot()
        assert snap.total_trades == 1
        assert snap.win_count == 1
        assert snap.win_rate == 1.0
        assert snap.total_pnl == pytest.approx(500.0)


class TestPersistence:
    def test_save_on_every_operation(self, account: PaperAccount, tmp_state: Path) -> None:
        account.open_position("BTC-USDT", "long", 0.1, 50000.0)
        assert tmp_state.exists()
        data = json.loads(tmp_state.read_text(encoding="utf-8"))
        assert len(data["orders"]) == 1
        assert "BTC-USDT:long" in data["positions"]

    def test_atomic_write(self, account: PaperAccount, tmp_state: Path) -> None:
        account.open_position("BTC-USDT", "long", 0.1, 50000.0)
        # tmp 文件应该不存在（已被 rename）
        assert not tmp_state.with_suffix(".tmp").exists()


class TestReset:
    def test_reset(self, account: PaperAccount) -> None:
        account.open_position("BTC-USDT", "long", 0.1, 50000.0)
        account.close_position("BTC-USDT", "long", 55000.0, "signal")
        account.reset()
        assert account.balance == 10000.0
        assert account.positions == {}
        assert account.trades == []
