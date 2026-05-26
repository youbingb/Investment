# 调度层：APScheduler 定时拉数据 → 算指标 → 跑信号 + 飞书通知（阶段 4-5）
# 回测层：滚动历史数据跑信号规则 + 收益/胜率/equity 跟踪（阶段 6）
from investment.runner.backtest import (
    BacktestResult,
    SignalOutcome,
    backtest_rules,
    backtest_with_returns,
    evaluate_outcomes,
)

__all__ = [
    "BacktestResult",
    "SignalOutcome",
    "backtest_rules",
    "backtest_with_returns",
    "evaluate_outcomes",
]
