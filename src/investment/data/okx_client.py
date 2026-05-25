"""OKX V5 现货公开行情 REST 客户端。

只封装公开 K 线接口（不需要 API key）；不涉及下单、账户。

文档：docs/EXTERNAL_APIS.md "OKX V5 现货公开行情" 一节。
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd
import requests

from investment.config import get_settings
from investment.logger import logger

#: DataFrame 列顺序（与 OKX 返回顺序一致），落 parquet 时也按这个顺序。
CANDLES_COLS: list[str] = [
    "ts", "open", "high", "low", "close",
    "vol", "vol_ccy", "vol_ccy_quote", "confirm",
]

#: OKX bar 取值合法集合（H/D/W/M 必须大写）。
VALID_BARS = {
    "1s", "1m", "3m", "5m", "15m", "30m",
    "1H", "2H", "4H", "6H", "12H",
    "1D", "1W", "1M",
}


class OKXClient:
    """OKX REST 客户端，session 复用、自动重试。

    用法：
        client = OKXClient()
        df = client.fetch_candles("BTC-USDT", "1H", limit=300)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.okx_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else s.okx_request_timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "investment/0.1.0")

    def fetch_candles(
        self,
        inst_id: str,
        bar: str = "1H",
        limit: int = 100,
        before: Optional[int] = None,
        after: Optional[int] = None,
    ) -> pd.DataFrame:
        """最近 K 线（1440 根历史上限）。

        Args:
            inst_id: 形如 "BTC-USDT"（破折号；不是 "BTC/USDT" 或 "BTCUSDT"）。
            bar: 见 ``VALID_BARS``，H/D 大写。
            limit: 默认 100，最大 300。
            before: 仅返回 ts < before（毫秒）。
            after: 仅返回 ts > after（毫秒）。
        """
        self._validate_bar(bar)
        if not 1 <= limit <= 300:
            raise ValueError(f"limit 必须在 1..300 之间，实际 {limit}")

        params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if before is not None:
            params["before"] = str(before)
        if after is not None:
            params["after"] = str(after)

        data = self._request_with_retry("/api/v5/market/candles", params)
        return self._parse_candles(data)

    def fetch_history_candles(
        self,
        inst_id: str,
        bar: str = "1H",
        limit: int = 100,
        after: Optional[int] = None,
    ) -> pd.DataFrame:
        """更早的历史 K 线（用于翻页拉过 1440 根的数据）。"""
        self._validate_bar(bar)
        if not 1 <= limit <= 100:
            raise ValueError(f"history-candles limit 必须在 1..100，实际 {limit}")

        params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if after is not None:
            params["after"] = str(after)

        data = self._request_with_retry("/api/v5/market/history-candles", params)
        return self._parse_candles(data)

    def _request_with_retry(self, path: str, params: dict) -> list:
        s = get_settings()
        last_err: Exception | None = None
        for attempt in range(1, s.okx_max_retries + 1):
            try:
                resp = self.session.get(
                    self.base_url + path, params=params, timeout=self.timeout,
                )
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("code") != "0":
                    raise RuntimeError(
                        f"OKX 业务错误 code={payload.get('code')} msg={payload.get('msg')}"
                    )
                return payload.get("data", [])
            except (requests.RequestException, RuntimeError, ValueError) as e:
                last_err = e
                logger.warning(
                    f"OKX {path} 第 {attempt}/{s.okx_max_retries} 次失败：{e}"
                )
                if attempt < s.okx_max_retries:
                    time.sleep(s.okx_retry_backoff_sec * attempt)

        raise RuntimeError(
            f"OKX {path} 重试 {s.okx_max_retries} 次仍失败"
        ) from last_err

    @staticmethod
    def _validate_bar(bar: str) -> None:
        if bar not in VALID_BARS:
            raise ValueError(
                f"非法 bar: {bar!r}。合法值（H/D/W/M 大写）：{sorted(VALID_BARS)}"
            )

    @staticmethod
    def _parse_candles(raw: list) -> pd.DataFrame:
        """把 OKX 原始二维 list 转 DataFrame，**翻正成 ts 升序**。

        OKX 返回字段顺序：[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        不同时期 API 可能返回 8 或 9 列（个别版本无 volCcyQuote），统一对齐到 9 列。
        """
        if not raw:
            return pd.DataFrame(columns=CANDLES_COLS)

        n_cols_target = len(CANDLES_COLS)
        normalized = []
        for row in raw:
            row = list(row)
            if len(row) == n_cols_target - 1:
                # 老版本无 volCcyQuote：复用 volCcy 填充
                row = row[:7] + [row[6]] + [row[-1]]
            elif len(row) > n_cols_target:
                row = row[:n_cols_target]
            normalized.append(row)

        df = pd.DataFrame(normalized, columns=CANDLES_COLS)
        df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
        for col in ["open", "high", "low", "close",
                    "vol", "vol_ccy", "vol_ccy_quote"]:
            df[col] = df[col].astype(float)
        df["confirm"] = df["confirm"].astype(str) == "1"
        return df.sort_values("ts").reset_index(drop=True)


__all__ = ["OKXClient", "CANDLES_COLS", "VALID_BARS"]
