"""飞书自建应用文本消息通知器。

用法：
    from investment.notifier.feishu import FeishuNotifier
    notifier = FeishuNotifier.from_settings()    # 从 .env 读凭证
    notifier.send_text("hello")                  # 失败重试 1 次；DRY_RUN 时只打印

设计要点：
- ``content`` 必须是 JSON 字符串：``json.dumps({"text": "..."})``，不是 dict。
  详见 docs/EXTERNAL_APIS.md "飞书自建应用" 一节。
- ``FEISHU_DRY_RUN=true`` 或凭证未配齐时进入 dry-run 模式：只 logger.info 不发。
  这让开发期不必拿到真实 chat_id 就能跑通主流程。
- lark Client 进程内共享一份（builder 开销不大但每条消息都新建没必要）。
- 失败重试一次；连续失败 ERROR 日志但不抛，避免一次飞书故障让整个 scheduler 死。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from investment.config import Settings, get_settings
from investment.logger import logger


def _missing_credentials(settings: Settings) -> list[str]:
    """返回缺失的飞书字段名列表（用于 dry-run 自动降级提示）。"""
    missing = []
    if not settings.feishu_app_id:
        missing.append("FEISHU_APP_ID")
    if not settings.feishu_app_secret:
        missing.append("FEISHU_APP_SECRET")
    if not settings.feishu_chat_id:
        missing.append("FEISHU_CHAT_ID")
    return missing


class FeishuNotifier:
    """单一职责：把一段文本送进飞书群。

    成员：
        app_id / app_secret: 自建应用凭证（dry_run 时可为空字符串）
        chat_id: 目标群 chat_id（dry_run 时可为空字符串）
        dry_run: True 时不实际调用飞书 API，只打日志
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        chat_id: str,
        *,
        dry_run: bool = False,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.dry_run = dry_run
        self._client: Optional[Any] = None  # 延迟构建，dry_run 时根本不 import lark

    # ---- 工厂 ----

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None) -> "FeishuNotifier":
        """从 ``investment.config.get_settings()`` 装配。

        如果 ``FEISHU_DRY_RUN=true`` 或任意凭证字段为空，自动进入 dry-run；
        缺凭证的情况会 WARNING 列出来，提示用户填 .env。
        """
        s = settings or get_settings()
        missing = _missing_credentials(s)
        dry_run = s.feishu_dry_run or bool(missing)
        if missing and not s.feishu_dry_run:
            logger.warning(
                f"飞书凭证不完整（缺：{', '.join(missing)}），自动进入 dry-run。"
                " 请补全 .env 后联通自检。"
            )
        return cls(
            app_id=s.feishu_app_id,
            app_secret=s.feishu_app_secret,
            chat_id=s.feishu_chat_id,
            dry_run=dry_run,
        )

    # ---- 主入口 ----

    def send_text(self, text: str, *, chat_id: Optional[str] = None) -> bool:
        """发文本消息。返回是否成功（dry-run 视为成功）。

        Args:
            text: 文本内容
            chat_id: 覆盖默认 chat_id；传 None 用 self.chat_id

        失败时重试一次，仍失败 ERROR 日志且返回 False（不抛）。
        """
        target = chat_id or self.chat_id

        if self.dry_run:
            logger.info(f"[飞书 DRY-RUN] → {target or '<未配置 chat_id>'}: {text}")
            return True

        if not target:
            logger.error("飞书 send_text 失败：未指定 chat_id")
            return False

        # 真发：第一次 + 重试一次
        for attempt in (1, 2):
            ok, err = self._do_send(target, text)
            if ok:
                logger.debug(f"飞书发送成功（第 {attempt} 次）：{text[:60]}")
                return True
            logger.warning(f"飞书发送失败（第 {attempt} 次）：{err}")
        logger.error(f"飞书发送两次都失败，放弃：text={text[:60]!r}")
        return False

    # ---- 内部 ----

    def _build_client(self) -> Any:
        """构建 lark Client。延迟到首次真发时才 import，避免 dry-run 启动开销。"""
        if self._client is not None:
            return self._client
        import lark_oapi as lark  # 延迟导入

        self._client = (
            lark.Client.builder()
            .app_id(self.app_id)
            .app_secret(self.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        return self._client

    def _do_send(self, chat_id: str, text: str) -> tuple[bool, str]:
        """单次发送，捕获所有异常返回 (ok, err_msg)。"""
        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            client = self._build_client()
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": text}, ensure_ascii=False))
                    .build()
                )
                .build()
            )
            resp = client.im.v1.message.create(req)
            if not resp.success():
                return False, f"code={resp.code} msg={resp.msg}"
            return True, ""
        except Exception as e:  # 包括网络、SDK 内部异常等
            return False, f"{type(e).__name__}: {e}"


__all__ = ["FeishuNotifier"]
