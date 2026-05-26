"""命令行：长跑模式 — 启动 scheduler，按 watchlist 定时跑 pipeline + 推飞书。

用法：
    # 启动守护（前台阻塞），Ctrl-C 退出
    python scripts/run_forever.py

    # 干跑（列出 job 不真启动），方便检查 cron 表达式 / 凭证 / watchlist 是否对
    python scripts/run_forever.py --list-jobs

设计：
- 启动前打一段横幅，让用户一眼看到：watchlist 几条、dry-run 是否生效、chat_id 长啥样
- 凭证齐全时显式提示 "将真实推送"；缺凭证时显式提示走 dry-run
- BlockingScheduler 自带 SIGINT 优雅退出（无须手动接信号）

部署提示：
- Linux：用 systemd unit 守护这个脚本（参考 README "部署"）
- Windows：用 nssm 把这个脚本注册成服务
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment.config import get_settings  # noqa: E402
from investment.logger import logger, setup_logger  # noqa: E402
from investment.runner.pipeline import get_notifier  # noqa: E402
from investment.runner.scheduler import build_scheduler  # noqa: E402


def _print_banner() -> None:
    s = get_settings()
    nf = get_notifier()
    chat_disp = s.feishu_chat_id or "<未配置>"
    if len(chat_disp) > 12:
        chat_disp = chat_disp[:8] + "…" + chat_disp[-4:]
    mode = "DRY-RUN（不真发飞书）" if nf.dry_run else "真实推送已启用"

    print("=" * 64)
    print("Investment 长跑模式启动中")
    print(f"  日志级别 : {s.log_level}")
    print(f"  通知模式 : {mode}")
    print(f"  chat_id  : {chat_disp}")
    print(f"  飞书 app : {s.feishu_app_id[:8] + '…' if s.feishu_app_id else '<未配置>'}")
    print("=" * 64)


def main() -> int:
    setup_logger()

    parser = argparse.ArgumentParser(description="长跑模式：启动 scheduler")
    parser.add_argument(
        "--list-jobs", action="store_true",
        help="只列出将注册的 job，不真启动 scheduler",
    )
    args = parser.parse_args()

    _print_banner()

    sch = build_scheduler()
    jobs = sch.get_jobs()
    if not jobs:
        logger.error("没有可调度的 job — 检查 config/symbols.yaml 的 watchlist 是否启用")
        return 1

    print(f"已注册 {len(jobs)} 个 job：")
    for job in jobs:
        print(f"  • {job.id:<24}  trigger={job.trigger}")
    print()

    if args.list_jobs:
        print("--list-jobs 模式：不启动 scheduler。退出。")
        return 0

    logger.info("scheduler 启动，按 Ctrl-C 退出")
    try:
        sch.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，scheduler 停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
