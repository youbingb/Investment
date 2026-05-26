"""阶段 5 单测：FeishuNotifier。

覆盖：
- dry-run 时不调用 lark，只 logger.info
- from_settings 在凭证不全时自动降级 dry-run
- 真发路径：成功 / 一次失败 + 一次成功 / 两次都失败
- _build_client 仅在真发时构建（懒加载）
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from investment.config import Settings
from investment.notifier.feishu import FeishuNotifier, _missing_credentials


def _fake_settings(**overrides) -> Settings:
    defaults = dict(
        feishu_app_id="app123",
        feishu_app_secret="sec456",
        feishu_chat_id="chat789",
        feishu_dry_run=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ============================================================
#  _missing_credentials
# ============================================================

def test_missing_credentials_all_present():
    s = _fake_settings()
    assert _missing_credentials(s) == []


def test_missing_credentials_partial():
    s = _fake_settings(feishu_chat_id="")
    assert _missing_credentials(s) == ["FEISHU_CHAT_ID"]


def test_missing_credentials_all_empty():
    s = _fake_settings(feishu_app_id="", feishu_app_secret="", feishu_chat_id="")
    assert set(_missing_credentials(s)) == {
        "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_CHAT_ID",
    }


# ============================================================
#  from_settings: dry-run 自动降级
# ============================================================

def test_from_settings_dry_run_flag_wins():
    s = _fake_settings(feishu_dry_run=True)
    nf = FeishuNotifier.from_settings(s)
    assert nf.dry_run is True


def test_from_settings_missing_creds_degrades_to_dry_run():
    s = _fake_settings(feishu_chat_id="")
    nf = FeishuNotifier.from_settings(s)
    assert nf.dry_run is True


def test_from_settings_full_creds_no_dry_run():
    s = _fake_settings()
    nf = FeishuNotifier.from_settings(s)
    assert nf.dry_run is False
    assert nf.app_id == "app123"
    assert nf.chat_id == "chat789"


# ============================================================
#  send_text
# ============================================================

def test_send_text_dry_run_returns_true_no_client_built():
    nf = FeishuNotifier("a", "b", "c", dry_run=True)
    assert nf.send_text("hi") is True
    # dry-run 不应触发 _build_client
    assert nf._client is None


def test_send_text_real_mode_missing_chat_id_returns_false():
    nf = FeishuNotifier("a", "b", "", dry_run=False)
    assert nf.send_text("hi") is False


def test_send_text_real_mode_success(monkeypatch):
    nf = FeishuNotifier("a", "b", "c", dry_run=False)
    monkeypatch.setattr(nf, "_do_send", lambda chat, text: (True, ""))
    assert nf.send_text("hello") is True


def test_send_text_retry_then_success(monkeypatch):
    nf = FeishuNotifier("a", "b", "c", dry_run=False)
    calls = []

    def fake(chat, text):
        calls.append((chat, text))
        return (False, "network down") if len(calls) == 1 else (True, "")

    monkeypatch.setattr(nf, "_do_send", fake)
    assert nf.send_text("hi") is True
    assert len(calls) == 2


def test_send_text_two_failures_returns_false(monkeypatch):
    nf = FeishuNotifier("a", "b", "c", dry_run=False)
    calls = []

    def fake(chat, text):
        calls.append(1)
        return False, "boom"

    monkeypatch.setattr(nf, "_do_send", fake)
    assert nf.send_text("hi") is False
    assert len(calls) == 2  # 仅两次：第一次 + 重试一次


def test_send_text_override_chat_id(monkeypatch):
    nf = FeishuNotifier("a", "b", "default-chat", dry_run=False)
    seen_chat = []
    monkeypatch.setattr(
        nf, "_do_send",
        lambda chat, text: (seen_chat.append(chat) or (True, "")),
    )
    nf.send_text("hi", chat_id="other-chat")
    assert seen_chat == ["other-chat"]


# ============================================================
#  _do_send: 透传 lark 异常成 (False, err)
# ============================================================

def test_do_send_catches_exception_returns_false():
    nf = FeishuNotifier("a", "b", "c", dry_run=False)
    # _build_client 抛错（比如 lark 没装），_do_send 应该返回 (False, "...")
    with patch.object(nf, "_build_client", side_effect=RuntimeError("no lark")):
        ok, err = nf._do_send("chat", "text")
    assert ok is False
    assert "RuntimeError" in err
    assert "no lark" in err


def test_do_send_resp_failure_returns_false():
    nf = FeishuNotifier("a", "b", "c", dry_run=False)

    fake_resp = SimpleNamespace(success=lambda: False, code=230001, msg="chat not found")
    fake_client = MagicMock()
    fake_client.im.v1.message.create.return_value = fake_resp

    with patch.object(nf, "_build_client", return_value=fake_client):
        ok, err = nf._do_send("chat", "text")

    assert ok is False
    assert "230001" in err
    assert "chat not found" in err


def test_do_send_resp_success_returns_true():
    nf = FeishuNotifier("a", "b", "c", dry_run=False)

    fake_resp = SimpleNamespace(success=lambda: True, code=0, msg="")
    fake_client = MagicMock()
    fake_client.im.v1.message.create.return_value = fake_resp

    with patch.object(nf, "_build_client", return_value=fake_client):
        ok, err = nf._do_send("chat", "text")

    assert ok is True
    assert err == ""
    # 验证 content 是 JSON 字符串（不是 dict）
    call = fake_client.im.v1.message.create.call_args
    req = call.args[0]
    # request_body.content 是 JSON 字符串
    body = req.request_body
    assert isinstance(body.content, str)
    assert '"text"' in body.content
