"""临时脚本：只启用 ma_cluster_breakout + ma20_pullback 两条规则，
在日线级别上回测过去 1 年，计算累计收益、胜率、最大回撤、年化。

用法：
    python scripts/backtest_dual_ma_1y.py

假设：
- 每笔交易等权（NAV 起 1.0，每笔 +/- exit_return）
- 出场：信号后第 10 根 K（约 10 天）
- 不计手续费 / 滑点
- 信号有重叠 / 同一根多规则命中也都各算一笔
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

# -- 配置 --
END = pd.Timestamp("2026-05-26", tz="UTC")
START = END - pd.Timedelta(days=365)
EXIT_HORIZON = 10  # 持仓 10 个交易日（约 2 周）
SYMBOLS = ["BTC-USDT", "ETH-USDT"]


def _aggregate_window(outcomes, start, end):
    """筛选 bar_ts 落在 [start, end] 的、且有完整 exit_return 的 outcome。"""
    return [
        o for o in outcomes
        if o.exit_return is not None and start <= o.signal.bar_ts <= end
    ]


def _equity_curve(trades):
    """每笔权重 1，累加。"""
    trades_sorted = sorted(trades, key=lambda o: o.signal.bar_ts)
    nav = 1.0
    peak = 1.0
    worst_dd = 0.0
    curve = []
    for o in trades_sorted:
        nav += o.exit_return
        if nav > peak:
            peak = nav
        dd = (nav - peak) / peak
        if dd < worst_dd:
            worst_dd = dd
        curve.append((o.signal.bar_ts, nav, o.exit_return))
    return curve, worst_dd


def main() -> int:
    print(f"\n{'='*88}")
    print(f"双均线交易系统 · 日线 · 过去 1 年回测")
    print(f"时间窗：{START.date()} → {END.date()}  ({365} 天)")
    print(f"规则：ma_cluster_breakout + ma20_pullback")
    print(f"出场：信号后第 {EXIT_HORIZON} 根日线 (约 {EXIT_HORIZON} 天)")
    print(f"假设：每笔等权 / 不计手续费滑点 / 信号重叠各算一笔")
    print(f"{'='*88}\n")

    for symbol in SYMBOLS:
        path = Path(f"data/cache/{symbol}_1D.parquet")
        if not path.exists():
            print(f"[skip] {symbol}: 缓存不存在 ({path})")
            continue
        df = pd.read_parquet(path)
        df = compute_all(df)

        rules = [MaClusterBreakoutRule(), Ma20PullbackRule()]
        result = backtest_with_returns(
            df, rules,
            symbol=symbol, timeframe="1D",
            horizons=(1, 3, 5, EXIT_HORIZON),
            exit_horizon=EXIT_HORIZON,
        )

        trades = _aggregate_window(result.outcomes, START, END)
        if not trades:
            print(f"\n--- {symbol} ---  过去 1 年无完整交易 ---")
            continue

        n = len(trades)
        wins = sum(1 for o in trades if o.is_win)
        win_rate = wins / n
        total_ret = sum(o.exit_return for o in trades)
        avg_ret = total_ret / n
        win_rets = [o.exit_return for o in trades if o.exit_return > 0]
        loss_rets = [o.exit_return for o in trades if o.exit_return <= 0]
        avg_win = (sum(win_rets) / len(win_rets)) if win_rets else float("nan")
        avg_loss = (sum(loss_rets) / len(loss_rets)) if loss_rets else float("nan")
        payoff = (avg_win / abs(avg_loss)) if (avg_loss and avg_loss < 0) else float("nan")

        curve, max_dd = _equity_curve(trades)
        first_ts = curve[0][0]
        last_ts = curve[-1][0]
        elapsed = (last_ts - first_ts).days or 1

        # 年化口径：用过去 1 年的"日历跨度"作分母，更直观
        calendar_days = (END - START).days  # 365
        simple_ann = total_ret * (365 / calendar_days)        # 与 total_ret 等价（窗口就是 1 年）
        compound_ann = (1 + total_ret) ** (365 / calendar_days) - 1

        # 按方向分
        n_long = sum(1 for o in trades if o.signal.direction == "long")
        n_short = sum(1 for o in trades if o.signal.direction == "short")

        # 按规则分
        per_rule: dict[str, list] = {}
        for o in trades:
            per_rule.setdefault(o.signal.rule_name, []).append(o)

        print(f"\n--- {symbol} ---")
        print(f"  交易笔数        : {n}  (long {n_long} / short {n_short})")
        print(f"  胜率            : {win_rate*100:.1f}%  ({wins}/{n})")
        print(f"  平均收益/笔     : {avg_ret*100:+.2f}%")
        print(f"  平均盈 / 平均亏 : {avg_win*100:+.2f}% / {avg_loss*100:+.2f}%")
        print(f"  赔率（avg_win/|avg_loss|）: {payoff:.2f}")
        print(f"  累计简单收益    : {total_ret*100:+.2f}%")
        print(f"  最大回撤        : {max_dd*100:+.2f}%")
        print(f"  实际首末跨度    : {elapsed} 天  ({first_ts.date()} → {last_ts.date()})")
        print(f"  ★ 年化（简单口径，1 年窗口）  : {simple_ann*100:+.2f}%")
        print(f"  ★ 年化（复利近似）             : {compound_ann*100:+.2f}%")
        print(f"  按规则：")
        for rule_name, outs in per_rule.items():
            w = sum(1 for o in outs if o.is_win)
            tret = sum(o.exit_return for o in outs)
            print(f"    {rule_name:25s} {len(outs):3d} 笔  胜率 {w/len(outs)*100:5.1f}%  累计 {tret*100:+.2f}%")

    print(f"\n{'='*88}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
