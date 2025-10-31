"""
Settings相关的API端点
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
    get_scraper_manager, get_task_manager, get_scheduler_manager,
    get_webhook_manager, get_metadata_manager, get_config_manager,
    get_rate_limiter, get_title_recognition_manager
)
router = APIRouter()

@router.get("/settings/title-recognition", response_model=TitleRecognitionContent, summary="获取识别词配置内容")
async def get_title_recognition_content(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """
    获取识别词配置内容
    
    Returns:
        TitleRecognitionContent: 包含识别词配置内容的响应
    """
    try:
        # 查询识别词配置（只有一条记录）
        result = await session.execute(
            select(orm_models.TitleRecognition).limit(1)
        )
        title_recognition = result.scalar_one_or_none()
        
        if title_recognition is None:
            # 如果没有配置记录，返回默认内容
            default_content = """# 自定义识别词配置 - 参考MoviePilot格式
# 支持以下几种配置格式（注意连接符号左右的空格）：

# 1. 屏蔽词：将该词从待识别文本中去除
# 屏蔽词示例
# 预告
# 花絮

# 2. 简单替换：被替换词 => 替换词
# 奔跑吧 => 奔跑吧兄弟
# 极限挑战 => 极限挑战第一季

# 3. 集数偏移：前定位词 <> 后定位词 >> 集偏移量（EP）
# 第 <> 话 >> EP-1
# Episode <> : >> EP+5

# 4. 复合格式：被替换词 => 替换词 && 前定位词 <> 后定位词 >> 集偏移量（EP）
# 某动画 => 某动画正确名称 && 第 <> 话 >> EP-1

# 5. 元数据替换：直接指定TMDB/豆瓣ID
# 错误标题 => {[tmdbid=12345;type=tv;s=1;e=1]}

# 6. 季度偏移：针对特定源的季度偏移
# TX源某动画第9季 => {[source=tencent;season_offset=9>13]}
# 某动画第5季 => {[source=bilibili;season_offset=5+3]}
# 错误标题 => {[source=iqiyi;title=正确标题;season_offset=*+1]}

# 集偏移支持运算：
# EP+1：集数加1
# 2*EP：集数翻倍
# 2*EP-1：集数翻倍减1

# 季度偏移支持格式：
# 9>13：第9季改为第13季
# 9+4：第9季加4变成第13季
# 9-1：第9季减1变成第8季
# *+4：所有季度都加4
# *>1：所有季度都改为第1季
"""
            return TitleRecognitionContent(content=default_content)
        
        return TitleRecognitionContent(content=title_recognition.content)
        
    except Exception as e:
        logger.error(f"获取识别词配置时发生错误: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取识别词配置时发生内部错误。")




@router.put("/settings/title-recognition", response_model=TitleRecognitionUpdateResponse, summary="更新识别词配置内容")
async def update_title_recognition_content(
    payload: TitleRecognitionContent,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    title_recognition_manager = Depends(get_title_recognition_manager)
):
    """
    更新识别词配置内容，使用全量替换模式

    Args:
        payload: 包含新识别词配置内容的请求体

    Returns:
        TitleRecognitionUpdateResponse: 包含更新结果和警告信息
    """
    try:
        if title_recognition_manager is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="识别词管理器未初始化")

        # 使用全量替换模式更新识别词规则，获取警告信息
        warnings = await title_recognition_manager.update_recognition_rules(payload.content)

        logger.info("识别词配置更新成功")

        return TitleRecognitionUpdateResponse(success=True, warnings=warnings)

    except Exception as e:
        logger.error(f"更新识别词配置时发生错误: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"更新识别词配置时发生内部错误: {str(e)}")



@router.get("/settings/global-filter", response_model=GlobalFilterSettings, summary="获取全局标题过滤规则")
async def get_global_filter_settings(
    config: ConfigManager = Depends(get_config_manager),
    current_user: models.User = Depends(security.get_current_user)
):
    """获取用于过滤搜索结果的全局中文和英文黑名单正则表达式。"""
    cn_filter = await config.get("search_result_global_blacklist_cn", "")
    eng_filter = await config.get("search_result_global_blacklist_eng", "")
    return GlobalFilterSettings(cn=cn_filter, eng=eng_filter)



@router.put("/settings/global-filter", summary="更新全局标题过滤规则")
async def update_global_filter_settings(
    payload: GlobalFilterSettings,
    config: ConfigManager = Depends(get_config_manager),
    current_user: models.User = Depends(security.get_current_user)
):
    """更新全局的中文和英文标题过滤黑名单。"""
    await config.setValue("search_result_global_blacklist_cn", payload.cn)
    await config.setValue("search_result_global_blacklist_eng", payload.eng)
    return {"message": "全局过滤规则已更新。"}



@router.get("/settings/webhook", response_model=WebhookSettings, summary="获取Webhook设置")
async def get_webhook_settings(
    config: ConfigManager = Depends(get_config_manager),
    current_user: models.User = Depends(security.get_current_user)
):
    # 使用 asyncio.gather 并发获取所有配置项
    (
        enabled_str, delayed_enabled_str, delay_hours_str, custom_domain_str,
        filter_mode, filter_regex, log_raw_request_str, fallback_enabled_str
    ) = await asyncio.gather(
        config.get("webhookEnabled", "true"),
        config.get("webhookDelayedImportEnabled", "false"),
        config.get("webhookDelayedImportHours", "24"),
        config.get("webhookCustomDomain", ""),
        config.get("webhookFilterMode", "blacklist"),
        config.get("webhookFilterRegex", ""),
        config.get("webhookLogRawRequest", "false"),
        config.get("webhookFallbackEnabled", "false")
    )
    return WebhookSettings(
        webhookEnabled=enabled_str.lower() == 'true',
        webhookDelayedImportEnabled=delayed_enabled_str.lower() == 'true',
        webhookDelayedImportHours=int(delay_hours_str) if delay_hours_str.isdigit() else 24,
        webhookCustomDomain=custom_domain_str,
        webhookFilterMode=filter_mode,
        webhookFilterRegex=filter_regex,
        webhookLogRawRequest=log_raw_request_str.lower() == 'true',
        webhookFallbackEnabled=fallback_enabled_str.lower() == 'true'
    )



@router.put("/settings/webhook", status_code=status.HTTP_204_NO_CONTENT, summary="更新Webhook设置")
async def update_webhook_settings(
    payload: WebhookSettings,
    config: ConfigManager = Depends(get_config_manager),
    current_user: models.User = Depends(security.get_current_user)
):
    # 使用 asyncio.gather 并发保存所有配置项
    await asyncio.gather(
        config.setValue("webhookEnabled", str(payload.webhookEnabled).lower()),
        config.setValue("webhookDelayedImportEnabled", str(payload.webhookDelayedImportEnabled).lower()),
        config.setValue("webhookDelayedImportHours", str(payload.webhookDelayedImportHours)),
        config.setValue("webhookCustomDomain", payload.webhookCustomDomain),
        config.setValue("webhookFilterMode", payload.webhookFilterMode),
        config.setValue("webhookFilterRegex", payload.webhookFilterRegex),
        config.setValue("webhookLogRawRequest", str(payload.webhookLogRawRequest).lower()),
        config.setValue("webhookFallbackEnabled", str(payload.webhookFallbackEnabled).lower())
    )
    return



