"""临时脚本：对比不同参数下的双均线日线 1 年回测。

对比矩阵：
- 默认参数 vs 放宽 cluster_width_pct=1.5
- exit_horizon=10 vs 20

打印一张对比表。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment.indicators import compute_all  # noqa: E402
from investment.runner.backtest import backtest_with_returns  # noqa: E402
from investment.signals.examples.ma20_pullback import Ma20PullbackRule  # noqa: E402
from investment.signals.examples.ma_cluster_breakout import (  # noqa: E402
    MaClusterBreakoutRule,
)

END = pd.Timestamp("2026-05-26", tz="UTC")
START = END - pd.Timedelta(days=365)


def _run(symbol, df, cluster_w, exit_h, pullback_tol=0.3, pullback_spread=1.0):
    rules = [
        MaClusterBreakoutRule(params={"cluster_width_pct": cluster_w}),
        Ma20PullbackRule(params={
            "tolerance_pct": pullback_tol,
            "min_spread_pct": pullback_spread,
        }),
    ]
    result = backtest_with_returns(
        df, rules,
        symbol=symbol, timeframe="1D",
        horizons=(1, 5, exit_h),
        exit_horizon=exit_h,
    )
    trades = [
        o for o in result.outcomes
        if o.exit_return is not None and START <= o.signal.bar_ts <= END
    ]
    if not trades:
        return None
    by_rule = {}
    for o in trades:
        by_rule.setdefault(o.signal.rule_name, []).append(o)

    n = len(trades)
    wins = sum(1 for o in trades if o.is_win)
    total = sum(o.exit_return for o in trades)
    sorted_trades = sorted(trades, key=lambda o: o.signal.bar_ts)
    peak = 1.0
    nav = 1.0
    dd = 0.0
    for o in sorted_trades:
        nav += o.exit_return
        if nav > peak:
            peak = nav
        d = (nav - peak) / peak
        if d < dd:
            dd = d

    return {
        "n": n,
        "win_rate": wins / n,
        "total": total,
        "dd": dd,
        "by_rule": {k: (len(v), sum(o.exit_return for o in v)) for k, v in by_rule.items()},
    }


def main() -> int:
    scenarios = [
        ("默认 (cluster_w=0.6, exit=10)",  0.6, 10),
        ("放宽 cluster_w=1.5, exit=10",    1.5, 10),
        ("默认 exit=20",                   0.6, 20),
        ("放宽 cluster_w=1.5, exit=20",    1.5, 20),
        ("放宽 cluster_w=3.0, exit=20",    3.0, 20),
    ]

    for symbol in ["BTC-USDT", "ETH-USDT"]:
        path = Path(f"data/cache/{symbol}_1D.parquet")
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df = compute_all(df)

        print(f"\n{'='*100}")
        print(f"{symbol} · 日线 · 过去 1 年 ({START.date()} → {END.date()})")
        print(f"{'='*100}")
        print(f"{'场景':<38}{'笔数':>6}{'胜率':>8}{'累计':>10}{'回撤':>10}  规则分布")
        print("-" * 100)
        for name, cw, eh in scenarios:
            r = _run(symbol, df, cw, eh)
            if r is None:
                print(f"{name:<38}{'-':>6}{'-':>8}{'-':>10}{'-':>10}  -")
                continue
            rule_str = "  ".join(
                f"{k.split('_')[0]}:{n}" for k, (n, _) in r["by_rule"].items()
            )
            print(
                f"{name:<38}"
                f"{r['n']:>6d}"
                f"{r['win_rate']*100:>7.1f}%"
                f"{r['total']*100:>+9.2f}%"
                f"{r['dd']*100:>+9.2f}%"
                f"  {rule_str}"
            )

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
