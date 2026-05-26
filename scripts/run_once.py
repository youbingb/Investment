"""命令行：跑一次 watchlist 中所有 (symbol, timeframe) 的 pipeline。

用法：
    python scripts/run_once.py                          # 用 config/signals.yaml enabled 的规则
    python scripts/run_once.py --enable-all             # 临时启用所有内置规则（不改 yaml）
    python scripts/run_once.py --notify                 # 命中时把信号推送到飞书（去重防重发）
    python scripts/run_once.py --enable-all --notify    # 二者叠加

打印每个组合的命中情况；--notify 会附加把信号送进飞书。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment.logger import logger, setup_logger  # noqa: E402
from investment.runner.pipeline import (  # noqa: E402
    load_watchlist,
    notify_signals,
    run_pipeline,
)
from investment.signals.loader import REGISTRY  # noqa: E402


def main() -> int:
    setup_logger()

    parser = argparse.ArgumentParser(description="跑一次 watchlist pipeline，打印命中信号")
    parser.add_argument(
        "--enable-all", action="store_true",
        help="临时启用所有内置规则（忽略 signals.yaml 中 enabled 字段）",
    )
    parser.add_argument(
        "--notify", action="store_true",
        help="把命中的信号推送到飞书（去重防同 bar 重发，DRY_RUN 时只打印）",
    )
    args = parser.parse_args()

    items = load_watchlist()
    if not items:
        logger.error("watchlist 为空，请检查 config/symbols.yaml")
        return 1
    logger.info(f"watchlist 共 {len(items)} 个组合")

    rules = None
    if args.enable_all:
        rules = [cls() for cls in REGISTRY.values()]
        logger.info(f"--enable-all 启用 {len(rules)} 条内置规则: {[r.name for r in rules]}")

    all_signals = []
    for item in items:
        result = run_pipeline(
            symbol=item.symbol,
            timeframe=item.timeframe,
            history_bars=item.history_bars,
            rules=rules,
        )
        all_signals.extend(result.signals)

    print()
    print("=" * 64)
    if not all_signals:
        print(f"本轮无命中（{len(items)} 个组合扫描完毕）。")
    else:
        print(f"本轮 {len(all_signals)} 条信号：")
        for sig in all_signals:
            print(f"  • {sig.message}")
    print("=" * 64)

    if args.notify and all_signals:
        sent = notify_signals(all_signals)
        logger.info(f"--notify：{len(all_signals)} 条信号，实际发出 {sent} 条（其余被去重抑制）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
