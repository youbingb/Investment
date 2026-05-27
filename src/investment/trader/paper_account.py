"""模拟账户 — 余额、持仓、交易记录、JSON 持久化。

设计要点：
- 纯本地 JSON 文件持久化（data/paper_account.json），重启不丢状态
- 每次写操作后自动保存（atomic write，先写 .tmp 再 rename）
- 余额/持仓操作全部在内存完成，save() 只做序列化
- 支持多标的同时持仓（每个 symbol+direction 只有一个 Position）
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from investment.logger import logger
from investment.trader.order import (
    Order, OrderSide, OrderStatus, OrderType,
    Position, Trade,
)

DEFAULT_PAPER_STATE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "paper_account.json"
)


@dataclass
class AccountSnapshot:
    """账户快照（只读，用于展示/汇报）。"""
    balance: float
    positions: list[Position]
    total_pnl: float
    total_trades: int
    win_count: int
    win_rate: float
    open_positions_count: int
    unrealized_pnl: float


class PaperAccount:
    """模拟交易账户。

    用法：
        account = PaperAccount(initial_balance=10000)
        order = account.open_position("BTC-USDT", "long", 0.001, 50000.0, ...)
        account.close_position("BTC-USDT", "long", 51000.0, "signal", order.order_id)
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        state_path: Optional[Path] = None,
    ) -> None:
        self._state_path = state_path or DEFAULT_PAPER_STATE_PATH
        self._initial_balance = initial_balance
        self._balance: float = initial_balance
        self._positions: dict[str, Position] = {}  # key = "symbol:direction"
        self._orders: list[Order] = []
        self._trades: list[Trade] = []

        # 尝试从文件恢复
        if self._state_path.exists():
            self._load()
            logger.info(
                f"模拟账户已从 {self._state_path} 恢复，"
                f"余额={self._balance:.2f} 持仓={len(self._positions)}"
            )
        else:
            logger.info(f"新建模拟账户，初始余额={initial_balance:.2f}")
            self.save()

    # ---- 查询 ----

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    @property
    def trades(self) -> list[Trade]:
        return list(self._trades)

    @property
    def orders(self) -> list[Order]:
        return list(self._orders)

    def get_position(self, symbol: str, direction: str) -> Optional[Position]:
        return self._positions.get(f"{symbol}:{direction}")

    def has_position(self, symbol: str, direction: str) -> bool:
        return f"{symbol}:{direction}" in self._positions

    def snapshot(self, current_prices: Optional[dict[str, float]] = None) -> AccountSnapshot:
        """生成账户快照。current_prices = {"BTC-USDT": 50000, ...} 用于算未实现盈亏。"""
        prices = current_prices or {}
        unrealized = 0.0
        for key, pos in self._positions.items():
            price = prices.get(pos.symbol)
            if price is not None:
                if pos.direction == "long":
                    unrealized += (price - pos.avg_entry_price) * pos.quantity
                else:  # short
                    unrealized += (pos.avg_entry_price - price) * pos.quantity

        trades = self._trades
        wins = sum(1 for t in trades if t.is_win)
        total_pnl = sum(t.pnl for t in trades)

        return AccountSnapshot(
            balance=self._balance,
            positions=list(self._positions.values()),
            total_pnl=total_pnl,
            total_trades=len(trades),
            win_count=wins,
            win_rate=(wins / len(trades)) if trades else 0.0,
            open_positions_count=len(self._positions),
            unrealized_pnl=unrealized,
        )

    # ---- 开仓 ----

    def open_position(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        price: float,
        *,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        signal_rule: str = "",
        signal_message: str = "",
    ) -> Order:
        """开仓：扣减余额，创建持仓和订单。

        如果已有同方向持仓，会加仓（更新均价和数量）。
        """
        key = f"{symbol}:{direction}"
        cost = quantity * price

        if cost > self._balance:
            raise ValueError(
                f"余额不足：需要 {cost:.2f} USDT，当前余额 {self._balance:.2f}"
            )

        # 扣减余额
        self._balance -= cost

        # 创建订单
        side = OrderSide.BUY if direction == "long" else OrderSide.SELL
        order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=price,
            status=OrderStatus.FILLED,
            filled_at=datetime.now(timezone.utc).isoformat(),
            signal_direction=direction,
            signal_rule=signal_rule,
            signal_message=signal_message,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

        # 更新持仓
        if key in self._positions:
            existing = self._positions[key]
            total_qty = existing.quantity + quantity
            existing.avg_entry_price = (
                (existing.avg_entry_price * existing.quantity + price * quantity)
                / total_qty
            )
            existing.quantity = total_qty
            # 更新止损止盈（取最新的）
            if stop_loss_price is not None:
                existing.stop_loss_price = stop_loss_price
            if take_profit_price is not None:
                existing.take_profit_price = take_profit_price
        else:
            self._positions[key] = Position(
                symbol=symbol,
                direction=direction,
                quantity=quantity,
                avg_entry_price=price,
                opened_at=order.created_at,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
            )

        self._orders.append(order)
        logger.info(
            f"开仓：{direction.upper()} {symbol} × {quantity} @ {price:.2f} "
            f"(花费 {cost:.2f} USDT，余额 {self._balance:.2f})"
        )
        self.save()
        return order

    # ---- 平仓 ----

    def close_position(
        self,
        symbol: str,
        direction: str,
        price: float,
        exit_reason: str = "signal",
    ) -> Optional[Trade]:
        """平仓：释放余额，记录交易。

        Returns:
            Trade 记录，如果无持仓返回 None。
        """
        key = f"{symbol}:{direction}"
        pos = self._positions.get(key)
        if pos is None:
            logger.warning(f"平仓失败：无 {direction} {symbol} 持仓")
            return None

        # 计算盈亏
        if direction == "long":
            pnl = (price - pos.avg_entry_price) * pos.quantity
        else:
            pnl = (pos.avg_entry_price - price) * pos.quantity

        pnl_pct = pnl / (pos.avg_entry_price * pos.quantity) if pos.notional_value > 0 else 0.0

        # 释放余额 = 原始成本 + 盈亏
        proceeds = pos.quantity * price
        self._balance += proceeds

        # 创建平仓订单
        side = OrderSide.SELL if direction == "long" else OrderSide.BUY
        exit_order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
            price=price,
            status=OrderStatus.FILLED,
            filled_at=datetime.now(timezone.utc).isoformat(),
            signal_direction=direction,
            signal_rule=exit_reason,
        )
        self._orders.append(exit_order)

        # 记录交易
        trade = Trade(
            trade_id=exit_order.order_id,
            symbol=symbol,
            direction=direction,
            entry_price=pos.avg_entry_price,
            exit_price=price,
            quantity=pos.quantity,
            entry_order_id=self._find_entry_order_id(symbol, direction),
            exit_order_id=exit_order.order_id,
            opened_at=pos.opened_at,
            closed_at=exit_order.filled_at or "",
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            signal_rule=exit_reason,
        )
        self._trades.append(trade)

        # 移除持仓
        del self._positions[key]

        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        logger.info(
            f"平仓：{direction.upper()} {symbol} × {pos.quantity} @ {price:.2f} "
            f"→ {emoji} PnL={pnl:+.2f} ({pnl_pct:+.2%}) [{exit_reason}] "
            f"余额={self._balance:.2f}"
        )
        self.save()
        return trade

    # ---- 止盈止损检查 ----

    def check_stop_loss_take_profit(
        self, symbol: str, current_price: float
    ) -> list[tuple[str, str, float]]:
        """检查所有持仓的止损/止盈。

        Returns:
            触发列表 [(symbol, direction, current_price), ...]
        """
        triggered: list[tuple[str, str, float]] = []
        for key, pos in list(self._positions.items()):
            if pos.symbol != symbol:
                continue

            if pos.direction == "long":
                if pos.stop_loss_price and current_price <= pos.stop_loss_price:
                    triggered.append((symbol, "long", current_price))
                    logger.info(
                        f"止损触发：LONG {symbol} @ {current_price:.2f} "
                        f"(止损价 {pos.stop_loss_price:.2f})"
                    )
                elif pos.take_profit_price and current_price >= pos.take_profit_price:
                    triggered.append((symbol, "long", current_price))
                    logger.info(
                        f"止盈触发：LONG {symbol} @ {current_price:.2f} "
                        f"(止盈价 {pos.take_profit_price:.2f})"
                    )
            elif pos.direction == "short":
                if pos.stop_loss_price and current_price >= pos.stop_loss_price:
                    triggered.append((symbol, "short", current_price))
                    logger.info(
                        f"止损触发：SHORT {symbol} @ {current_price:.2f} "
                        f"(止损价 {pos.stop_loss_price:.2f})"
                    )
                elif pos.take_profit_price and current_price <= pos.take_profit_price:
                    triggered.append((symbol, "short", current_price))
                    logger.info(
                        f"止盈触发：SHORT {symbol} @ {current_price:.2f} "
                        f"(止盈价 {pos.take_profit_price:.2f})"
                    )

        return triggered

    # ---- 持久化 ----

    def save(self) -> None:
        """原子写入 JSON 状态文件。"""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "initial_balance": self._initial_balance,
            "balance": self._balance,
            "positions": {k: v.to_dict() for k, v in self._positions.items()},
            "orders": [o.to_dict() for o in self._orders],
            "trades": [t.to_dict() for t in self._trades],
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = self._state_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._state_path)

    def _load(self) -> None:
        """从 JSON 文件恢复状态。"""
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            self._initial_balance = data.get("initial_balance", self._initial_balance)
            self._balance = data.get("balance", self._initial_balance)
            self._positions = {
                k: Position.from_dict(v)
                for k, v in data.get("positions", {}).items()
            }
            self._orders = [Order.from_dict(o) for o in data.get("orders", [])]
            self._trades = [Trade.from_dict(t) for t in data.get("trades", [])]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"模拟账户状态文件损坏，使用默认值：{e}")
            self._balance = self._initial_balance
            self._positions = {}
            self._orders = []
            self._trades = []

    def _find_entry_order_id(self, symbol: str, direction: str) -> str:
        """找到最近一次开仓订单的 ID。"""
        for o in reversed(self._orders):
            if (
                o.symbol == symbol
                and o.signal_direction == direction
                and o.status == OrderStatus.FILLED
                and o.side == (OrderSide.BUY if direction == "long" else OrderSide.SELL)
            ):
                return o.order_id
        return ""

    def reset(self) -> None:
        """重置账户到初始状态。"""
        self._balance = self._initial_balance
        self._positions.clear()
        self._orders.clear()
        self._trades.clear()
        self.save()
        logger.info(f"模拟账户已重置，余额={self._initial_balance:.2f}")


__all__ = ["PaperAccount", "AccountSnapshot"]
