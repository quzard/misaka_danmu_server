"""
API依赖注入函数
提供FastAPI端点所需的各种管理器和服务
"""

from fastapi import Request
from ..scraper_manager import ScraperManager
from ..task_manager import TaskManager
from ..scheduler import SchedulerManager
from ..webhook_manager import WebhookManager
from ..metadata_manager import MetadataSourceManager
from ..config_manager import ConfigManager
from ..cache_manager import CacheManager
from ..rate_limiter import RateLimiter


async def get_scraper_manager(request: Request) -> ScraperManager:
    """依赖项：从应用状态获取 Scraper 管理器"""
    return request.app.state.scraper_manager


async def get_task_manager(request: Request) -> TaskManager:
    """依赖项：从应用状态获取任务管理器"""
    return request.app.state.task_manager


async def get_scheduler_manager(request: Request) -> SchedulerManager:
    """依赖项：从应用状态获取 Scheduler 管理器"""
    return request.app.state.scheduler_manager


async def get_webhook_manager(request: Request) -> WebhookManager:
    """依赖项：从应用状态获取 Webhook 管理器"""
    return request.app.state.webhook_manager


async def get_metadata_manager(request: Request) -> MetadataSourceManager:
    """依赖项：从应用状态获取元数据源管理器"""
    return request.app.state.metadata_manager


async def get_config_manager(request: Request) -> ConfigManager:
    """依赖项：从应用状态获取配置管理器"""
    return request.app.state.config_manager


async def get_rate_limiter(request: Request) -> RateLimiter:
    """依赖项：从应用状态获取速率限制器"""
    return request.app.state.rate_limiter


async def get_title_recognition_manager(request: Request):
    """依赖项：从应用状态获取标题识别管理器"""
    return request.app.state.title_recognition_manager


async def get_cache_manager(request: Request) -> CacheManager:
    """依赖项：从应用状态获取缓存管理器"""
    return request.app.state.cache_manager
