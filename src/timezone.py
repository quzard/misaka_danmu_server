import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import settings

logger = logging.getLogger(__name__)
_app_timezone: ZoneInfo | None = None

def get_app_timezone() -> ZoneInfo:
    """
    获取并缓存由环境变量 TZ 定义的应用程序时区。
    如果 TZ 无效或未设置，则默认为 UTC。
    """
    global _app_timezone
    if _app_timezone is None:
        try:
            tz_str = settings.tz
            if not tz_str:
                logger.warning("环境变量 TZ 未设置，将默认使用 UTC 时区。")
                tz_str = "UTC"
            _app_timezone = ZoneInfo(tz_str)
        except ZoneInfoNotFoundError:
            logger.error(f"环境变量 TZ 的值 '{settings.tz}' 是一个无效的时区，将默认使用 UTC。")
            _app_timezone = ZoneInfo("UTC")
    return _app_timezone

def get_now() -> datetime:
    """获取附加了应用程序时区的当前时间。"""
    return datetime.now(get_app_timezone())