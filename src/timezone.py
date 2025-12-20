import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, Union

from .config import settings

logger = logging.getLogger(__name__)
_app_timezone: Optional[ZoneInfo] = None

# 时间格式常量
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

def get_app_timezone() -> ZoneInfo:
    """
    获取并缓存由环境变量 TZ 定义的应用程序时区。
    如果 TZ 无效或未设置，则默认为东八区 (Asia/Shanghai)。
    """
    global _app_timezone
    if _app_timezone is None:
        try:
            tz_str = settings.tz
            if not tz_str:
                logger.warning("环境变量 TZ 未设置，将默认使用东八区 (Asia/Shanghai) 时区。")
                tz_str = "Asia/Shanghai"
            _app_timezone = ZoneInfo(tz_str)
        except ZoneInfoNotFoundError:
            logger.error(f"环境变量 TZ 的值 '{settings.tz}' 是一个无效的时区，将默认使用东八区 (Asia/Shanghai)。")
            _app_timezone = ZoneInfo("Asia/Shanghai")
    return _app_timezone

def get_now() -> datetime:
    """
    获取附加了应用程序时区的当前时间，并返回一个不带时区信息的（naive）datetime对象。
    例如，如果UTC时间为00:00，而时区设置为Asia/Shanghai，此函数将返回 08:00:00。
    """
    return datetime.now(get_app_timezone()).replace(tzinfo=None)

def get_timezone_offset_str() -> str:
    """
    获取应用程序时区的UTC偏移量，并格式化为 '+HH:MM' 或 '-HH:MM' 字符串，
    以便与MySQL的 `SET time_zone` 命令兼容。
    """
    tz = get_app_timezone()
    # 我们需要一个 datetime 对象来正确计算偏移量，特别是对于有夏令时的时区
    now = datetime.now(tz)
    offset = tz.utcoffset(now)

    if offset is None:
        return "+00:00"

    total_seconds = offset.total_seconds()
    sign = '+' if total_seconds >= 0 else '-'
    hours = int(abs(total_seconds) // 3600)
    minutes = int((abs(total_seconds) % 3600) // 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


# ========== 时间字段辅助函数（适配字符串类型时间字段）==========

def get_now_str() -> str:
    """
    获取当前时间的字符串格式 (YYYY-MM-DD HH:MM:SS)
    用于直接赋值给数据库的时间字段
    """
    return get_now().strftime(TIME_FORMAT)


def str_to_datetime(time_str: Optional[str]) -> Optional[datetime]:
    """
    将字符串时间转换为 datetime 对象

    Args:
        time_str: 时间字符串 (YYYY-MM-DD HH:MM:SS) 或 None

    Returns:
        datetime 对象或 None
    """
    if time_str is None:
        return None
    try:
        # 去掉可能的微秒部分
        if '.' in time_str:
            time_str = time_str.split('.')[0]
        return datetime.strptime(time_str, TIME_FORMAT)
    except (ValueError, TypeError) as e:
        logger.warning(f"无法解析时间字符串 '{time_str}': {e}")
        return None


def datetime_to_str(dt: Optional[datetime]) -> Optional[str]:
    """
    将 datetime 对象转换为字符串格式

    Args:
        dt: datetime 对象或 None

    Returns:
        时间字符串 (YYYY-MM-DD HH:MM:SS) 或 None
    """
    if dt is None:
        return None
    return dt.strftime(TIME_FORMAT)


def time_str_add(time_str: str, delta: timedelta) -> str:
    """
    给时间字符串加上时间差

    Args:
        time_str: 时间字符串 (YYYY-MM-DD HH:MM:SS)
        delta: 时间差

    Returns:
        新的时间字符串
    """
    dt = str_to_datetime(time_str)
    if dt is None:
        return time_str
    new_dt = dt + delta
    return datetime_to_str(new_dt) or time_str


def compare_time_str(time_str1: Optional[str], time_str2: Optional[str]) -> int:
    """
    比较两个时间字符串

    Args:
        time_str1: 第一个时间字符串
        time_str2: 第二个时间字符串

    Returns:
        -1: time_str1 < time_str2
         0: time_str1 == time_str2
         1: time_str1 > time_str2

    注意：字符串格式 YYYY-MM-DD HH:MM:SS 可以直接按字典序比较
    """
    if time_str1 is None and time_str2 is None:
        return 0
    if time_str1 is None:
        return -1
    if time_str2 is None:
        return 1

    if time_str1 < time_str2:
        return -1
    elif time_str1 > time_str2:
        return 1
    return 0
