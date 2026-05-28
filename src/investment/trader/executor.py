"""交易执行器 — 把信号变成实际交易。

职责：
1. 接收 Pipeline 产出的 Signal
2. 根据配置做风控检查（仓位大小、最大持仓、方向过滤、规则过滤）
3. 使用退出策略计算止损止盈价
4. 调用 PaperAccount 执行开仓/平仓
5. 检查已有持仓的止损止盈触发

设计要点：
- 反向信号 = 先平旧仓再开新仓
- 同向信号 = 加仓（PaperAccount 已支持）
- 配置从 config/trading.yaml 读取
- 支持三种退出策略：赔率法、均线密集法、斐波那契法
- 仓位计算使用视频公式：仓位 = 最大亏损 / |开仓价 - 止损价|
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from investment.logger import logger
from investment.signals.base import Signal
from investment.trader.exit_strategies import (
    ExitStrategy,
    FixedOddsExit,
    MAClusterExit,
    FibonacciExit,
    create_exit_strategy,
)
from investment.trader.paper_account import PaperAccount

DEFAULT_TRADING_CONFIG = (
    Path(__file__).resolve().parents[3] / "config" / "trading.yaml"
)


class TradeExecutor:
    """信号驱动的交易执行器。

    用法：
        executor = TradeExecutor(account)
        results = executor.process_signals(signals, current_prices)
    """

    def __init__(
        self,
        account: PaperAccount,
        config_path: Optional[Path] = None,
    ) -> None:
        self.account = account
        self._config = self._load_config(config_path or DEFAULT_TRADING_CONFIG)
        self._exit_strategies = self._init_exit_strategies()

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled", True))

    def _init_exit_strategies(self) -> list[ExitStrategy]:
        """根据配置初始化退出策略列表。"""
        exit_cfg = self._config.get("exit_strategy", {})
        strategies = []

        # 默认使用赔率平仓法
        method = exit_cfg.get("method", "fixed_odds")

        if isinstance(method, str):
            # 单一策略
            params = exit_cfg.get(method, {})
            try:
                strategies.append(create_exit_strategy(method, **params))
            except ValueError as e:
                logger.warning(f"退出策略初始化失败: {e}，使用默认赔率法")
                strategies.append(FixedOddsExit())
        elif isinstance(method, list):
            # 多策略组合（按优先级）
            for m in method:
                if isinstance(m, str):
                    params = exit_cfg.get(m, {})
                    try:
                        strategies.append(create_exit_strategy(m, **params))
                    except ValueError as e:
                        logger.warning(f"退出策略 {m} 初始化失败: {e}")
                elif isinstance(m, dict):
                    name = m.get("name", "fixed_odds")
                    params = {k: v for k, v in m.items() if k != "name"}
                    try:
                        strategies.append(create_exit_strategy(name, **params))
                    except ValueError as e:
                        logger.warning(f"退出策略 {name} 初始化失败: {e}")

        if not strategies:
            logger.warning("没有可用的退出策略，使用默认赔率法 (1:3)")
            strategies.append(FixedOddsExit(odds_ratio=3.0))

        names = [s.name for s in strategies]
        logger.info(f"退出策略: {names}")
        return strategies

    def process_signals(
        self,
        signals: list[Signal],
        current_prices: Optional[dict[str, float]] = None,
        df_map: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """处理一批信号。

        Args:
            signals: Pipeline 产出的信号列表
            current_prices: 当前价格 {"BTC-USDT": 50000, ...}
            df_map: {symbol: DataFrame} 用于均线密集等需要 K 线数据的退出策略

        Returns:
            每个信号的处理结果列表
        """
        if not self.enabled:
            logger.info("交易未启用，跳过信号处理")
            return []

        results: list[dict[str, Any]] = []
        prices = current_prices or {}

        for sig in signals:
            result = self._process_single_signal(sig, prices, df_map)
            results.append(result)

        return results

    def check_positions(self, current_prices: dict[str, float]) -> list[dict[str, Any]]:
        """检查所有持仓的止损止盈。

        Returns:
            触发的平仓结果列表
        """
        if not self.enabled:
            return []

        results: list[dict[str, Any]] = []
        for symbol, price in current_prices.items():
            triggered = self.account.check_stop_loss_take_profit(symbol, price)
            for sym, direction, trigger_price in triggered:
                trade = self.account.close_position(sym, direction, trigger_price, "stop_loss/take_profit")
                if trade:
                    results.append({
                        "action": "close",
                        "symbol": sym,
                        "direction": direction,
                        "price": trigger_price,
                        "pnl": trade.pnl,
                        "pnl_pct": trade.pnl_pct,
                        "reason": "stop_loss/take_profit",
                    })

        return results

    def _process_single_signal(
        self,
        signal: Signal,
        prices: dict[str, float],
        df_map: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """处理单个信号。"""
        result: dict[str, Any] = {
            "signal": signal.rule_name,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "action": "skip",
            "reason": "",
        }

        # 方向过滤
        direction = signal.direction
        if direction == "neutral":
            result["reason"] = "neutral 方向不交易"
            return result
        if not self._config.get("directions", {}).get(direction, True):
            result["reason"] = f"{direction} 方向被配置禁用"
            return result

        # 规则过滤
        rules_cfg = self._config.get("rules", {})
        allow_list = rules_cfg.get("allow", [])
        deny_list = rules_cfg.get("deny", [])
        if allow_list and signal.rule_name not in allow_list:
            result["reason"] = f"规则 {signal.rule_name} 不在允许列表中"
            return result
        if deny_list and signal.rule_name in deny_list:
            result["reason"] = f"规则 {signal.rule_name} 在拒绝列表中"
            return result

        # 反向信号：先平旧仓
        opposite = "short" if direction == "long" else "long"
        if self.account.has_position(signal.symbol, opposite):
            price = prices.get(signal.symbol, signal.price)
            trade = self.account.close_position(
                signal.symbol, opposite, price, "reverse_signal"
            )
            if trade:
                logger.info(
                    f"反向平仓：{opposite.upper()} {signal.symbol} "
                    f"PnL={trade.pnl:+.2f} ({trade.pnl_pct:+.2%})"
                )
                result["closed_position"] = {
                    "direction": opposite,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                }

        # 检查是否已有同向持仓（判断是加仓还是新开）
        is_add = self.account.has_position(signal.symbol, direction)

        # 最大持仓数检查（只在新开仓时检查）
        if not is_add:
            max_open = self._config.get("risk", {}).get("max_open_positions", 0)
            if max_open > 0:
                open_count = len(self.account.positions)
                if open_count >= max_open:
                    result["reason"] = f"已达最大持仓数 {max_open}"
                    return result

            max_per_sym = self._config.get("risk", {}).get("max_positions_per_symbol", 1)
            if max_per_sym > 0:
                sym_count = sum(
                    1 for k in self.account.positions
                    if k.startswith(signal.symbol + ":")
                )
                if sym_count >= max_per_sym:
                    result["reason"] = f"该 symbol 已达最大持仓数 {max_per_sym}"
                    return result

        # 计算止损
        price = prices.get(signal.symbol, signal.price)
        risk_cfg = self._config.get("risk", {})
        stop_loss_pct = risk_cfg.get("stop_loss_pct", 3.0) / 100

        if direction == "long":
            stop_loss = price * (1 - stop_loss_pct)
        else:
            stop_loss = price * (1 + stop_loss_pct)

        # 使用退出策略计算止盈（按优先级尝试）
        take_profit = None
        used_strategy = ""
        df = df_map.get(signal.symbol) if df_map else None

        for strategy in self._exit_strategies:
            try:
                tp = strategy.calc_take_profit(
                    entry_price=price,
                    stop_loss_price=stop_loss,
                    direction=direction,
                    df=df,
                )
                if tp is not None:
                    # 验证止盈方向正确
                    if direction == "long" and tp > price:
                        take_profit = tp
                        used_strategy = strategy.name
                        break
                    elif direction == "short" and tp < price:
                        take_profit = tp
                        used_strategy = strategy.name
                        break
            except Exception as e:
                logger.warning(f"退出策略 {strategy.name} 计算失败: {e}")
                continue

        # 兜底：用固定百分比
        if take_profit is None:
            take_profit_pct = risk_cfg.get("take_profit_pct", 6.0) / 100
            if direction == "long":
                take_profit = price * (1 + take_profit_pct)
            else:
                take_profit = price * (1 - take_profit_pct)
            used_strategy = "fallback_pct"
            logger.warning("所有退出策略均未返回结果，使用固定百分比兜底")

        # 使用视频公式计算仓位大小
        quantity = self._calc_quantity_v2(price, stop_loss, direction)
        if quantity <= 0:
            result["reason"] = "计算仓位为 0（余额不足或低于最小交易额）"
            return result

        # 执行开仓
        try:
            order = self.account.open_position(
                symbol=signal.symbol,
                direction=direction,
                quantity=quantity,
                price=price,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                signal_rule=signal.rule_name,
                signal_message=signal.message,
            )
        except ValueError as e:
            result["reason"] = str(e)
            return result

        # 计算赔率
        risk = abs(price - stop_loss)
        reward = abs(take_profit - price)
        odds = reward / risk if risk > 0 else 0

        result["action"] = "add_position" if is_add else "open"
        result["quantity"] = quantity
        result["price"] = price
        result["stop_loss"] = stop_loss
        result["take_profit"] = take_profit
        result["cost"] = quantity * price
        result["balance_after"] = self.account.balance
        result["order_id"] = order.order_id
        result["exit_strategy"] = used_strategy
        result["odds_ratio"] = f"1:{odds:.1f}"

        logger.info(
            f"{'加仓' if is_add else '开仓'}信号处理：{direction.upper()} "
            f"{signal.symbol} × {quantity} @ {price:.2f} "
            f"[{signal.rule_name}] 止损={stop_loss:.2f} 止盈={take_profit:.2f} "
            f"赔率=1:{odds:.1f} 退出策略={used_strategy}"
        )
        return result

    def _calc_quantity_v2(
        self, price: float, stop_loss_price: float, direction: str
    ) -> float:
        """视频仓位计算公式。

        公式：仓位数量 = 最大亏损金额 / |开仓价 - 止损价|

        例如：最大亏 10 USDT，开仓价 60000，止损价 59700
        仓位 = 10 / |60000 - 59700| = 10 / 300 = 0.0333 BTC

        配置项：
        - position.max_loss_per_trade: 每笔最大亏损金额（USDT）
        - position.size_pct: 如果没设 max_loss_per_trade，回退到百分比
        - position.max_amount: 单笔上限
        - position.min_amount: 单笔下限
        """
        pos_cfg = self._config.get("position", {})
        risk_cfg = self._config.get("risk", {})
        max_loss = pos_cfg.get("max_loss_per_trade", 0)
        max_amount = pos_cfg.get("max_amount", 5000)
        min_amount = pos_cfg.get("min_amount", 5)

        if max_loss > 0:
            # 视频公式：仓位 = 最大亏损 / |开仓价 - 止损价|
            risk_per_unit = abs(price - stop_loss_price)
            if risk_per_unit <= 0:
                logger.warning("止损价等于开仓价，无法计算仓位")
                return 0.0
            quantity = max_loss / risk_per_unit
            cost = quantity * price

            # 检查余额是否够
            if cost > self.account.balance:
                # 缩减到余额能承受的范围
                quantity = self.account.balance / price
                cost = quantity * price
                logger.info(f"余额不足，缩减仓位到 {quantity}")

            # 检查上下限
            if cost > max_amount:
                quantity = max_amount / price
                cost = max_amount
            if cost < min_amount:
                return 0.0
        else:
            # 回退到百分比方式
            size_pct = pos_cfg.get("size_pct", 0.10)
            amount = self.account.balance * size_pct
            amount = min(amount, max_amount)
            if amount < min_amount:
                return 0.0
            quantity = amount / price

        # 保留合理精度
        if price > 1000:
            quantity = round(quantity, 6)  # BTC 精度
        elif price > 1:
            quantity = round(quantity, 4)  # ETH 精度
        else:
            quantity = round(quantity, 2)

        return quantity

    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        if not path.exists():
            logger.warning(f"交易配置不存在：{path}，使用默认值")
            return {"enabled": False}
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {"enabled": False}


__all__ = ["TradeExecutor"]
