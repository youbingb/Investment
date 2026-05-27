"""交易相关的数据结构：订单、持仓、成交记录。

设计要点：
- 所有字段都可 JSON 序列化（方便持久化）
- direction: "long" / "short"（与 Signal.direction 一致）
- status: pending → filled / rejected / cancelled
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import uuid


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Order:
    """一笔订单。

    Attributes:
        order_id: 唯一 ID
        symbol: 交易对，如 "BTC-USDT"
        side: buy / sell
        order_type: market / limit
        quantity: 下单数量（标的币的数量）
        price: 成交价（模拟盘用信号价 or 市价）
        status: 订单状态
        created_at: 下单时间
        filled_at: 成交时间
        signal_direction: 触发信号的方向 "long"/"short"
        signal_rule: 触发信号的规则名
        signal_message: 信号描述
        stop_loss_price: 止损价（可选）
        take_profit_price: 止盈价（可选）
        extra: 附加信息
    """
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: OrderStatus = OrderStatus.PENDING
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    filled_at: Optional[str] = None
    signal_direction: str = ""
    signal_rule: str = ""
    signal_message: str = ""
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status.value,
            "created_at": self.created_at,
            "filled_at": self.filled_at,
            "signal_direction": self.signal_direction,
            "signal_rule": self.signal_rule,
            "signal_message": self.signal_message,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Order:
        return cls(
            order_id=d["order_id"],
            symbol=d["symbol"],
            side=OrderSide(d["side"]),
            order_type=OrderType(d["order_type"]),
            quantity=d["quantity"],
            price=d["price"],
            status=OrderStatus(d["status"]),
            created_at=d["created_at"],
            filled_at=d.get("filled_at"),
            signal_direction=d.get("signal_direction", ""),
            signal_rule=d.get("signal_rule", ""),
            signal_message=d.get("signal_message", ""),
            stop_loss_price=d.get("stop_loss_price"),
            take_profit_price=d.get("take_profit_price"),
            extra=d.get("extra", {}),
        )


@dataclass
class Position:
    """一个标的的持仓。

    Attributes:
        symbol: 交易对
        direction: "long" / "short"
        quantity: 持仓数量
        avg_entry_price: 平均入场价
        opened_at: 首次开仓时间
        stop_loss_price: 止损价
        take_profit_price: 止盈价
        unrealized_pnl: 未实现盈亏（实时计算，不持久化）
    """
    symbol: str
    direction: str
    quantity: float
    avg_entry_price: float
    opened_at: str = ""
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    unrealized_pnl: float = 0.0

    @property
    def notional_value(self) -> float:
        """名义价值（数量 × 入场价）。"""
        return self.quantity * self.avg_entry_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "quantity": self.quantity,
            "avg_entry_price": self.avg_entry_price,
            "opened_at": self.opened_at,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Position:
        return cls(
            symbol=d["symbol"],
            direction=d["direction"],
            quantity=d["quantity"],
            avg_entry_price=d["avg_entry_price"],
            opened_at=d.get("opened_at", ""),
            stop_loss_price=d.get("stop_loss_price"),
            take_profit_price=d.get("take_profit_price"),
        )


@dataclass
class Trade:
    """一笔已完成的交易（从开仓到平仓的完整记录）。

    Attributes:
        trade_id: 唯一 ID
        symbol: 交易对
        direction: "long" / "short"
        entry_price: 入场价
        exit_price: 出场价
        quantity: 数量
        entry_order_id: 入场订单 ID
        exit_order_id: 出场订单 ID
        opened_at: 开仓时间
        closed_at: 平仓时间
        pnl: 盈亏（绝对值）
        pnl_pct: 盈亏百分比
        exit_reason: 平仓原因（signal / stop_loss / take_profit / manual）
        signal_rule: 触发开仓的规则名
    """
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_order_id: str
    exit_order_id: str
    opened_at: str
    closed_at: str
    pnl: float
    pnl_pct: float
    exit_reason: str = ""
    signal_rule: str = ""

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "entry_order_id": self.entry_order_id,
            "exit_order_id": self.exit_order_id,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "exit_reason": self.exit_reason,
            "signal_rule": self.signal_rule,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Trade:
        return cls(**d)


__all__ = [
    "Order", "OrderSide", "OrderStatus", "OrderType",
    "Position", "Trade",
]
