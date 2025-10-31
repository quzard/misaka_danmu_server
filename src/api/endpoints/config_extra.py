"""
Config_extra相关的API端点
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

@router.get("/config/proxy", response_model=models.ProxySettingsResponse, summary="获取代理配置")

async def get_proxy_settings(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取全局代理配置。"""
    proxy_url_task = crud.get_config_value(session, "proxyUrl", "")
    proxy_enabled_task = crud.get_config_value(session, "proxyEnabled", "false")
    proxy_url, proxy_enabled_str = await asyncio.gather(proxy_url_task, proxy_enabled_task)

    proxy_enabled = proxy_enabled_str.lower() == 'true'
    
    # Parse the URL into components
    protocol, host, port, username, password = "http", None, None, None, None
    if proxy_url:
        try:
            p = urlparse(proxy_url)
            protocol = p.scheme or "http"
            host = p.hostname
            port = p.port
            username = unquote(p.username) if p.username else None
            password = unquote(p.password) if p.password else None
        except Exception as e:
            logger.error(f"解析存储的代理URL '{proxy_url}' 失败: {e}")

    return models.ProxySettingsResponse(
        proxyProtocol=protocol,
        proxyHost=host,
        proxyPort=port,
        proxyUsername=username,
        proxyPassword=password,
        proxyEnabled=proxy_enabled
    )



@router.put("/config/proxy", status_code=status.HTTP_204_NO_CONTENT, summary="更新代理配置")
async def update_proxy_settings(
    payload: models.ProxySettingsUpdate,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """更新全局代理配置。"""
    proxy_url = ""
    if payload.proxyHost and payload.proxyPort:
        # URL-encode username and password to handle special characters like '@'
        userinfo = ""
        if payload.proxyUsername:
            userinfo = quote(payload.proxyUsername)
            if payload.proxyPassword:
                userinfo += ":" + quote(payload.proxyPassword)
            userinfo += "@"
        
        proxy_url = f"{payload.proxyProtocol}://{userinfo}{payload.proxyHost}:{payload.proxyPort}"

    await crud.update_config_value(session, "proxyUrl", proxy_url)
    config_manager.invalidate("proxyUrl")
    
    await crud.update_config_value(session, "proxyEnabled", str(payload.proxyEnabled).lower())
    config_manager.invalidate("proxyEnabled")

    await crud.update_config_value(session, "proxySslVerify", str(payload.proxySslVerify).lower())
    config_manager.invalidate("proxySslVerify")
    logger.info(f"用户 '{current_user.username}' 更新了代理配置。")



@router.post("/proxy/test", response_model=FullProxyTestResponse, summary="测试代理连接和延迟")
async def test_proxy_latency(
    request: ProxyTestRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """
    测试代理连接和到各源的延迟。
    - 如果提供了代理URL，则通过代理测试。
    - 如果未提供代理URL，则直接连接。
    """
    proxy_url = request.proxy_url
    proxy_to_use = proxy_url if proxy_url else None

    # --- 步骤 1: 测试与代理服务器本身的连通性 ---
    proxy_connectivity_result: ProxyTestResult
    if not proxy_url:
        proxy_connectivity_result = ProxyTestResult(status="skipped", error="未配置代理，跳过测试")
    else:
        # 使用一个已知的高可用、轻量级端点进行测试
        test_url_google = "http://www.google.com/generate_204"
        try:
            async with httpx.AsyncClient(proxy=proxy_to_use, timeout=10.0, follow_redirects=False) as client:
                start_time = time.time()
                response = await client.get(test_url_google)
                latency = (time.time() - start_time) * 1000
                # 204 No Content 是成功的标志
                if response.status_code == 204:
                    proxy_connectivity_result = ProxyTestResult(status="success", latency=latency)
                else:
                    proxy_connectivity_result = ProxyTestResult(
                        status="failure",
                        error=f"连接成功但状态码异常: {response.status_code}"
                    )
        except Exception as e:
            proxy_connectivity_result = ProxyTestResult(status="failure", error=str(e))

    # --- 步骤 2: 动态构建要测试的目标域名列表 ---
    target_sites_results: Dict[str, ProxyTestResult] = {}
    test_domains = set()
    
    # 统一获取所有源的设置
    enabled_metadata_settings = await crud.get_all_metadata_source_settings(session)
    scraper_settings = await crud.get_all_scraper_settings(session)

    # 合并所有源的设置，并添加一个获取实例的函数
    all_sources_settings = [
        (s, lambda name=s['providerName']: metadata_manager.get_source(name)) for s in enabled_metadata_settings
    ] + [
        (s, lambda name=s['providerName']: scraper_manager.get_scraper(name)) for s in scraper_settings
    ]

    log_message = "代理未启用，将测试所有已启用的源。" if not proxy_url else "代理已启用，将仅测试已配置代理的源。"
    logger.info(log_message)

    for setting, get_instance_func in all_sources_settings:
        provider_name = setting.get('providerName')

        # 优化：只测试已启用的源
        # 如果代理启用，则只测试勾选了 useProxy 的源；如果代理未启用，则测试所有启用的源。
        should_test = setting['isEnabled'] and (not proxy_url or setting.get('useProxy', False))

        if should_test:
            try:
                instance = get_instance_func()
                # 修正：支持异步获取 test_url
                if hasattr(instance, 'test_url'):
                    test_url_attr = getattr(instance, 'test_url')
                    # 检查 test_url 是否是一个异步属性
                    if asyncio.iscoroutine(test_url_attr):
                        test_domains.add(await test_url_attr)
                    else:
                        test_domains.add(test_url_attr)
            except ValueError:
                pass

    # --- 步骤 3: 并发执行所有测试 ---
    async def test_domain(domain: str, client: httpx.AsyncClient) -> tuple[str, ProxyTestResult]:
        try:
            start_time = time.time()
            # 使用 HEAD 请求以提高效率，我们只关心连通性
            await client.head(domain, timeout=10.0)
            latency = (time.time() - start_time) * 1000
            return domain, ProxyTestResult(status="success", latency=latency)
        except Exception as e:
            # 简化错误信息，避免在UI上显示过长的堆栈跟踪
            error_str = f"{type(e).__name__}"
            return domain, ProxyTestResult(status="failure", error=error_str)

    if test_domains:
        async with httpx.AsyncClient(proxy=proxy_to_use, timeout=10.0) as client:
            tasks = [test_domain(domain, client) for domain in test_domains]
            results = await asyncio.gather(*tasks)
            for domain, result in results:
                target_sites_results[domain] = result

    return FullProxyTestResponse(
        proxy_connectivity=proxy_connectivity_result,
        target_sites=target_sites_results
    )






@router.get("/config/customDanmakuPath", response_model=CustomDanmakuPathResponse, summary="获取自定义弹幕路径配置")
async def get_custom_danmaku_path(
    session: AsyncSession = Depends(get_db_session)
):
    """获取自定义弹幕路径配置"""
    enabled = await crud.get_config_value(session, "customDanmakuPathEnabled", "false")
    template = await crud.get_config_value(session, "customDanmakuPathTemplate", "/app/config/danmaku/${animeId}/${episodeId}")
    return CustomDanmakuPathResponse(enabled=enabled, template=template)



@router.put("/config/customDanmakuPath", response_model=CustomDanmakuPathResponse, summary="设置自定义弹幕路径配置")
async def set_custom_danmaku_path(
    request: CustomDanmakuPathRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """设置自定义弹幕路径配置"""
    logger.info(f"收到自定义弹幕路径配置请求: enabled={request.enabled}, template={request.template}")

    # 验证模板格式
    if request.enabled.lower() == 'true' and request.template:
        try:
            from src.path_template import DanmakuPathTemplate
            # 尝试创建模板对象来验证格式
            DanmakuPathTemplate(request.template)
            logger.info(f"模板验证成功: {request.template}")
        except Exception as e:
            logger.error(f"模板验证失败: {e}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"路径模板格式错误: {str(e)}")

    await crud.update_config_value(session, "customDanmakuPathEnabled", request.enabled)
    await crud.update_config_value(session, "customDanmakuPathTemplate", request.template)
    config_manager.invalidate("customDanmakuPathEnabled")
    config_manager.invalidate("customDanmakuPathTemplate")
    logger.info(f"自定义弹幕路径配置已保存")
    return CustomDanmakuPathResponse(enabled=request.enabled, template=request.template)

# --- 匹配后备Token配置 ---



@router.get("/config/matchFallbackTokens", response_model=MatchFallbackTokensResponse, summary="获取匹配后备允许的Token列表")
async def get_match_fallback_tokens(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取匹配后备允许的Token列表（JSON格式的token ID数组）"""
    value = await crud.get_config_value(session, "matchFallbackTokens", "[]")
    return MatchFallbackTokensResponse(value=value)



@router.put("/config/matchFallbackTokens", status_code=status.HTTP_204_NO_CONTENT, summary="设置匹配后备允许的Token列表")
async def set_match_fallback_tokens(
    request: MatchFallbackTokensResponse,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """设置匹配后备允许的Token列表（JSON格式的token ID数组）"""
    await crud.update_config_value(session, "matchFallbackTokens", request.value)
    config_manager.invalidate("matchFallbackTokens")
    logger.info(f"匹配后备Token配置已保存: {request.value}")
    return

# --- 后备搜索配置 ---



@router.get("/config/searchFallbackEnabled", response_model=ConfigValueResponse, summary="获取后备搜索状态")
async def get_search_fallback(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取后备搜索功能的启用状态"""
    value = await crud.get_config_value(session, "searchFallbackEnabled", "false")
    return ConfigValueResponse(value=value)



@router.put("/config/searchFallbackEnabled", status_code=status.HTTP_204_NO_CONTENT, summary="设置后备搜索状态")
async def set_search_fallback(
    request: ConfigValueRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """设置后备搜索功能的启用状态"""
    await crud.update_config_value(session, "searchFallbackEnabled", request.value)
    config_manager.invalidate("searchFallbackEnabled")
    logger.info(f"后备搜索状态已保存: {request.value}")
    return

# --- TMDB反查配置 ---
# 注意：这些专用路由必须在通用的 /config/{config_key} 路由之前定义，
# 否则会被通用路由拦截



@router.get("/config/tmdbReverseLookup", response_model=TmdbReverseLookupConfig, summary="获取TMDB反查配置")
async def get_tmdb_reverse_lookup_config(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取TMDB反查配置"""
    enabled = await crud.get_config_value(session, "tmdbReverseLookupEnabled", "false")
    sources_json = await crud.get_config_value(session, "tmdbReverseLookupSources", '["imdb", "tvdb"]')

    try:
        sources = json.loads(sources_json)
    except:
        sources = ["imdb", "tvdb"]  # 默认值

    return TmdbReverseLookupConfig(
        enabled=enabled.lower() == "true",
        sources=sources
    )



@router.post("/config/tmdbReverseLookup", summary="保存TMDB反查配置")
async def save_tmdb_reverse_lookup_config(
    request: TmdbReverseLookupConfigRequest,
    current_user: models.User = Depends(security.get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """保存TMDB反查配置"""
    # 修正：使用 config_manager.setValue 来确保在同一个事务中更新两个配置项
    # 这样可以避免多次 commit 导致的问题
    await config_manager.setValue("tmdbReverseLookupEnabled", str(request.enabled).lower())
    await config_manager.setValue("tmdbReverseLookupSources", json.dumps(request.sources))

    logger.info(f"用户 '{current_user.username}' 更新了TMDB反查配置: enabled={request.enabled}, sources={request.sources}")
    return {"message": "TMDB反查配置已保存"}



@router.get("/config/{config_key}", response_model=Dict[str, str], summary="获取指定配置项的值")
async def get_config_item(
    config_key: str,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取数据库中单个配置项的值。"""
    value = await crud.get_config_value(session, config_key, "") # 默认为空字符串
    return {"key": config_key, "value": value}



@router.put("/config/{config_key}", status_code=status.HTTP_204_NO_CONTENT, summary="更新指定配置项的值")
async def update_config_item(
    config_key: str,
    payload: Dict[str, Any],  # 修正：允许任意类型的值,避免前端传递undefined时报错
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """更新数据库中单个配置项的值。"""
    value = payload.get("value")
    if value is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing 'value' in request body")

    # 确保value是字符串类型
    value_str = str(value) if value is not None else ""

    await crud.update_config_value(session, config_key, value_str)
    config_manager.invalidate(config_key)
    logger.info(f"用户 '{current_user.username}' 更新了配置项 '{config_key}'。")



@router.post("/config/webhookApiKey/regenerate", response_model=Dict[str, str], summary="重新生成Webhook API Key")
async def regenerate_webhook_api_key(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """生成一个新的、随机的Webhook API Key并保存到数据库。"""
    alphabet = string.ascii_letters + string.digits
    new_key = ''.join(secrets.choice(alphabet) for _ in range(20))
    await crud.update_config_value(session, "webhookApiKey", new_key)
    config_manager.invalidate("webhookApiKey")
    logger.info(f"用户 '{current_user.username}' 重新生成了 Webhook API Key。")
    return {"key": "webhookApiKey", "value": new_key}



@router.post("/config/externalApiKey/regenerate", response_model=Dict[str, str], summary="重新生成外部API Key")
async def regenerate_external_api_key(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """生成一个新的、随机的外部API Key并保存到数据库。"""
    alphabet = string.ascii_letters + string.digits
    new_key = ''.join(secrets.choice(alphabet) for _ in range(32)) # 增加长度以提高安全性
    await crud.update_config_value(session, "externalApiKey", new_key)
    config_manager.invalidate("externalApiKey")
    logger.info(f"用户 '{current_user.username}' 重新生成了外部 API Key。")
    return {"key": "externalApiKey", "value": new_key}



@router.get("/config/provider/{providerName}", response_model=Dict[str, Any], summary="获取指定元数据源的配置")
async def get_provider_settings(
    providerName: str,
    current_user: models.User = Depends(security.get_current_user),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """获取指定元数据源的所有相关配置。"""
    try:
        return await metadata_manager.getProviderConfig(providerName)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))



@router.put("/config/provider/{providerName}", status_code=status.HTTP_204_NO_CONTENT, summary="更新指定元数据源的配置")
async def set_provider_settings(
    providerName: str,
    settings: Dict[str, Any],
    current_user: models.User = Depends(security.get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """批量更新指定元数据源的相关配置。"""
    config_keys_map = {
        "tmdb": ["tmdbApiKey", "tmdbApiBaseUrl", "tmdbImageBaseUrl"],
        "bangumi": ["bangumiClientId", "bangumiClientSecret", "bangumiToken"],
        "douban": "doubanCookie", # 单值配置
        "tvdb": "tvdbApiKey",   # 单值配置
    }

    if providerName in ["douban", "tvdb"]:
        key = config_keys_map.get(providerName)
        if key:
            # 修复：使用正确的字段名获取配置值
            if providerName == "tvdb":
                value = settings.get("tvdbApiKey", "")
            elif providerName == "douban":
                value = settings.get("doubanCookie", "")
            else:
                value = settings.get("value", "")
            await config_manager.setValue(configKey=key, configValue=value)
    else:
        keys_to_update = config_keys_map.get(providerName, [])
        tasks = [
            config_manager.setValue(configKey=key, configValue=settings[key])
            for key in keys_to_update if key in settings
        ]
        if tasks:
            await asyncio.gather(*tasks)
    logger.info(f"用户 '{current_user.username}' 更新了元数据源 '{providerName}' 的配置。")



@router.post("/config/ai/test", response_model=AITestResponse, summary="测试AI连接可用性")
async def test_ai_connection(
    request: AITestRequest,
    current_user: models.User = Depends(security.get_current_user)
):
    """测试AI连接配置是否可用"""
    try:
        start_time = time.time()

        # 根据provider确定base_url
        if request.baseUrl:
            base_url = request.baseUrl.rstrip('/')
        else:
            if request.provider == 'deepseek':
                base_url = 'https://api.deepseek.com'
            elif request.provider == 'openai':
                base_url = 'https://api.openai.com/v1'
            else:
                return AITestResponse(
                    success=False,
                    message="不支持的AI提供商",
                    error=f"未知的provider: {request.provider}"
                )

        # 构建API URL
        api_url = f"{base_url}/chat/completions"

        # 构建测试请求
        headers = {
            "Authorization": f"Bearer {request.apiKey}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": request.model,
            "messages": [
                {"role": "user", "content": "Hello"}
            ],
            "max_tokens": 10
        }

        # 发送测试请求
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(api_url, json=payload, headers=headers)

            latency = (time.time() - start_time) * 1000  # 转换为毫秒

            if response.status_code == 200:
                return AITestResponse(
                    success=True,
                    message="AI连接测试成功",
                    latency=round(latency, 2)
                )
            else:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get('error', {}).get('message', error_detail)
                except:
                    pass

                return AITestResponse(
                    success=False,
                    message=f"AI API返回错误 (HTTP {response.status_code})",
                    error=error_detail,
                    latency=round(latency, 2)
                )

    except httpx.TimeoutException:
        return AITestResponse(
            success=False,
            message="连接超时",
            error="请求超过30秒未响应,请检查网络连接或Base URL配置"
        )
    except httpx.ConnectError as e:
        return AITestResponse(
            success=False,
            message="无法连接到AI服务",
            error=f"连接失败: {str(e)}"
        )
    except Exception as e:
        logger.error(f"AI连接测试失败: {e}", exc_info=True)
        return AITestResponse(
            success=False,
            message="测试过程中发生错误",
            error=str(e)
        )


# --- Media Server API ---









































# --- 包含模块化的API端点 ---
from . import (
    config as config_endpoints,
    auth as auth_endpoints,
    scraper as scraper_endpoints,
    metadata_source as metadata_source_endpoints,
    media_server as media_server_endpoints
)

# 注册配置相关的路由
router.include_router(config_endpoints.router, prefix="/config", tags=["配置"])

# 注册认证相关的路由
auth_router.include_router(auth_endpoints.router, tags=["认证"])

# 注册搜索源相关的路由
router.include_router(scraper_endpoints.router, tags=["搜索源"])

# 注册元数据源相关的路由
router.include_router(metadata_source_endpoints.router, tags=["元数据源"])

# 注册媒体服务器相关的路由
router.include_router(media_server_endpoints.router, tags=["媒体服务器"])


