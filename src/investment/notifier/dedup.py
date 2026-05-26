"""信号去重：同一根 K 线的同一规则只发一次。

判定键：``Signal.dedup_key()`` = ``(symbol, timeframe, rule_name, bar_ts)``。

实现：
- 持久化到 ``data/cache/sent_signals.json``
- key 序列化成 ``{symbol}|{timeframe}|{rule}|{iso_bar_ts}``，value 是首次发送时间（ISO 字符串，方便人肉看）
- 进程内有 in-memory dict 加速；落盘是 "最多保留 max_entries 条" 的滚动窗口（默认 1000），避免文件无界增长
- 简单实现，不做并发锁；同进程内调度足够，跨进程极小概率重发可接受

用法：
    from investment.notifier.dedup import SignalDedup
    dedup = SignalDedup()
    for sig in signals:
        if dedup.should_send(sig):
            notifier.send_text(sig.message)
            dedup.mark_sent(sig)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from investment.logger import logger
from investment.signals.base import Signal

DEFAULT_STATE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "cache" / "sent_signals.json"
)
DEFAULT_MAX_ENTRIES = 1000


class SignalDedup:
    """读写 ``data/cache/sent_signals.json`` 的去重器。"""

    def __init__(
        self,
        state_path: Optional[Path] = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.max_entries = max_entries
        self._sent: dict[str, str] = self._load()

    # ---- 主入口 ----

    def should_send(self, sig: Signal) -> bool:
        """该信号此前未发过返回 True；已发过返回 False。"""
        return self._key(sig) not in self._sent

    def mark_sent(self, sig: Signal) -> None:
        """标记为已发，立刻落盘。"""
        key = self._key(sig)
        self._sent[key] = datetime.now(tz=timezone.utc).isoformat()
        # LRU 滚动：dict 是插入序，超量从头删
        while len(self._sent) > self.max_entries:
            oldest = next(iter(self._sent))
            self._sent.pop(oldest)
        self._save()

    # ---- 内部 ----

    @staticmethod
    def _key(sig: Signal) -> str:
        """把 dedup_key() 元组扁平成 JSON 友好的字符串。

        bar_ts 用 isoformat 而非 epoch，便于人肉看 JSON 文件时辨认。
        """
        symbol, timeframe, rule, ts = sig.dedup_key()
        return f"{symbol}|{timeframe}|{rule}|{ts.isoformat()}"

    def _load(self) -> dict[str, str]:
        if not self.state_path.exists():
            return {}
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(f"{self.state_path} 内容不是 dict，忽略")
                return {}
            return {str(k): str(v) for k, v in data.items()}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"读 {self.state_path} 失败：{e}，按空状态启动")
            return {}

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self._sent, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"写 {self.state_path} 失败：{e}（去重状态丢失，下次启动会重发）")


__all__ = ["SignalDedup", "DEFAULT_STATE_PATH", "DEFAULT_MAX_ENTRIES"]
