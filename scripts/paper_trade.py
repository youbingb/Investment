"""命令行：模拟交易 — 跑 pipeline + 自动执行模拟交易。

用法：
    python scripts/paper_trade.py                            # 跑一轮 watchlist + 模拟交易
    python scripts/paper_trade.py --enable-all               # 启用所有规则
    python scripts/paper_trade.py --notify                   # 同时推送飞书通知
    python scripts/paper_trade.py --status                   # 查看账户状态
    python scripts/paper_trade.py --reset                    # 重置账户到初始状态
    python scripts/paper_trade.py --trades                   # 查看交易历史
    python scripts/paper_trade.py --run-forever              # 持续运行模式
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment.logger import logger, setup_logger  # noqa: E402
from investment.runner.pipeline import (  # noqa: E402
    execute_trades,
    get_account,
    get_executor,
    load_watchlist,
    notify_signals,
    run_pipeline,
)
from investment.signals.loader import REGISTRY  # noqa: E402


def show_status() -> int:
    """显示账户状态。"""
    account = get_account()
    snap = account.snapshot()

    print()
    print("=" * 64)
    print("  📊 模拟账户状态")
    print("=" * 64)
    print(f"  💰 余额:      {snap.balance:>12.2f} USDT")
    print(f"  📈 总盈亏:    {snap.total_pnl:>+12.2f} USDT")
    print(f"  📋 总交易:    {snap.total_trades:>12d} 笔")
    if snap.total_trades > 0:
        print(f"  ✅ 盈利:      {snap.win_count:>12d} 笔")
        print(f"  📊 胜率:      {snap.win_rate:>11.1%}")
    print(f"  🔓 持仓中:    {snap.open_positions_count:>12d} 个")

    if snap.positions:
        print()
        print("  当前持仓:")
        for pos in snap.positions:
            emoji = "🟢" if pos.direction == "long" else "🔴"
            print(
                f"    {emoji} {pos.direction.upper()} {pos.symbol} "
                f"× {pos.quantity} @ {pos.avg_entry_price:.2f}"
            )
            if pos.stop_loss_price:
                print(f"      止损: {pos.stop_loss_price:.2f}")
            if pos.take_profit_price:
                print(f"      止盈: {pos.take_profit_price:.2f}")

    print("=" * 64)
    return 0


def show_trades() -> int:
    """显示交易历史。"""
    account = get_account()
    trades = account.trades

    if not trades:
        print("\n暂无交易记录。\n")
        return 0

    print()
    print("=" * 80)
    print(f"  📜 交易历史（共 {len(trades)} 笔）")
    print("=" * 80)
    print(f"  {'#':>3} {'方向':>6} {'交易对':<12} {'入场价':>10} {'出场价':>10} {'盈亏':>10} {'盈亏%':>8} {'原因':<16}")
    print("-" * 80)

    total_pnl = 0.0
    for i, t in enumerate(trades, 1):
        emoji = "🟢" if t.is_win else "🔴"
        print(
            f"  {i:>3} {t.direction.upper():>6} {t.symbol:<12} "
            f"{t.entry_price:>10.2f} {t.exit_price:>10.2f} "
            f"{t.pnl:>+10.2f} {t.pnl_pct:>+7.2%} {emoji} {t.exit_reason:<16}"
        )
        total_pnl += t.pnl

    wins = sum(1 for t in trades if t.is_win)
    print("-" * 80)
    print(
        f"  总计: {len(trades)} 笔 | "
        f"胜: {wins} 负: {len(trades)-wins} | "
        f"胜率: {wins/len(trades):.1%} | "
        f"总盈亏: {total_pnl:+.2f} USDT"
    )
    print("=" * 80)
    return 0


def run_once(args: argparse.Namespace) -> int:
    """跑一轮 pipeline + 模拟交易。"""
    items = load_watchlist()
    if not items:
        logger.error("watchlist 为空，请检查 config/symbols.yaml")
        return 1

    logger.info(f"watchlist 共 {len(items)} 个组合")

    rules = None
    if args.enable_all:
        rules = [cls() for cls in REGISTRY.values()]
        logger.info(f"--enable-all 启用 {len(rules)} 条规则: {[r.name for r in rules]}")

    all_signals = []
    for item in items:
        result = run_pipeline(
            symbol=item.symbol,
            timeframe=item.timeframe,
            history_bars=item.history_bars,
            rules=rules,
        )
        all_signals.extend(result.signals)

    # 获取当前价格
    current_prices: dict[str, float] = {}
    for item in items:
        result = run_pipeline(
            symbol=item.symbol,
            timeframe=item.timeframe,
            history_bars=1,
            rules=[],  # 只拿数据不跑规则
        )
        if result.rows > 0:
            store = get_executor().account  # 复用 pipeline 的 store
            # 用 pipeline 重新拿一下最新价格
            pass

    print()
    print("=" * 64)
    if not all_signals:
        print(f"本轮无命中（{len(items)} 个组合扫描完毕）。")
    else:
        print(f"本轮 {len(all_signals)} 条信号：")
        for sig in all_signals:
            print(f"  • {sig.message}")

        # 执行模拟交易
        trade_results = execute_trades(all_signals, current_prices)
        if trade_results:
            print()
            print("交易执行结果:")
            for r in trade_results:
                if r["action"] == "skip":
                    print(f"  ⏭ {r['symbol']} {r['direction']} → 跳过: {r['reason']}")
                elif r["action"] in ("open", "add_position"):
                    label = "加仓" if r["action"] == "add_position" else "开仓"
                    print(
                        f"  🟢 {label}: {r['direction'].upper()} {r['symbol']} "
                        f"× {r['quantity']} @ {r['price']:.2f} "
                        f"(止损 {r['stop_loss']:.2f} / 止盈 {r['take_profit']:.2f})"
                    )
                elif r["action"] == "close":
                    emoji = "🟢" if r.get("pnl", 0) > 0 else "🔴"
                    print(
                        f"  {emoji} 平仓: {r['direction'].upper()} {r['symbol']} "
                        f"PnL={r.get('pnl', 0):+.2f} ({r.get('pnl_pct', 0):+.2%})"
                    )

    print("=" * 64)

    if args.notify and all_signals:
        sent = notify_signals(all_signals)
        logger.info(f"--notify：{len(all_signals)} 条信号，发出 {sent} 条")

    return 0


def run_forever_mode(args: argparse.Namespace) -> int:
    """持续运行模式 — 定时扫描 + 交易。"""
    interval = args.interval * 60  # 分钟转秒
    logger.info(f"模拟交易守护模式启动，每 {args.interval} 分钟扫描一次")

    items = load_watchlist()
    if not items:
        logger.error("watchlist 为空")
        return 1

    rules = None
    if args.enable_all:
        rules = [cls() for cls in REGISTRY.values()]

    print()
    print("🚀 模拟交易守护模式已启动")
    print(f"   扫描间隔: {args.interval} 分钟")
    print(f"   交易对: {', '.join(set(i.symbol for i in items))}")
    print(f"   规则: {len(rules) if rules else '配置文件'} 条")
    print("   按 Ctrl+C 停止")
    print()

    try:
        while True:
            try:
                all_signals = []
                for item in items:
                    result = run_pipeline(
                        symbol=item.symbol,
                        timeframe=item.timeframe,
                        history_bars=item.history_bars,
                        rules=rules,
                    )
                    all_signals.extend(result.signals)

                if all_signals:
                    trade_results = execute_trades(all_signals)
                    for r in trade_results:
                        if r["action"] in ("open", "add_position"):
                            logger.info(
                                f"{'加仓' if r['action'] == 'add_position' else '开仓'}: "
                                f"{r['direction'].upper()} {r['symbol']} "
                                f"× {r['quantity']} @ {r['price']:.2f}"
                            )
                        elif r["action"] == "close":
                            logger.info(
                                f"平仓: {r['direction'].upper()} {r['symbol']} "
                                f"PnL={r.get('pnl', 0):+.2f}"
                            )

                    if args.notify:
                        notify_signals(all_signals)
                else:
                    logger.debug("本轮无信号")

                # 显示账户状态
                snap = get_account().snapshot()
                logger.info(
                    f"账户: 余额={snap.balance:.2f} "
                    f"持仓={snap.open_positions_count} "
                    f"总交易={snap.total_trades} "
                    f"胜率={snap.win_rate:.1%}"
                )

            except Exception as e:
                logger.error(f"本轮扫描异常: {e}")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n守护模式已停止。")
        show_status()
        return 0


def main() -> int:
    setup_logger()

    parser = argparse.ArgumentParser(
        description="模拟交易 — 自动捕捉信号并执行纸上交易"
    )
    parser.add_argument(
        "--enable-all", action="store_true",
        help="临时启用所有内置规则",
    )
    parser.add_argument(
        "--notify", action="store_true",
        help="同时推送飞书通知",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="查看账户状态",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="重置账户到初始状态",
    )
    parser.add_argument(
        "--trades", action="store_true",
        help="查看交易历史",
    )
    parser.add_argument(
        "--run-forever", action="store_true",
        help="持续运行模式",
    )
    parser.add_argument(
        "--interval", type=int, default=5,
        help="持续运行模式的扫描间隔（分钟，默认 5）",
    )
    args = parser.parse_args()

    if args.status:
        return show_status()
    if args.reset:
        get_account().reset()
        print("账户已重置。")
        return 0
    if args.trades:
        return show_trades()
    if args.run_forever:
        return run_forever_mode(args)

    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
