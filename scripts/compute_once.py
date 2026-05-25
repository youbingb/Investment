"""命令行：拉 N 根 K 线、算指标、打印最近 5 行带所有指标列。

用法：
    python scripts/compute_once.py BTC-USDT 1H
    python scripts/compute_once.py ETH-USDT 4H --n 500
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd  # noqa: E402

from investment.data.kline_store import KlineStore  # noqa: E402
from investment.data.okx_client import OKXClient  # noqa: E402
from investment.indicators import MA_PERIODS, compute_all  # noqa: E402
from investment.logger import logger, setup_logger  # noqa: E402


def main() -> int:
    setup_logger()

    parser = argparse.ArgumentParser(
        description="拉 K 线 → 算指标 → 打印最近 5 行带所有指标列",
    )
    parser.add_argument("inst_id", help="OKX 交易对，如 BTC-USDT")
    parser.add_argument("bar", help="周期，如 1H / 4H / 1D")
    parser.add_argument(
        "--n", type=int, default=300,
        help="拉取的 K 线根数（默认 300，要保证 > max MA 周期 = 120）",
    )
    args = parser.parse_args()

    if args.n <= max(MA_PERIODS):
        logger.warning(
            f"n={args.n} <= max MA 周期 {max(MA_PERIODS)}，"
            f"sma{max(MA_PERIODS)}/ema{max(MA_PERIODS)} 会有较多 NaN 行"
        )

    client = OKXClient()
    store = KlineStore()

    logger.info(f"拉取 {args.inst_id} {args.bar} × {args.n} 根...")
    df = store.get_or_fetch(client, args.inst_id, args.bar, args.n)
    if df.empty:
        logger.error("没拿到数据")
        return 1

    df = compute_all(df)
    logger.info(f"算指标完成；共 {len(df)} 行，最新 ts={df['ts'].iloc[-1]}")

    cols = (
        ["ts", "close"]
        + [f"sma{p}" for p in MA_PERIODS]
        + [f"ema{p}" for p in MA_PERIODS]
        + [f"dot{p}" for p in MA_PERIODS]
    )
    print()
    print("最近 5 行（已截取小数）：")
    pd.set_option("display.float_format", "{:.2f}".format)
    print(df[cols].tail(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
