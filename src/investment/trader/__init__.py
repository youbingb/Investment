"""模拟交易模块。

PaperAccount → 虚拟账户（余额、持仓、交易记录）
TradeExecutor → 信号驱动的交易执行 + 风控
"""
from investment.trader.executor import TradeExecutor
from investment.trader.paper_account import PaperAccount

__all__ = ["PaperAccount", "TradeExecutor"]
