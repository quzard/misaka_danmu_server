"""
UI API 路由模块
提供前端界面所需的API端点
"""
import logging
from fastapi import APIRouter
from typing import List, Optional, Callable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

# 导入模型和工具
from .. import models, orm_models, crud
from ..task_manager import TaskManager, TaskSuccess
from ..scraper_manager import ScraperManager
from ..scheduler_manager import SchedulerManager
from ..webhook_manager import WebhookManager
from ..metadata_manager import MetadataManager
from ..config_manager import ConfigManager
from ..rate_limiter import RateLimiter
from ..title_recognition import TitleRecognitionManager
from ..utils import download_image

# 导入依赖注入函数
from .dependencies import (
    get_scraper_manager, get_task_manager, get_scheduler_manager,
    get_webhook_manager, get_metadata_manager, get_config_manager,
    get_rate_limiter, get_title_recognition_manager
)

# 导入共享Pydantic模型
from .ui_models import (
    UITaskResponse, UIProviderSearchResponse, RefreshPosterRequest,
    ReassociationRequest, BulkDeleteEpisodesRequest, BulkDeleteRequest,
    ProxyTestResult, ProxyTestRequest, FullProxyTestResponse,
    TitleRecognitionContent, TitleRecognitionUpdateResponse,
    ApiTokenUpdate, CustomDanmakuPathRequest, CustomDanmakuPathResponse,
    MatchFallbackTokensResponse, ConfigValueResponse, ConfigValueRequest,
    TmdbReverseLookupConfig, TmdbReverseLookupConfigRequest,
    ImportFromUrlRequest, GlobalFilterSettings,
    RateLimitProviderStatus, FallbackRateLimitStatus, RateLimitStatusResponse,
    WebhookSettings, WebhookTaskItem, PaginatedWebhookTasksResponse,
    AITestRequest, AITestResponse
)

router = APIRouter()
auth_router = APIRouter()
logger = logging.getLogger(__name__)
