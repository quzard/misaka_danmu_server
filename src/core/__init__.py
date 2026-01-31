"""
核心模块 - 配置、安全、缓存、时区

使用方式:
    from src.core import ConfigManager, get_now, CacheManager, settings
    from src.core import verify_password, get_password_hash
"""

# 配置相关
from .config import settings, Settings
from .config_manager import ConfigManager
from .config_schema import CONFIG_SCHEMA
from .default_configs import DEFAULT_CONFIGS

# 安全相关 (从 src.security 导入)
from src.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_access_token,
    get_current_user,
    get_current_user_optional,
)

# 缓存相关
from .cache_manager import CacheManager

# 时区相关
from .timezone import get_now, get_app_timezone, get_timezone_offset_str

__all__ = [
    # 配置
    'settings',
    'Settings',
    'ConfigManager',
    'CONFIG_SCHEMA',
    'DEFAULT_CONFIGS',
    # 安全
    'verify_password',
    'get_password_hash',
    'create_access_token',
    'decode_access_token',
    'get_current_user',
    'get_current_user_optional',
    # 缓存
    'CacheManager',
    # 时区
    'get_now',
    'get_app_timezone',
    'get_timezone_offset_str',
]

