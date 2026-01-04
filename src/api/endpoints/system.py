"""
System相关的API端点
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

from datetime import datetime, timedelta
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
from ...log_manager import get_logs, subscribe_to_logs, unsubscribe_from_logs
from ..._version import APP_VERSION, DOCS_URL, GITHUB_OWNER, GITHUB_REPO
from ...task_manager import TaskManager, TaskSuccess, TaskStatus
from fastapi.responses import StreamingResponse
from ...metadata_manager import MetadataSourceManager
from ...scraper_manager import ScraperManager
from ... import tasks
from ...utils import parse_search_keyword
from ...webhook_manager import WebhookManager
from ...image_utils import download_image
from ...scheduler import SchedulerManager
from ...title_recognition import TitleRecognitionManager
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

@router.get(
    "/comment/{episodeId}",
    response_model=models.PaginatedCommentResponse,
    summary="获取指定分集的弹幕",
)
async def get_comments(
    episodeId: int,
    page: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(100, ge=1, description="每页数量"),
    session: AsyncSession = Depends(get_db_session)
):
    # 检查episode是否存在，如果不存在则返回404
    if not await crud.check_episode_exists(session, episodeId):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")

    comments_data = await crud.fetch_comments(session, episodeId)

    total = len(comments_data)
    start = (page - 1) * pageSize
    end = start + pageSize
    paginated_data = comments_data[start:end]

    comments = [
        models.Comment(cid=i + start, p=item.get("p", ""), m=item.get("m", ""))
        for i, item in enumerate(paginated_data)
    ]
    return models.PaginatedCommentResponse(total=total, list=comments)

@router.get("/version", response_model=Dict[str, str], summary="获取应用版本号和文档链接")
async def get_app_version():
    """获取当前后端应用的版本号和文档链接。"""
    return {"version": APP_VERSION, "docsUrl": DOCS_URL}


class VersionCheckResponse(BaseModel):
    """版本检查响应"""
    currentVersion: str = Field(..., description="当前版本")
    latestVersion: Optional[str] = Field(None, description="最新版本")
    hasUpdate: bool = Field(False, description="是否有更新")
    releaseUrl: Optional[str] = Field(None, description="Release 页面链接")
    changelog: Optional[str] = Field(None, description="更新日志（Markdown）")
    publishedAt: Optional[str] = Field(None, description="发布时间")


# 版本检查缓存
_app_version_cache: Optional[Dict[str, Any]] = None
_app_version_cache_time: Optional[datetime] = None
_APP_VERSION_CACHE_DURATION = timedelta(minutes=30)


@router.get("/version/check", response_model=VersionCheckResponse, summary="检查应用更新")
async def check_app_update(
    config_manager: ConfigManager = Depends(get_config_manager),
    force_refresh: bool = Query(False, description="强制刷新缓存")
):
    """
    检查是否有新版本可用。

    从 GitHub Releases 获取最新版本信息和更新日志。
    """
    global _app_version_cache, _app_version_cache_time

    # 检查缓存
    if not force_refresh and _app_version_cache and _app_version_cache_time:
        cache_age = datetime.now() - _app_version_cache_time
        if cache_age < _APP_VERSION_CACHE_DURATION:
            logger.debug(f"使用缓存的版本检查结果 (缓存时间: {cache_age.total_seconds():.1f}秒)")
            return VersionCheckResponse(**_app_version_cache)

    result = {
        "currentVersion": APP_VERSION,
        "latestVersion": None,
        "hasUpdate": False,
        "releaseUrl": None,
        "changelog": None,
        "publishedAt": None,
    }

    try:
        # 使用 _version.py 中的 GitHub 仓库信息
        api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

        # 获取代理配置
        proxy_enabled = (await config_manager.get("proxyEnabled", "false")).lower() == "true"
        proxy_url = await config_manager.get("proxyUrl", "") if proxy_enabled else None

        # 获取 GitHub Token
        github_token = await config_manager.get("github_token", "")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        timeout = httpx.Timeout(10.0, connect=5.0)

        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_url) as client:
            response = await client.get(api_url, headers=headers)

            if response.status_code == 200:
                release_data = response.json()

                latest_version = release_data.get("tag_name", "").lstrip("v")
                result["latestVersion"] = latest_version
                result["releaseUrl"] = release_data.get("html_url")
                result["changelog"] = release_data.get("body", "")
                result["publishedAt"] = release_data.get("published_at")

                # 比较版本号
                if latest_version and latest_version != APP_VERSION:
                    # 简单的版本比较（假设语义化版本）
                    try:
                        current_parts = [int(x) for x in APP_VERSION.split(".")]
                        latest_parts = [int(x) for x in latest_version.split(".")]
                        result["hasUpdate"] = latest_parts > current_parts
                    except ValueError:
                        # 如果版本号格式不标准，直接字符串比较
                        result["hasUpdate"] = latest_version != APP_VERSION
            else:
                logger.warning(f"获取 GitHub Release 失败: HTTP {response.status_code}")

    except Exception as e:
        logger.warning(f"检查更新失败: {e}")

    # 更新缓存
    _app_version_cache = result
    _app_version_cache_time = datetime.now()

    return VersionCheckResponse(**result)


class ReleaseInfo(BaseModel):
    """单个 Release 信息"""
    version: str = Field(..., description="版本号")
    changelog: str = Field("", description="更新日志")
    publishedAt: Optional[str] = Field(None, description="发布时间")
    releaseUrl: Optional[str] = Field(None, description="Release 页面链接")


class ReleasesResponse(BaseModel):
    """历史 Releases 响应"""
    releases: List[ReleaseInfo] = Field(default_factory=list, description="历史版本列表")


@router.get("/version/releases", response_model=ReleasesResponse, summary="获取历史版本列表")
async def get_release_history(
    config_manager: ConfigManager = Depends(get_config_manager),
    limit: int = Query(10, description="获取的版本数量", ge=1, le=50)
):
    """
    获取历史版本列表和更新日志。

    从 GitHub Releases 获取最近的版本信息。
    """
    releases = []

    try:
        # 使用 _version.py 中的 GitHub 仓库信息
        api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page={limit}"

        # 获取代理配置
        proxy_enabled = (await config_manager.get("proxyEnabled", "false")).lower() == "true"
        proxy_url = await config_manager.get("proxyUrl", "") if proxy_enabled else None

        # 获取 GitHub Token
        github_token = await config_manager.get("github_token", "")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        timeout = httpx.Timeout(10.0, connect=5.0)

        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_url) as client:
            response = await client.get(api_url, headers=headers)

            if response.status_code == 200:
                releases_data = response.json()

                for release in releases_data:
                    version = release.get("tag_name", "").lstrip("v")
                    releases.append(ReleaseInfo(
                        version=version,
                        changelog=release.get("body", ""),
                        publishedAt=release.get("published_at"),
                        releaseUrl=release.get("html_url")
                    ))
            else:
                logger.warning(f"获取 GitHub Releases 列表失败: HTTP {response.status_code}")

    except Exception as e:
        logger.warning(f"获取历史版本失败: {e}")

    return ReleasesResponse(releases=releases)



@router.get("/logs", response_model=List[str], summary="获取最新的服务器日志")
async def get_server_logs(current_user: models.User = Depends(security.get_current_user)):
    """获取存储在内存中的最新日志条目。"""
    return get_logs()


@router.get("/logs/stream", summary="SSE实时日志推送")
async def stream_server_logs(current_user: models.User = Depends(security.get_current_user)):
    """使用Server-Sent Events实时推送服务器日志。"""

    async def event_generator():
        # 创建一个队列用于接收新日志
        queue = asyncio.Queue()

        # 订阅日志更新
        subscribe_to_logs(queue)

        try:
            # 首先发送当前所有日志
            current_logs = get_logs()
            for log in reversed(current_logs):  # 反转以保持时间顺序
                # SSE支持多行: 每行前加 "data: " 前缀,最后加 "\n\n" 表示消息结束
                if '\n' in log:
                    # 多行日志,每行都加 data: 前缀
                    lines = log.split('\n')
                    for line in lines:
                        yield f"data: {line}\n"
                    yield "\n"  # 消息结束标记
                else:
                    # 单行日志
                    yield f"data: {log}\n\n"

            # 然后持续推送新日志
            while True:
                try:
                    # 等待新日志,设置超时以便定期发送心跳
                    log = await asyncio.wait_for(queue.get(), timeout=30.0)
                    # SSE支持多行: 每行前加 "data: " 前缀,最后加 "\n\n" 表示消息结束
                    if '\n' in log:
                        # 多行日志,每行都加 data: 前缀
                        lines = log.split('\n')
                        for line in lines:
                            yield f"data: {line}\n"
                        yield "\n"  # 消息结束标记
                    else:
                        # 单行日志
                        yield f"data: {log}\n\n"
                except asyncio.TimeoutError:
                    # 发送心跳注释以保持连接
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            logger.debug("SSE日志流连接被客户端关闭")
        finally:
            # 取消订阅
            unsubscribe_from_logs(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        }
    )

@router.post("/cache/clear", status_code=status.HTTP_200_OK, summary="清除所有缓存")

async def clear_all_caches(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
): #noqa
    """清除数据库中存储的所有缓存数据（包括搜索结果、分集列表、后备搜索缓存、弹幕缓存等）。"""
    # 清除数据库缓存（所有缓存现在都存储在数据库中）
    deleted_count = await crud.clear_all_cache(session)

    logger.info(f"用户 '{current_user.username}' 清除了所有缓存: 数据库 {deleted_count} 条。")
    return {
        "message": f"成功清除缓存: 数据库 {deleted_count} 条。",
        "database_cache": deleted_count
    }



@router.get("/external-logs", response_model=List[models.ExternalApiLogInfo], summary="获取最新的外部API访问日志")
async def get_external_api_logs(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    logs = await crud.get_external_api_logs(session)
    return [models.ExternalApiLogInfo.model_validate(log) for log in logs]



@router.get("/ua-rules", response_model=List[models.UaRule], summary="获取所有UA规则")
async def get_ua_rules(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    rules = await crud.get_ua_rules(session)
    return [models.UaRule.model_validate(r) for r in rules]




@router.post("/ua-rules", response_model=models.UaRule, status_code=201, summary="添加UA规则")
async def add_ua_rule(
    ruleData: models.UaRuleCreate,
    currentUser: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    try:
        rule_id = await crud.add_ua_rule(session, ruleData.uaString)
        # This is a bit inefficient but ensures we return the full object
        rules = await crud.get_ua_rules(session)
        new_rule = next((r for r in rules if r['id'] == rule_id), None)
        return models.UaRule.model_validate(new_rule)
    except Exception:
        raise HTTPException(status_code=409, detail="该UA规则已存在。")



@router.delete("/ua-rules/{ruleId}", status_code=204, summary="删除UA规则")
async def delete_ua_rule(
    ruleId: str,
    currentUser: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    try:
        rule_id_int = int(ruleId)
    except ValueError:
        raise HTTPException(status_code=400, detail="规则ID必须是有效的整数。")

    deleted = await crud.delete_ua_rule(session, rule_id_int)
    if not deleted:
        raise HTTPException(status_code=404, detail="找不到指定的规则ID。")



@router.get("/rate-limit/status", response_model=RateLimitStatusResponse, summary="获取所有流控规则的状态")
async def get_rate_limit_status(
    session: AsyncSession = Depends(get_db_session),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter)
):
    """获取所有流控规则的当前状态，包括全局和各源的配额使用情况。"""
    # 在获取状态前，先触发一次全局流控的检查，这会强制重置过期的计数器
    try:
        await rate_limiter.check("__ui_status_check__")
    except RateLimitExceededError:
        # 我们只关心检查和重置的副作用，不关心它是否真的超限，所以忽略此错误
        pass
    except Exception as e:
        # 记录其他潜在错误，但不中断状态获取
        logger.error(f"在获取流控状态时，检查全局流控失败: {e}")

    global_enabled = rate_limiter.enabled
    global_limit = rate_limiter.global_limit
    period_seconds = rate_limiter.global_period_seconds

    all_states = await crud.get_all_rate_limit_states(session)
    states_map = {s.providerName: s for s in all_states}

    global_state = states_map.get("__global__")
    seconds_until_reset = 0
    if global_state:
        # 使用 get_now() 确保时区一致性
        time_since_reset = get_now().replace(tzinfo=None) - global_state.lastResetTime
        seconds_until_reset = max(0, int(period_seconds - time_since_reset.total_seconds()))

    provider_items = []
    # 修正：从数据库获取所有已配置的搜索源，而不是调用一个不存在的方法
    all_scrapers_raw = await crud.get_all_scraper_settings(session)
    # 修正：在显示流控状态时，排除不产生网络请求的 'custom' 源
    all_scrapers = [s for s in all_scrapers_raw if s['providerName'] != 'custom']
    for scraper_setting in all_scrapers:
        provider_name = scraper_setting['providerName']
        provider_state = states_map.get(provider_name)
        
        quota: Union[int, str] = "∞"
        try:
            scraper_instance = scraper_manager.get_scraper(provider_name)
            provider_quota = getattr(scraper_instance, 'rate_limit_quota', None)
            if provider_quota is not None and provider_quota > 0:
                quota = provider_quota
        except ValueError:
            pass

        provider_items.append(RateLimitProviderStatus(
            providerName=provider_name,
            requestCount=provider_state.requestCount if provider_state else 0,
            quota=quota
        ))

    # 修正：将秒数转换为可读的字符串以匹配响应模型
    global_period_str = f"{period_seconds} 秒"

    # 获取后备流控状态 (合并match和search)
    fallback_match_state = states_map.get("__fallback_match__")
    fallback_search_state = states_map.get("__fallback_search__")

    match_count = fallback_match_state.requestCount if fallback_match_state else 0
    search_count = fallback_search_state.requestCount if fallback_search_state else 0
    total_fallback_count = match_count + search_count

    fallback_status = FallbackRateLimitStatus(
        totalCount=total_fallback_count,
        totalLimit=rate_limiter.fallback_limit,
        matchCount=match_count,
        searchCount=search_count
    )

    return RateLimitStatusResponse(
        enabled=global_enabled,
        verificationFailed=rate_limiter._verification_failed,
        globalRequestCount=global_state.requestCount if global_state else 0,
        globalLimit=global_limit,
        globalPeriod=global_period_str,
        secondsUntilReset=seconds_until_reset,
        providers=provider_items,
        fallback=fallback_status
    )


# ==================== Docker 容器管理 API ====================

from ...docker_utils import (
    is_docker_socket_available,
    get_docker_status,
    get_container_stats,
    restart_container,
    restart_via_exit,
    pull_image_stream,
    update_container_with_watchtower
)
import json


class DockerStatusResponse(BaseModel):
    """Docker 状态响应"""
    sdkInstalled: bool = Field(..., description="Docker SDK 是否已安装")
    socketAvailable: bool = Field(..., description="Docker socket 是否可用")
    socketPath: str = Field(..., description="Docker socket 路径")
    canRestart: bool = Field(..., description="是否可以通过 Docker API 重启")
    canUpdate: bool = Field(..., description="是否可以通过 Docker API 更新")
    message: str = Field(..., description="状态消息")


class RestartResponse(BaseModel):
    """重启响应"""
    success: bool
    message: str
    method: str = Field(..., description="重启方式: docker_api 或 process_exit")


@router.get("/docker/status", response_model=DockerStatusResponse, summary="获取 Docker 状态")
async def get_docker_status_endpoint(
    _: models.User = Depends(security.get_current_user)
):
    """
    获取 Docker 连接状态，用于判断是否可以使用 Docker API 进行重启/更新操作。
    """
    status = get_docker_status()
    return DockerStatusResponse(**status)


@router.get("/docker/stats", summary="获取容器资源使用统计")
async def get_docker_stats_endpoint(
    _: models.User = Depends(security.get_current_user)
):
    """
    获取当前容器的资源使用统计信息，包括 CPU、内存、网络 I/O 等。

    自动检测当前运行的容器，无需手动指定容器名称。
    需要 Docker socket 可用才能获取统计信息。
    """
    # 不传参数，自动检测当前容器
    stats = get_container_stats()
    return stats


@router.post("/restart", response_model=RestartResponse, summary="重启服务")
async def restart_service(
    current_user: models.User = Depends(security.get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """
    重启服务。

    - 如果 Docker socket 可用，通过 Docker API 重启容器
    - 如果 Docker socket 不可用，通过退出进程触发容器重启（依赖 restart policy）
    """
    container_name = await config_manager.get("containerName", "misaka-danmu-server")

    if is_docker_socket_available():
        # 使用 Docker API 重启
        result = await restart_container(container_name)
        if result.get("success"):
            logger.info(f"用户 '{current_user.username}' 通过 Docker API 重启了容器 '{container_name}'")
            return RestartResponse(
                success=True,
                message=result["message"],
                method="docker_api"
            )
        elif result.get("fallback"):
            # Docker API 失败，降级到进程退出
            logger.warning(f"Docker API 重启失败，降级到进程退出: {result['message']}")

    # 通过进程退出重启
    logger.info(f"用户 '{current_user.username}' 通过进程退出方式重启服务")

    # 创建后台任务延迟退出，让响应先返回
    async def delayed_exit():
        await asyncio.sleep(1)
        restart_via_exit()

    asyncio.create_task(delayed_exit())

    return RestartResponse(
        success=True,
        message="服务将在 1 秒后重启，请稍后刷新页面",
        method="process_exit"
    )


@router.get("/update/stream", summary="流式更新服务")
async def stream_update(
    current_user: models.User = Depends(security.get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """
    通过 SSE 流式返回更新进度。

    流程：
    1. 拉取最新镜像
    2. 使用 watchtower 更新容器
    """
    if not is_docker_socket_available():
        async def error_stream():
            yield f"data: {json.dumps({'status': 'Docker socket 不可用，无法执行更新', 'event': 'ERROR'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    container_name = await config_manager.get("containerName", "misaka-danmu-server")
    image_name = await config_manager.get("dockerImageName", "yanyutin753/misaka_danmu_server:latest")
    proxy_url = await config_manager.get("proxyUrl", "")
    proxy_enabled = (await config_manager.get("proxyEnabled", "false")).lower() == "true"

    effective_proxy = proxy_url if proxy_enabled and proxy_url else None

    async def generate_progress():
        try:
            # 阶段 1: 拉取镜像
            for progress in pull_image_stream(image_name, effective_proxy):
                yield f"data: {json.dumps(progress)}\n\n"

                # 如果已是最新或出错，直接结束
                if progress.get("event") in ("UP_TO_DATE", "ERROR"):
                    if progress.get("event") == "UP_TO_DATE":
                        yield f"data: {json.dumps({'status': '无需更新', 'event': 'DONE'})}\n\n"
                    return

            # 阶段 2: 使用 watchtower 更新
            for progress in update_container_with_watchtower(container_name):
                yield f"data: {json.dumps(progress)}\n\n"

        except Exception as e:
            logger.error(f"更新过程出错: {e}")
            yield f"data: {json.dumps({'status': f'更新失败: {str(e)}', 'event': 'ERROR'})}\n\n"

    logger.info(f"用户 '{current_user.username}' 开始更新服务 (镜像: {image_name})")
    return StreamingResponse(generate_progress(), media_type="text/event-stream")

