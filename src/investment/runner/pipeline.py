"""单次完整 pipeline：拉 K 线 → 算指标 → 跑信号规则。

阶段 4 提供给阶段 5 的飞书通知调用；阶段 5 之前先 print 到 stdout。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from investment.data.kline_store import KlineStore
from investment.data.okx_client import OKXClient
from investment.indicators import compute_all
from investment.logger import logger
from investment.signals.base import Signal, SignalRule
from investment.signals.loader import load_rules

DEFAULT_SYMBOLS_CONFIG = (
    Path(__file__).resolve().parents[3] / "config" / "symbols.yaml"
)

# 共享单例（避免每次 cron 触发都新建 client / store）
_CLIENT: Optional[OKXClient] = None
_STORE: Optional[KlineStore] = None


def _client() -> OKXClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OKXClient()
    return _CLIENT


def _store() -> KlineStore:
    global _STORE
    if _STORE is None:
        _STORE = KlineStore()
    return _STORE


@dataclass
class PipelineResult:
    symbol: str
    timeframe: str
    rows: int
    signals: list[Signal] = field(default_factory=list)

    @property
    def hit(self) -> bool:
        return bool(self.signals)


@dataclass
class WatchItem:
    symbol: str
    timeframe: str
    history_bars: int = 300


# ---------------- 主入口 ----------------

def run_pipeline(
    symbol: str,
    timeframe: str,
    history_bars: int = 300,
    rules: Optional[list[SignalRule]] = None,
    client: Optional[OKXClient] = None,
    store: Optional[KlineStore] = None,
) -> PipelineResult:
    """跑一次完整 pipeline。

    Args:
        symbol: 如 "BTC-USDT"
        timeframe: 如 "1H"
        history_bars: 至少 > max MA 周期（120），默认 300
        rules: 指定规则列表（测试用）；不传时 load_rules() 读 config/signals.yaml
        client / store: 可注入（测试用）；不传时用进程级单例
    """
    cl = client or _client()
    st = store or _store()
    rs = rules if rules is not None else load_rules()

    logger.info(f"pipeline 开始：{symbol} {timeframe} (history_bars={history_bars})")
    df = st.get_or_fetch(cl, symbol, timeframe, history_bars)
    if df.empty:
        logger.warning(f"{symbol} {timeframe} 没拉到数据，pipeline 终止")
        return PipelineResult(symbol, timeframe, rows=0)

    df = compute_all(df)
    signals: list[Signal] = []
    for rule in rs:
        try:
            sig = rule.evaluate(df, symbol=symbol, timeframe=timeframe)
        except Exception as e:
            logger.exception(f"规则 {rule.name} 在 {symbol} {timeframe} 抛错：{e}")
            continue
        if sig is not None:
            signals.append(sig)
            logger.info(f"命中：{sig.message}")
        else:
            logger.debug(f"未命中 {rule.name} on {symbol} {timeframe}")

    logger.info(
        f"pipeline 结束：{symbol} {timeframe} rows={len(df)} hits={len(signals)}"
    )
    return PipelineResult(symbol, timeframe, rows=len(df), signals=signals)


def load_watchlist(config_path: Optional[Path] = None) -> list[WatchItem]:
    """读 config/symbols.yaml，返回 enabled 的 (symbol, timeframe) 平铺列表。

    一个 watchlist 条目可以指定多个 timeframes，平铺成多个 WatchItem。
    """
    path = config_path or DEFAULT_SYMBOLS_CONFIG
    if not path.exists():
        logger.warning(f"symbols 配置不存在：{path}")
        return []

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    history_bars = int(cfg.get("fetch", {}).get("history_bars", 300))

    items: list[WatchItem] = []
    for entry in cfg.get("watchlist", []) or []:
        if not isinstance(entry, dict):
            continue
        if not entry.get("enabled", True):
            continue
        symbol = entry.get("symbol")
        if not symbol:
            continue
        timeframes = entry.get("timeframes") or ["1H"]
        for tf in timeframes:
            items.append(WatchItem(symbol=symbol, timeframe=tf, history_bars=history_bars))
    return items


__all__ = [
    "run_pipeline", "load_watchlist",
    "PipelineResult", "WatchItem",
    "DEFAULT_SYMBOLS_CONFIG",
]
