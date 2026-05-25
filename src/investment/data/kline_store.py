"""K 线本地 parquet 缓存。

文件路径：``data/cache/{inst_id}_{bar}.parquet``

设计原则：
- 一次 fetch 拿到的数据合并到既有缓存，按 ts 去重、升序
- 进程外可以共享同一份文件（pyarrow 读写并不会破坏现有数据）
- 不做"按时间区间查询"的查询能力，调用方拿到 DataFrame 自己切片
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from investment.data.okx_client import CANDLES_COLS, OKXClient
from investment.logger import logger

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"


class KlineStore:
    """parquet 缓存 + 自动补齐到指定行数。"""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- 基础 IO ----

    def path(self, inst_id: str, bar: str) -> Path:
        return self.cache_dir / f"{inst_id}_{bar}.parquet"

    def load(self, inst_id: str, bar: str) -> pd.DataFrame:
        """读本地缓存；不存在返回空 DataFrame。"""
        p = self.path(inst_id, bar)
        if not p.exists():
            return pd.DataFrame(columns=CANDLES_COLS)
        df = pd.read_parquet(p)
        # 防御：保证 ts 是 datetime 且升序
        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df.sort_values("ts").reset_index(drop=True)

    def save(self, inst_id: str, bar: str, df: pd.DataFrame) -> None:
        p = self.path(inst_id, bar)
        df.to_parquet(p, engine="pyarrow", index=False)
        logger.debug(f"KlineStore 保存 {p.name} ({len(df)} 行)")

    # ---- 主入口 ----

    def get_or_fetch(
        self,
        client: OKXClient,
        inst_id: str,
        bar: str,
        n: int,
    ) -> pd.DataFrame:
        """保证拿到至少 n 根最近的 K 线，必要时调用 client 补齐。

        逻辑：
        1. 先用 fetch_candles 拿最近 min(n, 300) 根（这是热数据，每次都刷一遍保证新鲜）
        2. 与本地 cache merge、去重、排序
        3. 如果合并后还不足 n 根，调 fetch_history_candles 往老翻页
        4. 写回 cache
        5. 返回最近 n 行
        """
        df_cached = self.load(inst_id, bar)

        # 第 1 步：刷最近一批
        fresh = client.fetch_candles(inst_id, bar, limit=min(n, 300))
        merged = self._merge(df_cached, fresh)

        # 第 2 步：缺多少老数据就翻页补
        while len(merged) < n:
            oldest_ts = int(merged["ts"].min().timestamp() * 1000)
            more = client.fetch_history_candles(
                inst_id, bar, limit=100, after=oldest_ts,
            )
            if more.empty:
                logger.warning(
                    f"{inst_id} {bar} 已经拉到最早历史，"
                    f"只有 {len(merged)} 根，达不到 {n} 根"
                )
                break
            merged = self._merge(merged, more)

        self.save(inst_id, bar, merged)
        return merged.tail(n).reset_index(drop=True)

    @staticmethod
    def _merge(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
        if a.empty:
            return b.copy()
        if b.empty:
            return a.copy()
        out = (
            pd.concat([a, b], ignore_index=True)
            .drop_duplicates(subset=["ts"], keep="last")
            .sort_values("ts")
            .reset_index(drop=True)
        )
        return out


__all__ = ["KlineStore", "DEFAULT_CACHE_DIR"]
