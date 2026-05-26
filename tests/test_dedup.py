"""阶段 5 单测：SignalDedup。

覆盖：
- 新信号首次 should_send=True；mark_sent 后 should_send=False
- 跨实例从磁盘读回状态保留
- max_entries 触发 LRU 淘汰最旧一条
- 损坏 / 不合法 JSON 文件不抛，退化为空状态
- 文件不存在 + 父目录不存在时 mark_sent 自动 mkdir
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from investment.notifier.dedup import SignalDedup
from investment.signals.base import Signal


def _sig(symbol="BTC-USDT", tf="1H", rule="golden_cross", ts="2026-05-26T10:00", direction="long"):
    return Signal(
        symbol=symbol,
        timeframe=tf,
        rule_name=rule,
        direction=direction,
        bar_ts=pd.Timestamp(ts, tz="UTC"),
        price=100.0,
        message=f"{rule} on {symbol} {tf}",
    )


def test_first_time_should_send(tmp_path: Path):
    sd = SignalDedup(state_path=tmp_path / "sent.json")
    assert sd.should_send(_sig()) is True


def test_mark_sent_then_should_not_send(tmp_path: Path):
    sd = SignalDedup(state_path=tmp_path / "sent.json")
    s = _sig()
    sd.mark_sent(s)
    assert sd.should_send(s) is False


def test_state_persisted_across_instances(tmp_path: Path):
    state = tmp_path / "sent.json"
    sd1 = SignalDedup(state_path=state)
    s = _sig()
    sd1.mark_sent(s)
    sd2 = SignalDedup(state_path=state)
    assert sd2.should_send(s) is False


def test_different_bar_ts_is_not_dedup(tmp_path: Path):
    sd = SignalDedup(state_path=tmp_path / "sent.json")
    s1 = _sig(ts="2026-05-26T10:00")
    s2 = _sig(ts="2026-05-26T11:00")
    sd.mark_sent(s1)
    assert sd.should_send(s2) is True


def test_different_rule_is_not_dedup(tmp_path: Path):
    sd = SignalDedup(state_path=tmp_path / "sent.json")
    s1 = _sig(rule="golden_cross")
    s2 = _sig(rule="dot_pullback")
    sd.mark_sent(s1)
    assert sd.should_send(s2) is True


def test_lru_eviction(tmp_path: Path):
    sd = SignalDedup(state_path=tmp_path / "sent.json", max_entries=2)
    s1 = _sig(ts="2026-05-26T10:00")
    s2 = _sig(ts="2026-05-26T11:00")
    s3 = _sig(ts="2026-05-26T12:00")
    sd.mark_sent(s1)
    sd.mark_sent(s2)
    sd.mark_sent(s3)
    # s1 应该被挤掉，s2/s3 还在
    assert sd.should_send(s1) is True
    assert sd.should_send(s2) is False
    assert sd.should_send(s3) is False


def test_corrupted_json_falls_back_to_empty(tmp_path: Path):
    state = tmp_path / "sent.json"
    state.write_text("{not valid json", encoding="utf-8")
    sd = SignalDedup(state_path=state)
    # 不抛；按空状态启动
    assert sd.should_send(_sig()) is True


def test_non_dict_json_falls_back_to_empty(tmp_path: Path):
    state = tmp_path / "sent.json"
    state.write_text('["a","b"]', encoding="utf-8")
    sd = SignalDedup(state_path=state)
    assert sd.should_send(_sig()) is True


def test_creates_parent_dirs_on_save(tmp_path: Path):
    state = tmp_path / "deeply" / "nested" / "sent.json"
    sd = SignalDedup(state_path=state)
    sd.mark_sent(_sig())
    assert state.exists()
    data = json.loads(state.read_text(encoding="utf-8"))
    # 至少有一条记录
    assert len(data) == 1
    # key 含 symbol|tf|rule|iso_ts 格式
    key = next(iter(data))
    assert "BTC-USDT" in key
    assert "1H" in key
    assert "golden_cross" in key


def test_save_value_is_iso_timestamp(tmp_path: Path):
    sd = SignalDedup(state_path=tmp_path / "sent.json")
    sd.mark_sent(_sig())
    data = json.loads((tmp_path / "sent.json").read_text(encoding="utf-8"))
    value = next(iter(data.values()))
    # ISO 字符串：含 'T' 和 '+00:00'
    assert "T" in value
    assert "+00:00" in value
