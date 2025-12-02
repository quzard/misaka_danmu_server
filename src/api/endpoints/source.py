"""
Source相关的API端点
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

@router.get("/library/source/{sourceId}/details", response_model=models.SourceDetailsResponse, summary="获取单个数据源的详情")
async def get_source_details(
    sourceId: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """获取指定数据源的详细信息，包括其提供方名称。"""
    source_info = await crud.get_anime_source_info(session, sourceId)
    if not source_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return models.SourceDetailsResponse.model_validate(source_info)



@router.delete("/library/source/{sourceId}", status_code=status.HTTP_202_ACCEPTED, summary="提交删除指定数据源的任务")
async def delete_source_from_anime(
    sourceId: int,
    deleteFiles: bool = Query(True, description="是否同时删除弹幕XML文件"),
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """提交一个后台任务来删除一个数据源及其所有关联的分集和弹幕。"""
    source_info = await crud.get_anime_source_info(session, sourceId)
    if not source_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    task_title = f"删除源: {source_info['title']} ({source_info['providerName']})"
    if not deleteFiles:
        task_title += " (保留文件)"
    unique_key = f"delete-source-{sourceId}"
    task_coro = lambda session, callback: tasks.delete_source_task(sourceId, session, callback, delete_files=deleteFiles)
    task_id, _ = await task_manager.submit_task(task_coro, task_title, unique_key=unique_key, run_immediately=True)

    logger.info(f"用户 '{current_user.username}' 提交了删除源 ID: {sourceId} 的任务 (Task ID: {task_id})，deleteFiles={deleteFiles}。")
    return {"message": f"删除源 '{source_info['providerName']}' 的任务已提交。", "taskId": task_id}



@router.put("/library/source/{sourceId}/favorite", status_code=status.HTTP_204_NO_CONTENT, summary="切换数据源的精确标记状态")
async def toggle_source_favorite(
    sourceId: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """切换指定数据源的精确标记状态。一个作品只能有一个精确标记的源。"""
    new_status = await crud.toggle_source_favorite_status(session, sourceId)
    if new_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return # 204 No Content, so no body is needed



@router.put("/library/source/{sourceId}/toggle-incremental-refresh", status_code=status.HTTP_204_NO_CONTENT, summary="切换数据源的定时增量更新状态")
async def toggle_source_incremental_refresh(
    sourceId: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """切换指定数据源的定时增量更新的启用/禁用状态。同一番剧下只能有一个源开启追更。"""
    new_state = await crud.toggle_source_incremental_refresh(session, sourceId)
    if new_state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    logger.info(f"用户 '{current_user.username}' 切换了源 ID {sourceId} 的追更状态为 {new_state}。")


@router.get("/library/source/{sourceId}/episodes", response_model=models.PaginatedEpisodesResponse, summary="获取数据源的所有分集")
async def get_source_episodes(
    sourceId: int,
    page: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(25, ge=1, description="每页数量"),
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取指定数据源下的所有已收录分集列表。"""
    paginated_result = await crud.get_episodes_for_source(session, sourceId, page, pageSize)
    # 修正：返回完整的分页响应对象
    return models.PaginatedEpisodesResponse(
        total=paginated_result["total"],
        list=paginated_result.get("episodes", [])
    )



@router.post("/library/source/{sourceId}/reorder-episodes", status_code=status.HTTP_202_ACCEPTED, summary="重整指定源的分集顺序")
async def reorder_source_episodes(
    sourceId: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """提交一个后台任务，按当前顺序重新编号指定数据源的所有分集。"""
    source_info = await crud.get_anime_source_info(session, sourceId)
    if not source_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    task_title = f"重整集数: {source_info['title']} ({source_info['providerName']})"
    task_coro = lambda session, callback: tasks.reorder_episodes_task(sourceId, session, callback)
    task_id, _ = await task_manager.submit_task(task_coro, task_title, queue_type="management")

    logger.info(f"用户 '{current_user.username}' 提交了重整源 ID: {sourceId} 集数的任务 (Task ID: {task_id})。")
    return {"message": f"重整集数任务 '{task_title}' 已提交。", "taskId": task_id}



@router.post("/library/source/{sourceId}/refresh", status_code=status.HTTP_202_ACCEPTED, summary="刷新指定数据源 (全量或增量)", response_model=UITaskResponse)
async def refresh_anime(
    sourceId: int,
    mode: str = Query("full", description="刷新模式: 'full' (全量) 或 'incremental' (增量)"),
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    task_manager: TaskManager = Depends(get_task_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    config_manager: ConfigManager = Depends(get_config_manager),
    title_recognition_manager = Depends(get_title_recognition_manager)
):
    """
    为指定的数据源启动一个刷新任务。
    - full: 清空并重新抓取所有分集和弹幕。
    - incremental: 尝试抓取最新一集。
    """
    source_info = await crud.get_anime_source_info(session, sourceId)
    if not source_info or not source_info.get("providerName") or not source_info.get("mediaId"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anime not found or missing source information for refresh.")
    
    unique_key = ""
    if mode == "incremental":
        logger.info(f"用户 '{current_user.username}' 为番剧 '{source_info['title']}' (源ID: {sourceId}) 启动了增量刷新任务。")
        # 修正：crud.get_episodes_for_source 现在返回一个带分页的字典
        paginated_result = await crud.get_episodes_for_source(session, sourceId, page_size=9999) # 获取所有分集以找到最大集数
        latest_episode_index = max((ep['episodeIndex'] for ep in paginated_result.get("episodes", [])), default=0)
        next_episode_index = latest_episode_index + 1
        
        unique_key = f"import-{source_info['providerName']}-{source_info['mediaId']}-ep{next_episode_index}"
        task_title = f"增量刷新: {source_info['title']} ({source_info['providerName']}) - 尝试第{next_episode_index}集"
        task_coro = lambda s, cb: tasks.incremental_refresh_task(
            sourceId=sourceId, nextEpisodeIndex=next_episode_index, session=s, manager=scraper_manager,
            task_manager=task_manager, config_manager=config_manager, progress_callback=cb, animeTitle=source_info["title"],
            rate_limiter=rate_limiter, metadata_manager=metadata_manager,
            title_recognition_manager=title_recognition_manager
        )
        message_to_return = f"番剧 '{source_info['title']}' 的增量刷新任务已提交。"
    elif mode == "full":
        logger.info(f"用户 '{current_user.username}' 为番剧 '{source_info['title']}' (源ID: {sourceId}) 启动了全量刷新任务。")
        unique_key = f"full-refresh-{sourceId}"
        task_title = f"全量刷新: {source_info['title']} ({source_info['providerName']})"
        task_coro = lambda s, cb: tasks.full_refresh_task(sourceId, s, scraper_manager, task_manager, rate_limiter, cb, metadata_manager)
        message_to_return = f"番剧 '{source_info['title']}' 的全量刷新任务已提交。"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的刷新模式，必须是 'full' 或 'incremental'。")

    task_id, _ = await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)
    return {"message": message_to_return, "taskId": task_id}



@router.post("/library/sources/delete-bulk", status_code=status.HTTP_202_ACCEPTED, summary="提交批量删除数据源的任务", response_model=UITaskResponse)
async def delete_bulk_sources(
    request_data: BulkDeleteRequest,
    current_user: models.User = Depends(security.get_current_user),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """提交一个后台任务来批量删除多个数据源。"""
    if not request_data.sourceIds:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source IDs list cannot be empty.")

    delete_files = getattr(request_data, 'deleteFiles', True)
    task_title = f"批量删除 {len(request_data.sourceIds)} 个数据源"
    if not delete_files:
        task_title += " (保留文件)"
    ids_str = ",".join(sorted([str(sid) for sid in request_data.sourceIds]))
    unique_key = f"delete-bulk-sources-{hashlib.md5(ids_str.encode('utf-8')).hexdigest()[:8]}"
    task_coro = lambda session, callback: tasks.delete_bulk_sources_task(request_data.sourceIds, session, callback, delete_files=delete_files)
    task_id, _ = await task_manager.submit_task(task_coro, task_title, unique_key=unique_key, run_immediately=True)

    logger.info(f"用户 '{current_user.username}' 提交了批量删除 {len(request_data.sourceIds)} 个源的任务 (Task ID: {task_id})，deleteFiles={delete_files}。")
    return {"message": task_title + "的任务已提交。", "taskId": task_id}







@router.post("/library/source/{source_id}/manual-import", status_code=status.HTTP_202_ACCEPTED, summary="手动导入单个分集弹幕")
async def manual_import_episode(
    source_id: int,
    request_data: models.ManualImportRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    task_manager: TaskManager = Depends(get_task_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter)
):
    """提交一个后台任务，从给定的URL手动导入弹幕。"""
    source_info = await crud.get_anime_source_info(session, source_id)
    if not source_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    provider_name = source_info['providerName']
    
    # 修正：使用 url 或 content 字段，优先使用 content
    content_to_use = request_data.content if request_data.content is not None else request_data.url

    # 仅对非自定义源验证URL
    if provider_name != 'custom':
        if not content_to_use: # Should be caught by validator, but for safety
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="URL is required for non-custom sources.")
        url_prefixes = {
            'bilibili': 'bilibili.com', 'tencent': 'v.qq.com', 'iqiyi': 'iqiyi.com', 'youku': 'youku.com',
            'mgtv': 'mgtv.com', 'acfun': 'acfun.cn', 'renren': 'rrsp.com.cn'
        }
        expected_prefix = url_prefixes.get(provider_name)
        if not expected_prefix or expected_prefix not in content_to_use:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"提供的URL与当前源 '{provider_name}' 不匹配。")

    task_title = f"手动导入: {source_info['title']} - {request_data.title or f'第 {request_data.episodeIndex} 集'} - [{provider_name}]"
    
    # 生成unique_key以防止重复任务
    unique_key = f"manual-import-{source_id}-{request_data.episodeIndex}-{provider_name}"
    
    task_coro = lambda session, callback: tasks.manual_import_task(
        sourceId=source_id, animeId=source_info['animeId'], title=request_data.title,
        episodeIndex=request_data.episodeIndex, content=content_to_use, providerName=provider_name,
        progress_callback=callback, session=session, manager=scraper_manager, rate_limiter=rate_limiter
    )
    task_id, _ = await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)
    return {"message": f"手动导入任务 '{task_title}' 已提交。", "taskId": task_id}



@router.post("/library/source/{sourceId}/batch-import", status_code=status.HTTP_202_ACCEPTED, summary="批量手动导入分集", response_model=UITaskResponse)
async def batch_manual_import(
    sourceId: int,
    payload: models.BatchManualImportRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
):
    """
    为指定的数据源批量手动导入分集。
    - 对于普通数据源，请求体中的 'content' 应为视频URL。
    - 对于 'custom' 数据源，'content' 应为dandanplay格式的XML弹幕文件内容。
    """
    source_info = await crud.get_anime_source_info(session, sourceId)
    if not source_info:
        raise HTTPException(status_code=404, detail="数据源未找到")

    task_title = f"批量手动导入: {source_info['title']} ({source_info['providerName']})"
    unique_key = f"batch-manual-import-{sourceId}"
    try:
        task_coro = lambda s, cb: tasks.batch_manual_import_task(
            sourceId=sourceId,
            animeId=source_info['animeId'],
            providerName=source_info['providerName'],
            items=payload.items,
            progress_callback=cb,
            session=s,
            manager=scraper_manager,
            rate_limiter=rate_limiter
        )
        task_id, _ = await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)
        return {"message": "批量手动导入任务已提交", "taskId": task_id}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# --- 追更与标记管理 ---

class IncrementalRefreshSourceInfo(BaseModel):
    """单个源的追更信息"""
    sourceId: int
    providerName: str
    isFavorited: bool
    incrementalRefreshEnabled: bool
    incrementalRefreshFailures: int
    lastRefreshLatestEpisodeAt: Optional[datetime] = None
    episodeCount: int


class IncrementalRefreshAnimeGroup(BaseModel):
    """按番剧分组的追更信息"""
    animeId: int
    animeTitle: str
    sources: List[IncrementalRefreshSourceInfo]


class IncrementalRefreshSourcesResponse(BaseModel):
    """追更源列表响应（分页）"""
    total: int  # 总番剧数
    totalSources: int  # 总源数
    refreshEnabled: int  # 追更中数量
    favorited: int  # 已标记数量
    list: List[IncrementalRefreshAnimeGroup]


class IncrementalRefreshTaskStatus(BaseModel):
    """增量追更定时任务状态"""
    exists: bool
    enabled: bool
    cronExpression: Optional[str] = None
    nextRunTime: Optional[datetime] = None
    taskId: Optional[str] = None


class BatchToggleIncrementalRequest(BaseModel):
    """批量开启/关闭追更请求"""
    sourceIds: List[int]
    enabled: bool


class BatchSetFavoriteRequest(BaseModel):
    """批量设置标记请求"""
    sourceIds: List[int]


@router.get("/library/incremental-refresh/sources", response_model=IncrementalRefreshSourcesResponse, summary="获取所有源（按番剧分组，支持分页和过滤）")
async def get_incremental_refresh_sources(
    page: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(20, ge=1, le=100, description="每页番剧数量"),
    keyword: str = Query("", description="搜索关键词（匹配番剧名称或源名称）"),
    favoriteFilter: str = Query("all", pattern="^(all|favorited|unfavorited)$", description="标记过滤"),
    refreshFilter: str = Query("all", pattern="^(all|enabled|disabled)$", description="追更过滤"),
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """获取所有源（包括启用和未启用追更的），按番剧分组返回，支持分页和过滤。用于追更管理弹窗。"""
    result = await crud.get_incremental_refresh_sources_grouped(
        session,
        page=page,
        page_size=pageSize,
        keyword=keyword,
        favorite_filter=favoriteFilter,
        refresh_filter=refreshFilter,
    )
    return result


@router.get("/library/incremental-refresh/task-status", response_model=IncrementalRefreshTaskStatus, summary="获取增量追更定时任务状态")
async def get_incremental_refresh_task_status(
    current_user: models.User = Depends(security.get_current_user),
    scheduler: SchedulerManager = Depends(get_scheduler_manager),
):
    """检测增量追更定时任务是否存在及其状态。"""
    tasks_list = await scheduler.get_all_tasks()

    # 查找 job_type 为 "incrementalRefresh" 的任务（驼峰命名）
    for task in tasks_list:
        if task.get("jobType") == "incrementalRefresh":
            return IncrementalRefreshTaskStatus(
                exists=True,
                enabled=task.get("isEnabled", False),
                cronExpression=task.get("cronExpression"),
                nextRunTime=task.get("nextRunTime"),
                taskId=task.get("taskId")
            )

    return IncrementalRefreshTaskStatus(
        exists=False,
        enabled=False,
        cronExpression=None,
        nextRunTime=None,
        taskId=None
    )


@router.post("/library/incremental-refresh/batch-toggle", summary="批量开启/关闭追更")
async def batch_toggle_incremental_refresh(
    payload: BatchToggleIncrementalRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """批量开启或关闭指定源的增量追更。"""
    count = await crud.batch_toggle_incremental_refresh(session, payload.sourceIds, payload.enabled)
    action = "开启" if payload.enabled else "关闭"
    return {"message": f"成功{action} {count} 个源的追更", "count": count}


@router.post("/library/incremental-refresh/batch-favorite", summary="批量设置标记")
async def batch_set_favorite(
    payload: BatchSetFavoriteRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """批量设置标记。每个源会被设为标记，同一番剧下的其他源会被取消标记。"""
    count = await crud.batch_set_favorite(session, payload.sourceIds)
    return {"message": f"成功设置 {count} 个源为标记", "count": count}



