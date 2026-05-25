"""loguru 日志初始化。

用法：
    from investment.logger import setup_logger, logger
    setup_logger()                  # 程序入口处调一次
    logger.info("hello")            # 其他地方直接 import logger

LOG_LEVEL 从 .env 读，默认 INFO。
"""
import sys

from loguru import logger

from investment.config import get_settings

_configured = False


def setup_logger() -> None:
    """幂等：多次调用只配置一次。"""
    global _configured
    if _configured:
        return

    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <7}</level> | "
            "<cyan>{name}:{line}</cyan> - <level>{message}</level>"
        ),
        backtrace=False,
        diagnose=False,
    )
    _configured = True


__all__ = ["setup_logger", "logger"]
