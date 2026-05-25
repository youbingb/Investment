"""信号规则抽象基类与 Signal 数据结构。

每个具体规则继承 ``SignalRule``，实现 ``evaluate(df, params)``。
返回 ``Optional[Signal]``：None = 本根 K 线无信号；Signal = 命中。

判定方法约定：
- 只看最末一根 ``confirm=True`` 的 K 线（未收盘的不评估，避免抖动误报）
- 需要"上穿/下穿"语义时，比较倒数第 1 / 倒数第 2 根 confirmed bar
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd


@dataclass(frozen=True)
class Signal:
    """一次信号命中的载荷。

    Attributes:
        symbol: 例如 ``"BTC-USDT"``
        timeframe: 例如 ``"1H"``
        rule_name: 规则唯一名，对应 ``config/signals.yaml`` 的 key
        direction: ``"long"`` / ``"short"`` / ``"neutral"``
        bar_ts: 命中那根 K 线的收盘时间 (UTC)
        price: 命中时的 close
        message: 人类可读的描述（飞书消息直接用）
        extra: 规则特定的额外信息（如交叉的两根均线值）
    """
    symbol: str
    timeframe: str
    rule_name: str
    direction: str
    bar_ts: pd.Timestamp
    price: float
    message: str
    extra: dict[str, Any] = field(default_factory=dict)

    def dedup_key(self) -> tuple[str, str, str, pd.Timestamp]:
        """同一 (symbol, timeframe, rule_name, bar_ts) 视为同一信号，不重复发送。"""
        return (self.symbol, self.timeframe, self.rule_name, self.bar_ts)


class SignalRule(ABC):
    """规则抽象基类。

    实现要求：
    - ``name`` 类属性必须唯一，对应 yaml key
    - ``evaluate`` 返回 None 表示未命中；返回 Signal 表示命中
    - 实现内禁止修改入参 df
    """

    name: str = ""

    def __init__(self, params: Optional[dict[str, Any]] = None) -> None:
        self.params = params or {}

    @abstractmethod
    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
    ) -> Optional[Signal]: ...

    # -- 工具方法 ----------------------------------------------------

    @staticmethod
    def confirmed(df: pd.DataFrame) -> pd.DataFrame:
        """只取已收盘的 K 线。"""
        return df[df["confirm"]] if "confirm" in df.columns else df

    @staticmethod
    def last_two_confirmed(df: pd.DataFrame) -> Optional[tuple[pd.Series, pd.Series]]:
        """返回 (前一根, 最末根) 已收盘 K 线，不足 2 根返回 None。"""
        c = SignalRule.confirmed(df)
        if len(c) < 2:
            return None
        return c.iloc[-2], c.iloc[-1]


__all__ = ["Signal", "SignalRule"]
