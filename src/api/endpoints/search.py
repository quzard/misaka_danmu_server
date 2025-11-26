"""
Search相关的API端点
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
from ...season_mapper import ai_type_and_season_mapping_and_correction
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
    get_rate_limiter, get_title_recognition_manager, get_ai_matcher_manager
)
from ...ai.ai_matcher_manager import AIMatcherManager
from ...season_mapper import title_contains_season_name, ai_season_mapping_and_correction

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
    "/search/anime",
    response_model=models.AnimeSearchResponse,
    summary="搜索本地数据库中的节目信息",
)
async def search_anime_local(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    session: AsyncSession = Depends(get_db_session)
):
    db_results = await crud.search_anime(session, keyword)
    animes = [
        models.AnimeInfo(animeId=item["id"], animeTitle=item["title"], type=item["type"])
        for item in db_results
    ]
    return models.AnimeSearchResponse(animes=animes)

@router.get("/search/provider", response_model=UIProviderSearchResponse, summary="从外部数据源搜索节目")
async def search_anime_provider(
    request: Request,
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    manager: ScraperManager = Depends(get_scraper_manager),
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    title_recognition_manager: TitleRecognitionManager = Depends(get_title_recognition_manager),
    config_manager: ConfigManager = Depends(get_config_manager),
    ai_matcher_manager: AIMatcherManager = Depends(get_ai_matcher_manager)
):
    """
    从所有已配置的数据源（如腾讯、B站等）搜索节目信息。
    此接口实现了智能的按季缓存机制，并保留了原有的别名搜索、过滤和排序逻辑。
    """
    try:
        parsed_keyword = parse_search_keyword(keyword)
        original_title = parsed_keyword["title"]
        season_to_filter = parsed_keyword["season"]
        episode_to_filter = parsed_keyword["episode"]

        # 应用搜索预处理规则
        search_title = original_title
        search_season = season_to_filter
        if title_recognition_manager:
            processed_title, processed_episode, processed_season, preprocessing_applied = await title_recognition_manager.apply_search_preprocessing(original_title, episode_to_filter, season_to_filter)
            if preprocessing_applied:
                search_title = processed_title
                logger.info(f"✓ WebUI搜索预处理: '{original_title}' -> '{search_title}'")
                # 如果集数发生了变化，更新episode_to_filter
                if processed_episode != episode_to_filter:
                    episode_to_filter = processed_episode
                    logger.info(f"✓ WebUI集数预处理: {parsed_keyword['episode']} -> {episode_to_filter}")
                # 如果季数发生了变化，更新season_to_filter
                if processed_season != season_to_filter:
                    search_season = processed_season
                    season_to_filter = processed_season
                    logger.info(f"✓ WebUI季度预处理: {parsed_keyword['season']} -> {season_to_filter}")
            else:
                logger.info(f"○ WebUI搜索预处理未生效: '{original_title}'")

        # --- 新增：按季缓存逻辑 ---
        # 缓存键基于核心标题和季度，允许在同一季的不同分集搜索中复用缓存
        cache_key = f"provider_search_{search_title}_{season_to_filter or 'all'}"
        supplemental_cache_key = f"supplemental_search_{search_title}"
        cached_results_data = await crud.get_cache(session, cache_key)
        cached_supplemental_results = await crud.get_cache(session, supplemental_cache_key)

        if cached_results_data is not None and cached_supplemental_results is not None:
            logger.info(f"搜索缓存命中: '{cache_key}'")
            # 缓存数据已排序和过滤，只需更新当前请求的集数信息
            results = [models.ProviderSearchInfo.model_validate(item) for item in cached_results_data]
            for item in results:
                item.currentEpisodeIndex = episode_to_filter
            
            return UIProviderSearchResponse(
                results=[item.model_dump() for item in results],
                supplemental_results=[models.ProviderSearchInfo.model_validate(item).model_dump() for item in cached_supplemental_results],
                search_season=season_to_filter,
                search_episode=episode_to_filter
            )
        
        logger.info(f"搜索缓存未命中: '{cache_key}'，正在执行完整搜索流程...")
        # --- 缓存逻辑结束 ---

        # 创建季度映射任务(如果启用) - 与搜索并行运行
        season_mapping_task = None
        season_name = None
        home_search_season_mapping_enabled = await config_manager.get("homeSearchEnableTmdbSeasonMapping", "false")

        # 季度映射：启用时，使用统一逻辑进行季度映射
        season_mapping_task = None
        if home_search_season_mapping_enabled.lower() == "true":
            # 确定要映射的季度
            season_to_map = season_to_filter if season_to_filter and season_to_filter > 1 else None

            if season_to_map:
                # 用户明确指定季度：获取该季度的准确名称
                logger.info(f"○ 主页搜索 季度映射: 开始为 '{search_title}' S{season_to_map:02d} 获取季度名称(并行)...")
            else:
                # 用户未指定季度：智能识别可能的季度
                logger.info(f"○ 主页搜索 季度映射: 开始为 '{search_title}' 进行智能季度识别(并行)...")
                season_to_map = 2  # 默认从第2季开始检查

            # 获取AI匹配器(如果启用)
            ai_matcher = await ai_matcher_manager.get_matcher()
            if ai_matcher:
                logger.debug("主页搜索 季度映射: 使用AI匹配器")
            else:
                logger.debug("主页搜索 季度映射: AI匹配器未启用或初始化失败")

            # 获取元数据源和自定义提示词
            metadata_source = await config_manager.get("seasonMappingMetadataSource", "tmdb")
            custom_prompt = await config_manager.get("seasonMappingPrompt", "")
            sources = [metadata_source] if metadata_source else None

            # 创建并行任务：使用统一的季度映射逻辑
            async def get_season_mapping():
                try:
                    return await metadata_manager.get_season_name(
                        title=search_title,
                        season_number=season_to_map,
                        year=None,
                        sources=sources,
                        ai_matcher=ai_matcher,
                        user=current_user,
                        custom_prompt=custom_prompt if custom_prompt else None
                    )
                except Exception as e:
                    logger.warning(f"主页搜索 季度映射失败: {e}")
                    return None

            season_mapping_task = asyncio.create_task(get_season_mapping())

        episode_info = {
            "season": season_to_filter,
            "episode": episode_to_filter
        } if episode_to_filter is not None else None

        logger.info(f"用户 '{current_user.username}' 正在搜索: '{keyword}' (解析为: title='{search_title}', season={season_to_filter}, episode={episode_to_filter})")

        # 第一次检查:在所有搜索之前检查是否有弹幕源
        if not manager.has_enabled_scrapers:
            logger.warning("❌ 没有启用的弹幕搜索源，终止本次搜索")
            logger.info("请在'搜索源-弹幕搜索源'页面中至少启用一个弹幕源，如果没有弹幕源请从资源仓库中加载")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="没有启用的弹幕搜索源，请在“搜索源”页面中启用至少一个。"
            )

        # --- 原有的复杂搜索流程开始 ---
        # 1. 获取别名和补充结果
        # 修正：检查是否有任何启用的辅助源或强制辅助源
        has_any_aux_source = await metadata_manager.has_any_enabled_aux_source()

        if not has_any_aux_source:
            logger.info("未配置或未启用任何有效的辅助搜索源，直接进行全网搜索。")
            supplemental_results = []
            # 修正:变量名统一
            all_results = await manager.search_all([search_title], episode_info=episode_info)
            logger.info(f"直接搜索完成，找到 {len(all_results)} 个原始结果。")
            filter_aliases = {search_title} # 确保至少有原始标题用于后续处理
        else:
            # 检查是否有启用的弹幕源 - 在辅助搜索之前先检查
            if not manager.has_enabled_scrapers:
                logger.warning("❌ 辅助搜索已启用，但没有启用的弹幕搜索源，终止本次搜索")
                logger.info("请在'搜索源-弹幕搜索源'页面中至少启用一个弹幕源，如果没有弹幕源请从资源仓库中加载")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='没有启用的弹幕搜索源，请在"搜索源-弹幕搜索源"页面下中至少启用一个，如果没有弹幕源就从资源仓库中加载弹幕源。'
                )

            logger.info("一个或多个元数据源已启用辅助搜索，开始执行...")
            # 修正：增加一个“防火墙”来验证从元数据源返回的别名，防止因模糊匹配导致的结果污染。
            # 优化：并行执行辅助搜索和主搜索
            logger.info(f"将使用解析后的标题 '{search_title}' 进行全网搜索...")

            # 1. 并行启动两个任务
            main_task = asyncio.create_task(
                manager.search_all([search_title], episode_info=episode_info)
            )

            supp_task = asyncio.create_task(
                metadata_manager.search_supplemental_sources(search_title, current_user)
            )

            # 2. 等待两个任务都完成
            all_results, (all_possible_aliases, supplemental_results) = await asyncio.gather(
                main_task, supp_task
            )

            # 3. 验证每个别名与原始搜索词的相似度
            validated_aliases = set()
            for alias in all_possible_aliases:
                # 使用 token_set_ratio 并设置一个合理的阈值（例如70），以允许小的差异但过滤掉完全不相关的结果。
                if fuzz.token_set_ratio(search_title, alias) > 70:
                    validated_aliases.add(alias)
                else:
                    logger.debug(f"别名验证：已丢弃低相似度的别名 '{alias}' (与 '{search_title}' 相比)")
            
            # 4. 使用经过验证的别名列表进行后续操作
            filter_aliases = validated_aliases
            filter_aliases.add(search_title) # 确保原始搜索词总是在列表中
            logger.info(f"所有辅助搜索完成，最终别名集大小: {len(filter_aliases)}")

            # 新增：根据您的要求，打印最终的别名列表以供调试
            logger.info(f"用于过滤的别名列表: {list(filter_aliases)}")

            def normalize_for_filtering(title: str) -> str:
                if not title: return ""
                title = re.sub(r'[\[【(（].*?[\]】)）]', '', title)
                return title.lower().replace(" ", "").replace("：", ":").strip()

            # 修正：采用更智能的两阶段过滤策略
            # 阶段1：基于原始搜索词进行初步、宽松的过滤，以确保所有相关系列（包括不同季度和剧场版）都被保留。
            # 只有当用户明确指定季度时，我们才进行更严格的过滤。
            normalized_filter_aliases = {normalize_for_filtering(alias) for alias in filter_aliases if alias}
            filtered_results = []
            for item in all_results:
                normalized_item_title = normalize_for_filtering(item.title)
                if not normalized_item_title: continue
                
                # 检查搜索结果是否与任何一个别名匹配
                # token_set_ratio 擅长处理单词顺序不同和部分单词匹配的情况。
                # 修正：使用 partial_ratio 来更好地匹配续作和外传 (e.g., "刀剑神域" vs "刀剑神域外传")
                # 85 的阈值可以在保留强相关的同时，过滤掉大部分无关结果。
                if any(fuzz.partial_ratio(normalized_item_title, alias) > 85 for alias in normalized_filter_aliases):
                    filtered_results.append(item)

            logger.info(f"别名过滤: 从 {len(all_results)} 个原始结果中，保留了 {len(filtered_results)} 个相关结果。")
            results = filtered_results

    except httpx.RequestError as e:
        error_message = f"搜索 '{keyword}' 时发生网络错误: {e}"
        logger.error(error_message, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=error_message)

    # 辅助函数，用于根据标题修正媒体类型
    def is_movie_by_title(title: str) -> bool:
        if not title:
            return False
        # 关键词列表，不区分大小写
        movie_keywords = ["剧场版", "劇場版", "movie", "映画"]
        title_lower = title.lower()
        return any(keyword in title_lower for keyword in movie_keywords)

    # 新增逻辑：根据标题关键词修正媒体类型
    for item in results:
        if item.type == 'tv_series' and is_movie_by_title(item.title):
            logger.info(f"标题 '{item.title}' 包含电影关键词，类型从 'tv_series' 修正为 'movie'。")
            item.type = 'movie'

    # 如果用户在搜索词中明确指定了季度，则对结果进行过滤
    if season_to_filter:
        original_count = len(results)
        # 当指定季度时，我们只关心电视剧类型
        filtered_by_type = [item for item in results if item.type == 'tv_series']
        
        # 然后在电视剧类型中，我们按季度号过滤
        filtered_by_season = []
        for item in filtered_by_type:
            # 使用模型中已解析好的 season 字段进行比较
            if item.season == season_to_filter:
                filtered_by_season.append(item)
        
        logger.info(f"根据指定的季度 ({season_to_filter}) 进行过滤，从 {original_count} 个结果中保留了 {len(filtered_by_season)} 个。")
        results = filtered_by_season

    # 修正：在返回结果前，确保 currentEpisodeIndex 与本次请求的 episode_info 一致。
    # 这可以防止因缓存或其他原因导致的状态泄露。
    current_episode_index_for_this_request = episode_info.get("episode") if episode_info else None
    for item in results:
        item.currentEpisodeIndex = current_episode_index_for_this_request

    # 新增：根据搜索源的显示顺序和标题相似度对结果进行排序
    source_settings = await crud.get_all_scraper_settings(session)
    source_order_map = {s['providerName']: s['displayOrder'] for s in source_settings}

    def sort_key(item: models.ProviderSearchInfo):
        provider_order = source_order_map.get(item.provider, 999)
        # 使用 token_set_ratio 来获得更鲁棒的标题相似度评分
        similarity_score = fuzz.token_set_ratio(search_title, item.title)
        # 主排序键：源顺序（升序）；次排序键：相似度（降序）
        return (provider_order, -similarity_score)

    sorted_results = sorted(results, key=sort_key)

    # --- 新增：在返回前缓存最终结果 ---
    # 我们缓存的是整季的结果，所以在存入前清除特定集数的信息
    results_to_cache = []
    for item in sorted_results:
        item_copy = item.model_copy(deep=True)
        item_copy.currentEpisodeIndex = None
        results_to_cache.append(item_copy.model_dump())

    if sorted_results:
        await crud.set_cache(session, cache_key, results_to_cache, ttl_seconds=10800)
    # 缓存补充结果
    if supplemental_results:
        await crud.set_cache(session, supplemental_cache_key, [item.model_dump() for item in supplemental_results], ttl_seconds=10800)
    # --- 缓存逻辑结束 ---



    # 使用统一的AI类型和季度映射修正函数
    if ai_matcher and metadata_manager:
        try:
            # 使用新的统一函数进行类型和季度修正
            mapping_result = await ai_type_and_season_mapping_and_correction(
                search_title=search_title,
                search_results=sorted_results,
                metadata_manager=metadata_manager,
                ai_matcher=ai_matcher,
                logger=logger,
                similarity_threshold=60.0
            )

            # 应用修正结果
            if mapping_result['total_corrections'] > 0:
                logger.info(f"✓ 主页搜索 统一AI映射成功: 总计修正了 {mapping_result['total_corrections']} 个结果")
                logger.info(f"  - 类型修正: {len(mapping_result['type_corrections'])} 个")
                logger.info(f"  - 季度修正: {len(mapping_result['season_corrections'])} 个")

                # 更新搜索结果（已经直接修改了sorted_results）
                sorted_results = mapping_result['corrected_results']
            else:
                logger.info(f"○ 主页搜索 统一AI映射: 未找到需要修正的信息")

        except Exception as e:
            logger.warning(f"主页搜索 统一AI映射任务执行失败: {e}")
    elif season_mapping_task:
        # 兼容旧逻辑（如果存在）
        try:
            corrected_results = await season_mapping_task
            if corrected_results:
                logger.info(f"✓ 主页搜索 季度映射成功: 修正了 {len(corrected_results)} 个结果的季度信息")
                for correction in corrected_results:
                    item = correction['item']
                    item.season = correction['corrected_season']
                    logger.info(f"  ✓ 季度修正: '{item.title}' → S{item.season}")
            else:
                logger.info(f"○ 主页搜索 季度映射: 未找到需要修正的季度信息")
        except Exception as e:
            logger.warning(f"主页搜索 季度映射任务执行失败: {e}")

    return UIProviderSearchResponse(
        results=[item.model_dump() for item in sorted_results],
        supplemental_results=[item.model_dump() for item in supplemental_results] if supplemental_results else [],
        search_season=season_to_filter,
        search_episode=episode_to_filter
    )



@router.get("/search/episodes", response_model=List[models.ProviderEpisodeInfo], summary="获取搜索结果的分集列表")
async def get_episodes_for_search_result(
    provider: str = Query(...),
    media_id: str = Query(...),
    media_type: Optional[str] = Query(None), # Pass media_type to help scraper
    supplement_provider: Optional[str] = Query(None, description="补充源provider"),
    supplement_media_id: Optional[str] = Query(None, description="补充源mediaId"),
    manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    current_user: models.User = Depends(security.get_current_user)
):
    """为指定的搜索结果获取完整的分集列表。支持从补充源获取分集URL。"""
    try:
        episodes = []

        # 如果提供了补充源参数,从补充源获取分集URL
        if supplement_provider and supplement_media_id:
            logger.info(f"使用补充源 {supplement_provider} 获取分集列表")

            try:
                # 获取补充源实例
                supplement_source = metadata_manager.sources.get(supplement_provider)
                if not supplement_source:
                    logger.warning(f"补充源 {supplement_provider} 不可用")
                elif not getattr(supplement_source, 'supports_episode_urls', False):
                    logger.warning(f"补充源 {supplement_provider} 不支持分集URL获取")
                else:
                    # 使用补充源获取分集URL列表
                    episode_urls = await supplement_source.get_episode_urls(
                        supplement_media_id, provider  # 目标平台
                    )
                    logger.info(f"补充源获取到 {len(episode_urls)} 个分集URL")

                    if episode_urls:
                        # 获取主源scraper用于解析URL
                        scraper = manager.get_scraper(provider)

                        # 解析URL获取分集信息
                        for i, url in episode_urls:
                            try:
                                # 从URL提取episode_id
                                episode_id = await scraper.get_id_from_url(url)
                                if episode_id:
                                    episodes.append(models.ProviderEpisodeInfo(
                                        provider=provider,
                                        episodeId=episode_id,
                                        title=f"第{i}集",
                                        episodeIndex=i,
                                        url=url
                                    ))
                            except Exception as e:
                                logger.warning(f"解析URL失败 (第{i}集): {e}")

                        logger.info(f"补充源成功解析 {len(episodes)} 个分集")
            except Exception as e:
                logger.error(f"使用补充源获取分集失败: {e}", exc_info=True)
        else:
            # 从主源获取分集列表
            scraper = manager.get_scraper(provider)
            # 将 db_media_type 传递给 get_episodes 以帮助需要它的刮削器（如 mgtv）
            episodes = await scraper.get_episodes(media_id, db_media_type=media_type)

        return episodes
    except httpx.RequestError as e:
        # 新增：捕获网络错误
        error_message = f"从 {provider} 获取分集列表时发生网络错误: {e}"
        logger.error(f"获取分集列表失败 (provider={provider}, media_id={media_id}): {error_message}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=error_message)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"获取分集列表失败 (provider={provider}, media_id={media_id}): {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取分集列表失败。")




