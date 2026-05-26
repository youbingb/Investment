"""命令行：在历史 K 线上回放信号规则 + 收益统计 + 资金曲线 + CSV 导出。

用法：
    # BTC-USDT 1H 用 enabled 规则跑全量缓存（默认 horizons=1,5,10,20，exit=10）
    python scripts/backtest.py BTC-USDT 1H

    # 临时启用所有内置规则
    python scripts/backtest.py BTC-USDT 1H --enable-all

    # 限定时间窗口（含两端，UTC）
    python scripts/backtest.py BTC-USDT 1H --start 2024-01-01 --end 2024-06-30

    # 自定义 horizons + exit
    python scripts/backtest.py BTC-USDT 1H --enable-all --horizons 1,3,5,10 --exit-after 5

    # 导出明细到 CSV
    python scripts/backtest.py BTC-USDT 1H --enable-all --csv data/reports/btc_1h.csv

输出 4 段：
1. 头部 — 时间窗 / 总根数 / 命中数
2. 按规则汇总 — 命中 / 完整窗口 / 胜率 / 平均收益 / MFE / MAE
3. 按方向汇总 — long / short / neutral 命中数
4. 资金曲线 — NAV 起止 / 最高 / 最低 / 累计收益 / 最大回撤
5. 最近 N 条命中明细（带 exit_return 标签）

CSV 字段：ts, symbol, tf, rule, direction, entry, ret_<h>, ..., mfe, mae, is_win
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import pandas as pd

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment.data.kline_store import KlineStore  # noqa: E402
from investment.indicators import compute_all  # noqa: E402
from investment.logger import logger, setup_logger  # noqa: E402
from investment.runner.backtest import (  # noqa: E402
    DEFAULT_EXIT_HORIZON,
    DEFAULT_HORIZONS,
    BacktestResult,
    backtest_with_returns,
)
from investment.signals.loader import REGISTRY, load_rules  # noqa: E402


def _parse_ts(s: str | None) -> pd.Timestamp | None:
    if s is None:
        return None
    return pd.Timestamp(s, tz="UTC")


def _parse_horizons(s: str) -> tuple[int, ...]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out = tuple(int(p) for p in parts)
    if not out:
        raise argparse.ArgumentTypeError("--horizons 至少要一个值")
    if any(h <= 0 for h in out):
        raise argparse.ArgumentTypeError("horizon 必须 > 0")
    return out


def _fmt_pct(x: float) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "  -  "
    return f"{x*100:+6.2f}%"


def _fmt_ratio(x: float) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "  -  "
    if math.isinf(x):
        return "  inf"
    return f"{x:6.2f}"


def _print_per_rule_stats(result: BacktestResult) -> None:
    stats = result.stats_by_rule()
    if not stats:
        print("（无规则统计）")
        return
    headers = ["规则", "命中", "完整窗口", "胜率", "平均收益",
               "平均盈", "平均亏", "赔率", "盈亏比", "平均 MFE", "平均 MAE"]
    print(f"{headers[0]:<14} {headers[1]:>6} {headers[2]:>8} "
          f"{headers[3]:>7} {headers[4]:>9} {headers[5]:>9} {headers[6]:>9} "
          f"{headers[7]:>7} {headers[8]:>7} {headers[9]:>9} {headers[10]:>9}")
    print("-" * 114)
    for name, st in sorted(stats.items(), key=lambda x: -x[1]["count"]):
        wr = st["win_rate"]
        wr_s = f"{wr*100:6.1f}%" if not math.isnan(wr) else "   -  "
        print(
            f"{name:<14} "
            f"{int(st['count']):>6d} "
            f"{int(st['trades']):>8d} "
            f"{wr_s:>7} "
            f"{_fmt_pct(st['avg_return']):>9} "
            f"{_fmt_pct(st['avg_win']):>9} "
            f"{_fmt_pct(st['avg_loss']):>9} "
            f"{_fmt_ratio(st['payoff_ratio']):>7} "
            f"{_fmt_ratio(st['profit_factor']):>7} "
            f"{_fmt_pct(st['avg_mfe']):>9} "
            f"{_fmt_pct(st['avg_mae']):>9}"
        )


def _print_equity_summary(result: BacktestResult) -> None:
    curve = result.equity_curve()
    if not curve:
        print("（无完整窗口的信号，资金曲线为空）")
        return
    navs = [nav for _, nav in curve]
    print(f"  起始 NAV  : 1.0000")
    print(f"  最末 NAV  : {curve[-1][1]:.4f}")
    print(f"  最高 NAV  : {max(navs):.4f}  @ {curve[navs.index(max(navs))][0]}")
    print(f"  最低 NAV  : {min(navs):.4f}  @ {curve[navs.index(min(navs))][0]}")
    print(f"  累计收益  : {result.total_return*100:+.2f}%")
    print(f"  最大回撤  : {result.max_drawdown*100:+.2f}%")
    print(f"  交易笔数  : {len(curve)}")


def _print_recent(result: BacktestResult, limit: int) -> None:
    if not result.outcomes:
        return
    recent = sorted(result.outcomes, key=lambda o: o.signal.bar_ts, reverse=True)[:limit]
    print(f"最近 {len(recent)} 条命中（倒序）：")
    for o in recent:
        ret = o.exit_return
        tag = "WIN " if o.is_win is True else ("LOSE" if o.is_win is False else "?   ")
        ret_s = _fmt_pct(ret) if ret is not None else "  无完整窗口"
        print(f"  [{o.signal.bar_ts}] {tag} ret={ret_s}  {o.signal.message}")


def _export_csv(result: BacktestResult, path: Path, horizons: tuple[int, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ts", "symbol", "timeframe", "rule", "direction", "entry_price"]
    fields += [f"ret_{h}" for h in horizons]
    fields += ["mfe_pct", "mae_pct", "exit_horizon", "exit_return", "is_win", "message"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for o in sorted(result.outcomes, key=lambda x: x.signal.bar_ts):
            s = o.signal
            row = [
                s.bar_ts.isoformat(), s.symbol, s.timeframe,
                s.rule_name, s.direction, f"{o.entry_price:.6f}",
            ]
            for h in horizons:
                r = o.horizon_returns.get(h, float("nan"))
                row.append("" if (isinstance(r, float) and math.isnan(r)) else f"{r:.6f}")
            row.append("" if math.isnan(o.mfe_pct) else f"{o.mfe_pct:.6f}")
            row.append("" if math.isnan(o.mae_pct) else f"{o.mae_pct:.6f}")
            row.append(str(o.exit_horizon))
            row.append("" if o.exit_return is None else f"{o.exit_return:.6f}")
            row.append("" if o.is_win is None else ("1" if o.is_win else "0"))
            row.append(s.message)
            w.writerow(row)
    logger.info(f"CSV 已导出：{path}（{len(result.outcomes)} 行）")


def main() -> int:
    setup_logger()

    parser = argparse.ArgumentParser(description="历史回测：信号 + 收益 + 资金曲线")
    parser.add_argument("symbol", help="例如 BTC-USDT")
    parser.add_argument("timeframe", help="例如 1H / 4H / 1D")
    parser.add_argument("--start", default=None, help="起始时间（UTC，含）")
    parser.add_argument("--end", default=None, help="结束时间（UTC，含）")
    parser.add_argument(
        "--enable-all", action="store_true",
        help="启用所有内置规则；不传时读 signals.yaml enabled 字段",
    )
    parser.add_argument(
        "--horizons", type=_parse_horizons,
        default=DEFAULT_HORIZONS,
        help='收益跟踪窗口（根数），逗号分隔。默认 "1,5,10,20"',
    )
    parser.add_argument(
        "--exit-after", type=int, default=DEFAULT_EXIT_HORIZON,
        help="模拟交易持仓 N 根 K 后平仓，默认 10。MFE/MAE 也在这个窗口内算",
    )
    parser.add_argument(
        "--csv", default=None,
        help="把信号 + 收益明细导出到 CSV（如 data/reports/btc_1h.csv）",
    )
    parser.add_argument(
        "--limit-show", type=int, default=20,
        help="终端最近命中明细打印行数，默认 20",
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

    horizons = tuple(sorted(set(args.horizons) | {args.exit_after}))
    result = backtest_with_returns(
        df, rules,
        symbol=args.symbol, timeframe=args.timeframe,
        horizons=horizons, exit_horizon=args.exit_after,
    )

    print()
    print("=" * 96)
    print(f"回测 {args.symbol} {args.timeframe}")
    print(f"  时间窗：{df['ts'].iloc[0]} → {df['ts'].iloc[-1]}")
    print(f"  K 线  ：{result.bars_total} 根 / 评估 {result.bars_evaluated} 根")
    print(f"  命中  ：{len(result.signals)}  (其中 {len(result.outcomes)} 个 long/short 进入收益跟踪)")
    print(f"  horizons={horizons}  exit_after={args.exit_after}")
    print()
    print("按规则统计：")
    _print_per_rule_stats(result)
    print()
    print("按方向汇总：")
    for d, cnt in sorted(result.hits_by_direction.items(), key=lambda x: -x[1]):
        print(f"  • {d}: {cnt}")
    print()
    print("资金曲线（每笔权重 1，无手续费）：")
    _print_equity_summary(result)
    print()
    _print_recent(result, args.limit_show)
    print("=" * 96)

    if args.csv:
        _export_csv(result, Path(args.csv), horizons)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
