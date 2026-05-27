"""每日模拟交易盈亏汇报脚本。

输出格式化的盈亏报告到 stdout，供 cron job 或手动调用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from datetime import datetime, timezone

from investment.runner.pipeline import get_account  # noqa: E402


def main() -> str:
    account = get_account()
    snap = account.snapshot()
    trades = account.trades
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"📊 每日模拟交易报告",
        f"📅 {now}",
        "",
        f"💰 账户余额: {snap.balance:.2f} USDT (初始 100.00)",
        f"📈 总盈亏: {snap.total_pnl:+.2f} USDT ({snap.total_pnl/100:+.1%})",
        f"📋 总交易: {snap.total_trades} 笔",
    ]

    if snap.total_trades > 0:
        lines.append(f"✅ 胜率: {snap.win_rate:.1%} ({snap.win_count}胜/{snap.total_trades - snap.win_count}负)")

    lines.append(f"🔓 当前持仓: {snap.open_positions_count} 个")

    if snap.positions:
        lines.append("")
        lines.append("当前持仓详情:")
        for pos in snap.positions:
            emoji = "🟢" if pos.direction == "long" else "🔴"
            lines.append(f"  {emoji} {pos.direction.upper()} {pos.symbol}")
            lines.append(f"    数量: {pos.quantity} | 入场: {pos.avg_entry_price:.2f}")
            if pos.stop_loss_price:
                lines.append(f"    止损: {pos.stop_loss_price:.2f}")
            if pos.take_profit_price:
                lines.append(f"    止盈: {pos.take_profit_price:.2f}")

    # 最近 5 笔交易
    recent = trades[-5:] if trades else []
    if recent:
        lines.append("")
        lines.append("最近交易:")
        for t in reversed(recent):
            emoji = "🟢" if t.is_win else "🔴"
            lines.append(
                f"  {emoji} {t.direction.upper()} {t.symbol} "
                f"入场{t.entry_price:.2f} → 出场{t.exit_price:.2f} "
                f"PnL={t.pnl:+.2f} ({t.pnl_pct:+.1%}) [{t.exit_reason}]"
            )

    report = "\n".join(lines)
    print(report)
    return report


if __name__ == "__main__":
    main()
