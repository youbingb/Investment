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

    _force_utf8_console()

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


def _force_utf8_console() -> None:
    """Windows 控制台默认 GBK / CP936，中文会乱码。

    Python 3.7+ 的 ``sys.stdout/stderr.reconfigure`` 能把流编码改成 UTF-8；
    失败就静默忽略（容器、IDE、被重定向到文件时可能没这个方法）。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


__all__ = ["setup_logger", "logger"]
