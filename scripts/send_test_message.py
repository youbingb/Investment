"""阶段 5 联通自检：往飞书发一条 "Investment 联通测试 + UTC 时间" 文本。

用法：
    python scripts/send_test_message.py                  # 用 .env 中的 chat_id
    python scripts/send_test_message.py --chat-id XXXX   # 临时指定 chat_id
    FEISHU_DRY_RUN=true python scripts/send_test_message.py  # 不真发，看 stdout

什么时候用：
- 第一次拿到飞书 app_id / app_secret / chat_id，验证三件套 + 网络都通
- 调试规则之前，先确认 notifier 是否能成功送达
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment.logger import logger, setup_logger  # noqa: E402
from investment.notifier.feishu import FeishuNotifier  # noqa: E402


def main() -> int:
    setup_logger()

    parser = argparse.ArgumentParser(description="飞书联通自检：发一条测试消息")
    parser.add_argument("--chat-id", default=None, help="覆盖 .env 中的 FEISHU_CHAT_ID")
    parser.add_argument(
        "--text",
        default=None,
        help='自定义文本；默认 "Investment 联通测试 <UTC iso ts>"',
    )
    args = parser.parse_args()

    notifier = FeishuNotifier.from_settings()
    now_iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text = args.text or f"Investment 联通测试 {now_iso}"

    ok = notifier.send_text(text, chat_id=args.chat_id)

    if ok and notifier.dry_run:
        logger.info("dry-run 完成（未真实调用飞书 API）。"
                    " 想要真发，把 .env 里 FEISHU_DRY_RUN 设 false 并填齐凭证。")
        return 0
    if ok:
        logger.info("已发送：请去飞书群里确认是否收到。")
        return 0
    logger.error("发送失败。请检查 app_id / app_secret / chat_id 是否正确，机器人是否在群内。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
