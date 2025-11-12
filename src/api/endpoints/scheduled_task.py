"""
Scheduled_task相关的API端点
"""

import re
from typing import Optional, List, Any, Dict, Callable, Union
import asyncio
import secrets
import hashlib
import importlib
import string
import time
import json
from urllib.parse import urlparse, urlunparse, quote, unquote
import logging

from datetime import datetime
from sqlalchemy import update, select, func, exc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import httpx
from ...rate_limiter import RateLimiter, RateLimitExceededError
from ...config_manager import ConfigManager
from pydantic import BaseModel, Field, model_validator
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status, Response
from fastapi.security import OAuth2PasswordRequestForm

from ... import crud, models, orm_models, security, scraper_manager
from src import models as api_models
from ...log_manager import get_logs
from ...task_manager import TaskManager, TaskSuccess, TaskStatus
from ...metadata_manager import MetadataSourceManager
from ...scraper_manager import ScraperManager
from ... import tasks
from ...utils import parse_search_keyword
from ...webhook_manager import WebhookManager
from ...image_utils import download_image
from ...scheduler import SchedulerManager
from ...title_recognition import TitleRecognitionManager
from ..._version import APP_VERSION
from thefuzz import fuzz
from ...config import settings
from ...timezone import get_now
from ...database import get_db_session
from ...search_utils import unified_search

logger = logging.getLogger(__name__)


from ..dependencies import (
    get_scraper_manager, get_task_manager, get_scheduler_manager,
    get_webhook_manager, get_metadata_manager, get_config_manager,
    get_rate_limiter, get_title_recognition_manager
)

from ..ui_models import (
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

@router.get("/scheduled-tasks/available-jobs", response_model=List[api_models.AvailableJobInfo])
async def get_available_jobs(request: Request):
    """获取所有已加载的可用任务类型及其名称。"""
    scheduler_manager = request.app.state.scheduler_manager
    jobs = scheduler_manager.get_available_jobs()
    logger.info(f"可用的任务类型: {jobs}")
    return jobs



@router.get("/scheduled-tasks", response_model=List[models.ScheduledTaskInfo], summary="获取所有定时任务")
async def get_scheduled_tasks(
    current_user: models.User = Depends(security.get_current_user),
    scheduler: SchedulerManager = Depends(get_scheduler_manager)
):
    tasks = await scheduler.get_all_tasks()
    return [models.ScheduledTaskInfo.model_validate(t) for t in tasks]



@router.post("/scheduled-tasks", response_model=models.ScheduledTaskInfo, status_code=201, summary="创建定时任务")
async def create_scheduled_task(
    task_data: models.ScheduledTaskCreate,
    current_user: models.User = Depends(security.get_current_user),
    scheduler: SchedulerManager = Depends(get_scheduler_manager)
):
    try:
        new_task = await scheduler.add_task(task_data.name, task_data.jobType, task_data.cronExpression, task_data.isEnabled)
        return models.ScheduledTaskInfo.model_validate(new_task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建定时任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="创建定时任务时发生内部错误")



@router.put("/scheduled-tasks/{taskId}", response_model=models.ScheduledTaskInfo, summary="更新定时任务")
async def update_scheduled_task(
    taskId: str,
    task_data: models.ScheduledTaskUpdate,
    current_user: models.User = Depends(security.get_current_user),
    scheduler: SchedulerManager = Depends(get_scheduler_manager)
):
    updated_task = await scheduler.update_task(taskId, task_data.name, task_data.cronExpression, task_data.isEnabled)
    if not updated_task:
        raise HTTPException(status_code=404, detail="找不到指定的任务ID")
    return models.ScheduledTaskInfo.model_validate(updated_task)



@router.delete("/scheduled-tasks/{taskId}", status_code=204, summary="删除定时任务")
async def delete_scheduled_task(taskId: str, current_user: models.User = Depends(security.get_current_user), scheduler: SchedulerManager = Depends(get_scheduler_manager)):
    await scheduler.delete_task(taskId)



@router.post("/scheduled-tasks/{taskId}/run", status_code=202, summary="立即运行一次定时任务")
async def run_scheduled_task_now(taskId: str, current_user: models.User = Depends(security.get_current_user), scheduler: SchedulerManager = Depends(get_scheduler_manager)):
    try:
        await scheduler.run_task_now(taskId)
        return {"message": "任务已触发运行"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))



