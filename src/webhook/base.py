from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, Optional

import aiomysql
from fastapi import Request
from pydantic import BaseModel

from ..task_manager import TaskManager
from ..scraper_manager import ScraperManager

class WebhookPayload(BaseModel):
    """定义 Webhook 负载的通用结构。"""
    event_type: str
    media_title: str
    season_number: Optional[int] = None
    episode_number: Optional[int] = None

class BaseWebhook(ABC):
    """所有 Webhook 处理器的抽象基类。"""

    def __init__(self, pool: aiomysql.Pool, task_manager: TaskManager, scraper_manager: ScraperManager):
        self.pool = pool
        self.task_manager = task_manager
        self.scraper_manager = scraper_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def handle(self, request: Request):
        """处理传入的 Webhook 负载。"""
        raise NotImplementedError