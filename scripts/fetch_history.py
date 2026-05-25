"""命令行：拉取指定 inst_id + bar 的最近 N 根 K 线到本地 parquet。

用法：
    python scripts/fetch_history.py BTC-USDT 1H 500
    python scripts/fetch_history.py ETH-USDT 4H 1000

数据会写入 ``data/cache/{inst_id}_{bar}.parquet``。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让 `python scripts/xxx.py` 也能 import investment 包（无需 pip install -e）
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment.data.kline_store import KlineStore  # noqa: E402
from investment.data.okx_client import OKXClient  # noqa: E402
from investment.logger import logger, setup_logger  # noqa: E402


def main() -> int:
    setup_logger()

    parser = argparse.ArgumentParser(
        description="拉取 OKX K 线到 data/cache/{inst}_{bar}.parquet",
    )
    parser.add_argument("inst_id", help="OKX 交易对，例如 BTC-USDT（破折号）")
    parser.add_argument("bar", help="周期，例如 1H / 4H / 1D（H/D 大写）")
    parser.add_argument("n", type=int, help="目标行数（最少 1）")
    args = parser.parse_args()

    if args.n < 1:
        parser.error("n 至少为 1")

    client = OKXClient()
    store = KlineStore()

    logger.info(f"开始拉取 {args.inst_id} {args.bar}，目标 {args.n} 根")
    df = store.get_or_fetch(client, args.inst_id, args.bar, args.n)

    if df.empty:
        logger.error("没拿到任何数据，请检查 inst_id 是否正确（OKX 用破折号格式）")
        return 1

    logger.info(
        f"完成：拿到 {len(df)} 根，"
        f"最早 {df['ts'].iloc[0]}，最新 {df['ts'].iloc[-1]}"
    )
    print()
    print("最近 5 根：")
    cols = ["ts", "open", "high", "low", "close", "vol", "confirm"]
    print(df[cols].tail(5).to_string(index=False))
    print()
    print(f"已缓存到：{store.path(args.inst_id, args.bar)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
