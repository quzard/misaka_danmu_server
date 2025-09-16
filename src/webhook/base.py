from abc import ABC, abstractmethod
import logging
import re
from datetime import timedelta
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from fastapi import Request

from .. import crud
from ..config_manager import ConfigManager
from ..task_manager import TaskManager
from ..rate_limiter import RateLimiter
from ..scraper_manager import ScraperManager
from ..metadata_manager import MetadataSourceManager

class WebhookPayload(BaseModel):
    """定义 Webhook 负载的通用结构。"""
    event_type: str
    media_title: str
    season_number: Optional[int] = None
    episode_number: Optional[int] = None

class BaseWebhook(ABC):
    """所有 Webhook 处理器的抽象基类。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], task_manager: TaskManager, scraper_manager: ScraperManager, rate_limiter: RateLimiter, metadata_manager: MetadataSourceManager, config_manager: ConfigManager):
        self._session_factory = session_factory
        self.task_manager = task_manager
        self.scraper_manager = scraper_manager
        self.rate_limiter = rate_limiter
        self.metadata_manager = metadata_manager
        self.config_manager = config_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def handle(self, request: Request, webhook_source: str):
        """处理传入的 Webhook 负载。"""
        raise NotImplementedError

    async def dispatch_task(
        self,
        task_title: str,
        unique_key: str,
        payload: Dict[str, Any],
        webhook_source: str
    ):
        """
        将解析后的 Webhook 请求分发到数据库或任务管理器。
        """
        async with self._session_factory() as session:
            # 检查全局开关和过滤规则的逻辑已移至 webhook/tasks.py 中，
            # 以确保即使任务被延时，规则也能在执行时被应用。
            delayed_enabled = (await self.config_manager.get("webhookDelayedImportEnabled", "false")).lower() == 'true'
            delay_hours_str = await self.config_manager.get("webhookDelayedImportHours", "24")
            delay_hours = int(delay_hours_str) if delay_hours_str.isdigit() else 24

            await crud.create_webhook_task(
                session, task_title, unique_key, payload, webhook_source,
                delayed_enabled, timedelta(hours=delay_hours)
            )
            await session.commit()