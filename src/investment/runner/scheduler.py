"""APScheduler 后台调度：按 watchlist 的 timeframe 定时跑 pipeline。

时间策略（全部按 UTC 对齐 OKX bar 收盘时刻，延后 1 分钟跑避免错过收盘）：
- 1m / 5m / 15m / 30m  → 每 N 分钟 +1 秒
- 1H            → 每小时 :01
- 4H            → UTC 00/04/08/12/16/20 时 :01
- 1D            → UTC 00:01
- 其他          → 抛错（避免静默跑错时间）

直接命令行启动：
    python -m investment.runner.scheduler
    # 或
    python scripts/run_forever.py     # 阶段 6 提供
"""
from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from investment.logger import logger, setup_logger
from investment.runner.pipeline import (
    WatchItem,
    load_watchlist,
    notify_signals,
    run_pipeline,
)


def trigger_for_timeframe(timeframe: str) -> CronTrigger:
    """把 OKX bar 字符串映射成 APScheduler CronTrigger（UTC）。"""
    tf = timeframe
    if tf.endswith("m"):
        mins = int(tf[:-1])
        if 60 % mins != 0:
            raise ValueError(f"不规则的分钟周期 {tf}，无法对齐到整 60 分钟")
        return CronTrigger(minute=f"*/{mins}", second=1, timezone="UTC")
    if tf.endswith("H"):
        hours = int(tf[:-1])
        if hours == 1:
            return CronTrigger(minute=1, timezone="UTC")
        if 24 % hours != 0:
            raise ValueError(f"不规则的小时周期 {tf}，无法对齐到 24 小时")
        return CronTrigger(hour=f"*/{hours}", minute=1, timezone="UTC")
    if tf.endswith("D"):
        days = int(tf[:-1])
        if days != 1:
            raise ValueError(f"不支持 {tf}，只支持 1D")
        return CronTrigger(hour=0, minute=1, timezone="UTC")
    raise ValueError(f"不支持的 timeframe: {tf}")


def _job(item: WatchItem) -> None:
    """单个 (symbol, timeframe) 的 cron 触发函数。"""
    try:
        result = run_pipeline(
            symbol=item.symbol,
            timeframe=item.timeframe,
            history_bars=item.history_bars,
        )
    except Exception:
        logger.exception(f"job {item.symbol} {item.timeframe} 出错")
        return

    if not result.signals:
        logger.info(f"{item.symbol} {item.timeframe} 本轮无命中")
        return

    for sig in result.signals:
        logger.info(f"命中：{sig.message}")
    sent = notify_signals(result.signals)
    logger.info(
        f"{item.symbol} {item.timeframe}: {len(result.signals)} 个信号，发出 {sent} 条"
    )


def build_scheduler() -> BlockingScheduler:
    """构建 + 注册所有 watchlist job，返回未启动的 scheduler。"""
    sch = BlockingScheduler(timezone="UTC")
    items = load_watchlist()
    if not items:
        logger.warning("watchlist 为空，scheduler 没有 job")
        return sch

    for item in items:
        try:
            trigger = trigger_for_timeframe(item.timeframe)
        except ValueError as e:
            logger.error(f"跳过 {item.symbol} {item.timeframe}：{e}")
            continue
        sch.add_job(
            _job,
            args=[item],
            trigger=trigger,
            id=f"{item.symbol}_{item.timeframe}",
            replace_existing=True,
            misfire_grace_time=120,  # 错过 2 分钟内还会补跑一次
        )
        logger.info(f"注册 job: {item.symbol} {item.timeframe} → {trigger}")
    return sch


def main() -> int:
    setup_logger()
    sch = build_scheduler()
    if not sch.get_jobs():
        logger.error("没有可调度的 job，退出")
        return 1

    logger.info(f"scheduler 启动，{len(sch.get_jobs())} 个 job，按 Ctrl-C 退出")
    try:
        sch.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到退出信号，scheduler 停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
