"""命令行：在历史 K 线上回放信号规则，统计命中。

用法：
    # BTC-USDT 1H 用 enabled 规则跑全量缓存
    python scripts/backtest.py BTC-USDT 1H

    # 临时启用所有内置规则
    python scripts/backtest.py BTC-USDT 1H --enable-all

    # 限定时间窗口（含两端，UTC）
    python scripts/backtest.py BTC-USDT 1H --start 2024-01-01 --end 2024-06-30

    # 数据不够时先 fetch_history.py 拉到本地，再回测
    python scripts/fetch_history.py BTC-USDT 1H 1000
    python scripts/backtest.py BTC-USDT 1H --enable-all

输出：每条规则的命中数、方向分布、最近 N 条信号明细。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment.data.kline_store import KlineStore  # noqa: E402
from investment.indicators import compute_all  # noqa: E402
from investment.logger import logger, setup_logger  # noqa: E402
from investment.runner.backtest import backtest_rules  # noqa: E402
from investment.signals.loader import REGISTRY, load_rules  # noqa: E402


def _parse_ts(s: str | None) -> pd.Timestamp | None:
    if s is None:
        return None
    return pd.Timestamp(s, tz="UTC")


def main() -> int:
    setup_logger()

    parser = argparse.ArgumentParser(description="在历史 K 线缓存上回放信号规则")
    parser.add_argument("symbol", help="例如 BTC-USDT")
    parser.add_argument("timeframe", help="例如 1H / 4H / 1D")
    parser.add_argument(
        "--start", default=None,
        help='起始时间（UTC，含），格式 "2024-01-01" 或 "2024-01-01T08:00"',
    )
    parser.add_argument(
        "--end", default=None,
        help='结束时间（UTC，含）',
    )
    parser.add_argument(
        "--enable-all", action="store_true",
        help="启用所有内置规则；不传时读 config/signals.yaml enabled 字段",
    )
    parser.add_argument(
        "--limit-show", type=int, default=20,
        help="明细打印最多 N 条命中（按时间倒序），默认 20",
    )
    args = parser.parse_args()

    store = KlineStore()
    df = store.load(args.symbol, args.timeframe)
    if df.empty:
        logger.error(
            f"本地缓存为空：{store.path(args.symbol, args.timeframe)}\n"
            f"先跑：python scripts/fetch_history.py {args.symbol} {args.timeframe} 1000"
        )
        return 1

    # 时间窗筛
    start = _parse_ts(args.start)
    end = _parse_ts(args.end)
    if start is not None:
        df = df[df["ts"] >= start]
    if end is not None:
        df = df[df["ts"] <= end]
    df = df.reset_index(drop=True)
    if df.empty:
        logger.error("时间窗内没数据")
        return 1

    df = compute_all(df)

    if args.enable_all:
        rules = [cls() for cls in REGISTRY.values()]
        logger.info(f"--enable-all 启用 {len(rules)} 条规则：{[r.name for r in rules]}")
    else:
        rules = load_rules()
        if not rules:
            logger.error("signals.yaml 中没有 enabled 规则；可加 --enable-all")
            return 1

    result = backtest_rules(
        df, rules,
        symbol=args.symbol, timeframe=args.timeframe,
    )

    print()
    print("=" * 64)
    print(f"回测 {args.symbol} {args.timeframe}")
    print(f"  时间窗：{df['ts'].iloc[0]} → {df['ts'].iloc[-1]}")
    print(f"  K 线：{result.bars_total} 根 / 评估 {result.bars_evaluated} 根")
    print(f"  总命中：{len(result.signals)}")
    print()
    print("按规则汇总：")
    for name, cnt in sorted(result.hits_by_rule.items(), key=lambda x: -x[1]):
        print(f"  • {name}: {cnt}")
    print()
    print("按方向汇总：")
    for d, cnt in sorted(result.hits_by_direction.items(), key=lambda x: -x[1]):
        print(f"  • {d}: {cnt}")
    print()
    if result.signals:
        recent = sorted(result.signals, key=lambda s: s.bar_ts, reverse=True)[: args.limit_show]
        print(f"最近 {len(recent)} 条命中（倒序）：")
        for s in recent:
            print(f"  [{s.bar_ts}] {s.message}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
