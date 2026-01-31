"""
弹弹Play 兼容 API 的依赖项函数

使用方式:
    from src.api.dandan.dependencies import (
        get_config_manager, get_task_manager, get_metadata_manager, get_rate_limiter
    )
"""

from fastapi import Request

from src.core import ConfigManager
from src.services import TaskManager, MetadataSourceManager, ScraperManager
from src.rate_limiter import RateLimiter


async def get_config_manager(request: Request) -> ConfigManager:
    """依赖项：从应用状态获取配置管理器"""
    return request.app.state.config_manager


async def get_task_manager(request: Request) -> TaskManager:
    """依赖项：从应用状态获取任务管理器"""
    return request.app.state.task_manager


async def get_metadata_manager(request: Request) -> MetadataSourceManager:
    """依赖项：从应用状态获取元数据源管理器"""
    return request.app.state.metadata_manager


async def get_rate_limiter(request: Request) -> RateLimiter:
    """依赖项：从应用状态获取速率限制器"""
    return request.app.state.rate_limiter


async def get_scraper_manager(request: Request) -> ScraperManager:
    """依赖项：从应用状态获取弹幕源管理器"""
    return request.app.state.scraper_manager

