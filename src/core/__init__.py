"""
核心模块 - 配置、安全、时区

使用方式:
    from src.core import settings, get_now
    from src.core import verify_password, get_password_hash

注意: ConfigManager 和 CacheManager 已迁移到 src.db 层
    from src.db import ConfigManager, CacheManager
"""

# 配置相关（纯静态配置，无数据库依赖）
from .config import settings, Settings
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

# 时区相关
from .timezone import get_now, get_app_timezone, get_timezone_offset_str

# 向后兼容：从 src.db 重新导出管理器
# 这样旧代码 `from src.core import ConfigManager` 仍然可以工作
from src.db.config_manager import ConfigManager
from src.db.cache_manager import CacheManager

__all__ = [
    # 配置
    'settings',
    'Settings',
    'CONFIG_SCHEMA',
    'DEFAULT_CONFIGS',
    # 安全
    'verify_password',
    'get_password_hash',
    'create_access_token',
    'decode_access_token',
    'get_current_user',
    'get_current_user_optional',
    # 时区
    'get_now',
    'get_app_timezone',
    'get_timezone_offset_str',
    # 管理器（向后兼容，实际位于 src.db）
    'ConfigManager',
    'CacheManager',
]

