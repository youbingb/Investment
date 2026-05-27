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
from investment.notifier.dedup import SignalDedup
from investment.notifier.feishu import FeishuNotifier
from investment.signals.base import Signal, SignalRule
from investment.signals.loader import load_rules
from investment.trader.executor import TradeExecutor
from investment.trader.paper_account import PaperAccount

DEFAULT_SYMBOLS_CONFIG = (
    Path(__file__).resolve().parents[3] / "config" / "symbols.yaml"
)

# 共享单例（避免每次 cron 触发都新建 client / store / notifier / dedup）
_CLIENT: Optional[OKXClient] = None
_STORE: Optional[KlineStore] = None
_NOTIFIER: Optional[FeishuNotifier] = None
_DEDUP: Optional[SignalDedup] = None
_ACCOUNT: Optional[PaperAccount] = None
_EXECUTOR: Optional[TradeExecutor] = None


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


def get_notifier() -> FeishuNotifier:
    """进程级 FeishuNotifier 单例。"""
    global _NOTIFIER
    if _NOTIFIER is None:
        _NOTIFIER = FeishuNotifier.from_settings()
    return _NOTIFIER


def get_dedup() -> SignalDedup:
    """进程级 SignalDedup 单例。"""
    global _DEDUP
    if _DEDUP is None:
        _DEDUP = SignalDedup()
    return _DEDUP


def reset_notifier_singletons() -> None:
    """测试用：重置 notifier / dedup 单例。"""
    global _NOTIFIER, _DEDUP
    _NOTIFIER = None
    _DEDUP = None


def get_account() -> PaperAccount:
    """进程级 PaperAccount 单例。"""
    global _ACCOUNT
    if _ACCOUNT is None:
        # 从 trading.yaml 读取初始余额
        trading_cfg_path = Path(__file__).resolve().parents[3] / "config" / "trading.yaml"
        initial_balance = 10000.0
        if trading_cfg_path.exists():
            with open(trading_cfg_path, encoding="utf-8") as f:
                tcfg = yaml.safe_load(f) or {}
            initial_balance = float(tcfg.get("initial_balance", 10000.0))
        _ACCOUNT = PaperAccount(initial_balance=initial_balance)
    return _ACCOUNT


def get_executor() -> TradeExecutor:
    """进程级 TradeExecutor 单例。"""
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = TradeExecutor(get_account())
    return _EXECUTOR


def reset_trader_singletons() -> None:
    """测试用：重置 account / executor 单例。"""
    global _ACCOUNT, _EXECUTOR
    _ACCOUNT = None
    _EXECUTOR = None



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


def notify_signals(
    signals: list[Signal],
    *,
    notifier: Optional[FeishuNotifier] = None,
    dedup: Optional[SignalDedup] = None,
) -> int:
    """把信号送进飞书 + 落地去重状态。返回实际发送（含 dry-run）的条数。

    传入的 notifier/dedup 为空时取进程级单例。
    去重命中的信号会跳过，dedup 也不会被 mark_sent（保留旧记录）。
    notifier.send_text 失败的信号同样不入 dedup（下次还能补发）。
    """
    if not signals:
        return 0
    nf = notifier or get_notifier()
    dd = dedup or get_dedup()

    sent = 0
    for sig in signals:
        if not dd.should_send(sig):
            logger.debug(f"去重跳过：{sig.dedup_key()}")
            continue
        if nf.send_text(sig.message):
            dd.mark_sent(sig)
            sent += 1
        else:
            logger.warning(f"通知失败，不计入去重：{sig.dedup_key()}")
    return sent



def execute_trades(
    signals: list[Signal],
    current_prices: Optional[dict[str, float]] = None,
    *,
    executor: Optional[TradeExecutor] = None,
) -> list[dict]:
    """把信号送进交易执行器，返回每笔的处理结果。

    传入的 executor 为空时取进程级单例。
    """
    if not signals:
        return []
    ex = executor or get_executor()
    return ex.process_signals(signals, current_prices)


__all__ = [
    "run_pipeline", "load_watchlist", "notify_signals",
    "execute_trades",
    "PipelineResult", "WatchItem",
    "DEFAULT_SYMBOLS_CONFIG",
    "get_notifier", "get_dedup", "reset_notifier_singletons",
    "get_account", "get_executor", "reset_trader_singletons",
]
