"""Webhook任务模块"""
import asyncio
import json
import logging
from typing import Callable, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from thefuzz import fuzz

from .. import crud, models, orm_models
from ..orm_models import AnimeSource as AS
from ..config_manager import ConfigManager
from ..scraper_manager import ScraperManager
from ..metadata_manager import MetadataSourceManager
from ..task_manager import TaskManager, TaskSuccess
from ..rate_limiter import RateLimiter
from ..title_recognition import TitleRecognitionManager
from ..search_utils import unified_search
from ..timezone import get_now
from ..utils import parse_search_keyword

logger = logging.getLogger(__name__)


# 延迟导入辅助函数
def _get_generic_import_task():
    from .import_core import generic_import_task
    return generic_import_task


async def run_webhook_tasks_directly_manual(
    session: AsyncSession,
    task_ids: List[int],
    task_manager: "TaskManager",
    scraper_manager: "ScraperManager",
    metadata_manager: "MetadataSourceManager",
    config_manager: "ConfigManager",
    rate_limiter: "RateLimiter",
    title_recognition_manager: "TitleRecognitionManager"
) -> int:
    """直接获取并执行指定的待处理Webhook任务。"""
    if not task_ids:
        return 0

    stmt = select(orm_models.WebhookTask).where(orm_models.WebhookTask.id.in_(task_ids), orm_models.WebhookTask.status == "pending")
    tasks_to_run = (await session.execute(stmt)).scalars().all()

    submitted_count = 0
    for task in tasks_to_run:
        try:
            payload = json.loads(task.payload)
            task_coro = lambda s, cb: webhook_search_and_dispatch_task(
                webhookSource=task.webhookSource, progress_callback=cb, session=s,
                manager=scraper_manager, task_manager=task_manager,
                metadata_manager=metadata_manager, config_manager=config_manager,
                rate_limiter=rate_limiter, title_recognition_manager=title_recognition_manager,
                **payload
            )
            await task_manager.submit_task(task_coro, task.taskTitle, unique_key=task.uniqueKey)
            await session.delete(task)
            await session.commit()  # 为每个成功提交的任务单独提交删除操作
            submitted_count += 1
        except Exception as e:
            logger.error(f"手动执行 Webhook 任务 (ID: {task.id}) 时失败: {e}", exc_info=True)
            await session.rollback()
    return submitted_count


async def webhook_search_and_dispatch_task(
    animeTitle: str,
    mediaType: str,
    season: int,
    currentEpisodeIndex: int,
    searchKeyword: str,
    doubanId: Optional[str],
    tmdbId: Optional[str],
    imdbId: Optional[str],
    tvdbId: Optional[str],
    bangumiId: Optional[str],
    webhookSource: str,
    year: Optional[int],
    progress_callback: Callable,
    session: AsyncSession,
    manager: ScraperManager,
    task_manager: TaskManager, # type: ignore
    metadata_manager: MetadataSourceManager,
    config_manager: ConfigManager,
    rate_limiter: RateLimiter,
    title_recognition_manager: TitleRecognitionManager,
    # 媒体库整季导入时, 可选: 指定已在媒体库中选中的分集索引列表
    selectedEpisodes: Optional[List[int]] = None,
):
    """
    Webhook 触发的后台任务：搜索所有源，找到最佳匹配，并为该匹配分发一个新的、具体的导入任务。
    """
    generic_import_task = _get_generic_import_task()
    
    try:
        logger.info(f"Webhook 任务: 开始为 '{animeTitle}' (S{season:02d}E{currentEpisodeIndex:02d}) 查找最佳源...")
        await progress_callback(5, "正在检查已收藏的源...")

        # 1. 优先查找已收藏的源 (Favorited Source)
        logger.info(f"Webhook 任务: 查找已存在的anime - 标题='{animeTitle}', 季数={season}, 年份={year}")
        existing_anime = await crud.find_anime_by_title_season_year(session, animeTitle, season, year, title_recognition_manager, source=None)
        if existing_anime:
            anime_id = existing_anime['id']
            favorited_source = await crud.find_favorited_source_for_anime(session, anime_id)
            if favorited_source:
                logger.info(f"Webhook 任务: 找到已收藏的源 '{favorited_source['providerName']}'，将直接使用此源。")
                await progress_callback(10, f"找到已收藏的源: {favorited_source['providerName']}")

                # 根据来源动态生成任务标题前缀
                if webhookSource == "media_server":
                    source_prefix = "媒体库读取导入"
                elif webhookSource in ["emby", "jellyfin", "plex"]:
                    source_prefix = f"Webhook自动导入 ({webhookSource.capitalize()})"
                else:
                    source_prefix = f"Webhook自动导入 ({webhookSource})"

                task_title = f"{source_prefix}: {favorited_source['animeTitle']} - S{season:02d}E{currentEpisodeIndex:02d} ({favorited_source['providerName']})"
                unique_key = f"import-{favorited_source['providerName']}-{favorited_source['mediaId']}-S{season}-ep{currentEpisodeIndex}"
                task_coro = lambda session, cb: generic_import_task(
                    provider=favorited_source['providerName'], mediaId=favorited_source['mediaId'], animeTitle=favorited_source['animeTitle'], year=year,
                    mediaType=favorited_source['mediaType'], season=season, currentEpisodeIndex=currentEpisodeIndex,
                    imageUrl=favorited_source['imageUrl'], doubanId=doubanId, tmdbId=tmdbId, imdbId=imdbId, tvdbId=tvdbId, config_manager=config_manager, metadata_manager=metadata_manager,
                    bangumiId=bangumiId, rate_limiter=rate_limiter,
                    progress_callback=cb, session=session, manager=manager,
                    task_manager=task_manager,
                    title_recognition_manager=title_recognition_manager,
                    selectedEpisodes=selectedEpisodes,
                )
                await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)

                # 根据来源动态生成成功消息
                if webhookSource == "media_server":
                    success_message = f"已为收藏源 '{favorited_source['providerName']}' 创建导入任务。"
                else:
                    success_message = f"Webhook: 已为收藏源 '{favorited_source['providerName']}' 创建导入任务。"
                raise TaskSuccess(success_message)

        # 2. 如果没有收藏源，则并发搜索所有启用的源
        logger.info(f"Webhook 任务: 未找到收藏源，开始并发搜索所有启用的源...")
        await progress_callback(20, "并发搜索所有源...")

        parsed_keyword = parse_search_keyword(searchKeyword)
        original_title = parsed_keyword["title"]
        season_to_filter = parsed_keyword.get("season") or season
        episode_to_filter = parsed_keyword.get("episode") or currentEpisodeIndex

        # 2.1 创建季度映射任务(如果启用) - 与搜索并行运行
        season_mapping_task = None
        webhook_tmdb_enabled = await config_manager.get("webhookEnableTmdbSeasonMapping", "true")
        if webhook_tmdb_enabled.lower() == "true" and season_to_filter and season_to_filter > 1:
            logger.info(f"○ Webhook 季度映射: 开始为 '{original_title}' S{season_to_filter:02d} 获取季度名称(并行)...")

            # 检查是否启用AI匹配
            ai_match_enabled = await config_manager.get("aiMatchEnabled", "false")
            ai_matcher = None
            if ai_match_enabled.lower() == "true":
                try:
                    from ..ai_matcher import AIMatcher
                    ai_config = {
                        "ai_match_provider": await config_manager.get("aiProvider", "deepseek"),
                        "ai_match_api_key": await config_manager.get("aiApiKey", ""),
                        "ai_match_base_url": await config_manager.get("aiBaseUrl", ""),
                        "ai_match_model": await config_manager.get("aiModel", "deepseek-chat"),
                        "ai_match_prompt": await config_manager.get("aiPrompt", ""),
                        "ai_log_raw_response": (await config_manager.get("aiLogRawResponse", "false")).lower() == "true"
                    }
                    ai_matcher = AIMatcher(ai_config)
                except Exception as e:
                    logger.warning(f"Webhook 季度映射: AI匹配器初始化失败: {e}")

            # 获取元数据源和自定义提示词
            metadata_source = await config_manager.get("seasonMappingMetadataSource", "tmdb")
            custom_prompt = await config_manager.get("seasonMappingPrompt", "")
            sources = [metadata_source] if metadata_source else None

            # 创建并行任务
            async def get_season_mapping():
                try:
                    return await metadata_manager.get_season_name(
                        title=original_title,
                        season_number=season_to_filter,
                        year=year,
                        sources=sources,
                        ai_matcher=ai_matcher,
                        user=None,
                        custom_prompt=custom_prompt if custom_prompt else None
                    )
                except Exception as e:
                    logger.warning(f"Webhook 季度映射失败: {e}")
                    return None

            season_mapping_task = asyncio.create_task(get_season_mapping())
        else:
            if webhook_tmdb_enabled.lower() != "true":
                logger.info("○ Webhook 季度映射: 功能未启用")
            elif not season_to_filter or season_to_filter <= 1:
                logger.info(f"○ Webhook 季度映射: 季度号为{season_to_filter},跳过(仅处理S02及以上)")

        # 应用与 WebUI 一致的标题预处理规则
        search_title = original_title
        if title_recognition_manager:
            (
                processed_title,
                processed_episode,
                processed_season,
                preprocessing_applied,
            ) = await title_recognition_manager.apply_search_preprocessing(
                original_title, episode_to_filter, season_to_filter
            )
            if preprocessing_applied:
                search_title = processed_title
                logger.info(
                    f"✓ Webhook搜索预处理: '{original_title}' -> '{search_title}'"
                )
                if processed_episode != episode_to_filter:
                    logger.info(
                        f"✓ Webhook集数预处理: {episode_to_filter} -> {processed_episode}"
                    )
                    episode_to_filter = processed_episode
                if processed_season != season_to_filter:
                    logger.info(
                        f"✓ Webhook季度预处理: {season_to_filter} -> {processed_season}"
                    )
                    season_to_filter = processed_season
            else:
                logger.info(f"○ Webhook搜索预处理未生效: '{original_title}'")
        else:
            logger.info("○ 未配置标题识别管理器，跳过Webhook搜索预处理。")

        # 构造 episode_info
        episode_info = (
            {"season": season_to_filter, "episode": episode_to_filter}
            if episode_to_filter is not None
            else {"season": season_to_filter}
        )

        logger.info(f"Webhook 任务: 已将搜索词 '{searchKeyword}' 解析为标题 '{search_title}' 进行搜索。")

        # 使用统一的搜索函数（与 WebUI 搜索保持一致）
        all_search_results = await unified_search(
            search_term=search_title,
            session=session,
            scraper_manager=manager,
            metadata_manager=metadata_manager,
            use_alias_expansion=True,
            use_alias_filtering=True,
            use_title_filtering=True,
            use_source_priority_sorting=True,
            progress_callback=None,
            episode_info=episode_info,
            alias_similarity_threshold=70,
        )

        if not all_search_results:
            raise ValueError(f"未找到 '{animeTitle}' 的任何可用源。")

        # 等待季度映射任务完成(如果有)
        season_name_from_mapping = None
        if season_mapping_task:
            try:
                season_name_from_mapping = await season_mapping_task
                if season_name_from_mapping:
                    logger.info(f"✓ Webhook 季度映射成功: '{original_title}' S{season_to_filter:02d} → '{season_name_from_mapping}'")
                else:
                    logger.info(f"○ Webhook 季度映射: 未找到季度名称")
            except Exception as e:
                logger.warning(f"Webhook 季度映射任务失败: {e}")

        # 根据季度映射结果调整搜索结果的 season 字段
        if season_name_from_mapping and season_to_filter and season_to_filter > 1:
            from ..season_mapper import title_contains_season_name

            adjusted_count = 0
            for item in all_search_results:
                # 只处理电视剧类型且 season 为 None 或 1 的结果
                if item.type == "tv_series" and (item.season is None or item.season == 1):
                    if title_contains_season_name(item.title, season_name_from_mapping, threshold=60.0):
                        logger.info(f"  ✓ 季度调整: '{item.title}' (Provider: {item.provider}) season: {item.season} → {season_to_filter}")
                        item.season = season_to_filter
                        adjusted_count += 1

            if adjusted_count > 0:
                logger.info(f"✓ 根据季度映射调整了 {adjusted_count} 个结果的 season 字段")

        # 3. 根据标题关键词修正媒体类型（与 WebUI 一致）
        def is_movie_by_title(title: str) -> bool:
            if not title:
                return False
            # 关键词列表，不区分大小写
            movie_keywords = ["剧场版", "劇場版", "movie", "映画"]
            title_lower = title.lower()
            return any(keyword in title_lower for keyword in movie_keywords)

        for item in all_search_results:
            if item.type == "tv_series" and is_movie_by_title(item.title):
                logger.info(
                    f"Webhook: 标题 '{item.title}' 包含电影关键词，类型从 'tv_series' 修正为 'movie'。"
                )
                item.type = "movie"

        # 4. 如果搜索词中明确指定了季度，对结果进行过滤（与 WebUI 一致）
        # 注意：电影类型不进行季度过滤
        if season_to_filter and season_to_filter > 0 and mediaType != "movie":
            original_count = len(all_search_results)
            # 当指定季度时，我们只关心电视剧类型
            filtered_by_type = [item for item in all_search_results if item.type == "tv_series"]

            # 然后在电视剧类型中，我们按季度号过滤
            filtered_by_season = [
                item for item in filtered_by_type if item.season == season_to_filter
            ]

            logger.info(
                f"Webhook: 根据指定的季度 ({season_to_filter}) 进行过滤，从 {original_count} 个结果中保留了 {len(filtered_by_season)} 个。"
            )
            all_search_results = filtered_by_season

        # 5. 使用与WebUI相同的智能匹配算法选择最佳匹配项
        ordered_settings = await crud.get_all_scraper_settings(session)
        provider_order = {s['providerName']: s['displayOrder'] for s in ordered_settings}

        # 添加调试日志
        logger.info(f"Webhook 任务: 排序前的媒体类型: media_type='{mediaType}', 共 {len(all_search_results)} 个结果")
        for i, item in enumerate(all_search_results[:5]):
            logger.info(f"  {i+1}. '{item.title}' (Provider: {item.provider}, Type: {item.type})")

        # 使用与WebUI相同的智能排序逻辑，优化年份权重
        all_search_results.sort(
            key=lambda item: (
                # 1. 最高优先级：完全匹配的标题
                10000 if item.title.strip() == animeTitle.strip() else 0,
                # 2. 次高优先级：去除标点符号后的完全匹配
                5000 if item.title.replace("：", ":").replace(" ", "").strip() == animeTitle.replace("：", ":").replace(" ", "").strip() else 0,
                # 3. 第三优先级：高相似度匹配（98%以上）且标题长度差异不大
                2000 if (fuzz.token_sort_ratio(animeTitle, item.title) > 98 and abs(len(item.title) - len(animeTitle)) <= 10) else 0,
                # 4. 第四优先级：较高相似度匹配（95%以上）且标题长度差异不大
                1000 if (fuzz.token_sort_ratio(animeTitle, item.title) > 95 and abs(len(item.title) - len(animeTitle)) <= 20) else 0,
                # 5. 年份匹配（降低权重，避免年份匹配但标题不匹配的结果排在前面）
                500 if year is not None and item.year is not None and item.year == year else 0,
                # 6. 季度匹配（仅对电视剧）
                100 if season is not None and mediaType == 'tv_series' and item.season == season else 0,
                # 7. 一般相似度，但必须达到85%以上才考虑
                fuzz.token_set_ratio(animeTitle, item.title) if fuzz.token_set_ratio(animeTitle, item.title) >= 85 else 0,
                # 8. 惩罚标题长度差异大的结果
                -abs(len(item.title) - len(animeTitle)),
                # 9. 惩罚年份不匹配的结果（如果webhook提供了年份但搜索结果年份不匹配）
                -500 if year is not None and item.year is not None and item.year != year else 0,
                # 10. 最后考虑源优先级
                -provider_order.get(item.provider, 999)
            ),
            reverse=True # 按得分从高到低排序
        )

        # 添加排序后的调试日志
        logger.info(f"Webhook 任务: 排序后的前5个结果:")
        for i, item in enumerate(all_search_results[:5]):
            title_match = "✓" if item.title.strip() == animeTitle.strip() else "✗"
            year_match = "✓" if year is not None and item.year is not None and item.year == year else ("✗" if year is not None and item.year is not None else "-")
            similarity = fuzz.token_set_ratio(animeTitle, item.title)
            year_info = f"年份: {item.year}" if item.year else "年份: 未知"
            logger.info(f"  {i+1}. '{item.title}' (Provider: {item.provider}, Type: {item.type}, {year_info}, 年份匹配: {year_match}, 标题匹配: {title_match}, 相似度: {similarity}%)")

        # 评估所有候选项 (不限制数量)
        logger.info(f"Webhook 任务: 共有 {len(all_search_results)} 个搜索结果")

        # 检查是否启用AI匹配
        ai_match_enabled = (await config_manager.get("aiMatchEnabled", "false")).lower() == 'true'
        best_match = None
        ai_selected_index = None

        if ai_match_enabled:
            logger.info("Webhook 任务: AI匹配已启用")
            try:
                # 获取AI配置 - 使用 AIMatcher 期望的键名
                ai_config = {
                    'ai_match_provider': await config_manager.get("aiProvider", "deepseek"),
                    'ai_match_api_key': await config_manager.get("aiApiKey", ""),
                    'ai_match_base_url': await config_manager.get("aiBaseUrl", ""),
                    'ai_match_model': await config_manager.get("aiModel", ""),
                    'ai_match_prompt': await config_manager.get("aiPrompt", ""),
                    'ai_log_raw_response': (await config_manager.get("aiLogRawResponse", "false")).lower() == 'true'
                }

                # 检查必要配置
                if not ai_config['ai_match_api_key']:
                    logger.warning("Webhook 任务: AI匹配已启用但未配置API密钥，降级到传统匹配")
                else:
                    # 构建查询信息
                    query_info = {
                        'title': animeTitle,
                        'season': season if mediaType == 'tv_series' else None,
                        'episode': currentEpisodeIndex,
                        'year': year,
                        'type': mediaType
                    }

                    # 获取精确标记信息
                    favorited_info = {}

                    for result in all_search_results:
                        # 查找是否有相同provider和mediaId的源被标记
                        stmt = (
                            select(AS.isFavorited)
                            .where(
                                AS.providerName == result.provider,
                                AS.mediaId == result.mediaId
                            )
                            .limit(1)
                        )
                        result_row = await session.execute(stmt)
                        is_favorited = result_row.scalar_one_or_none()
                        if is_favorited:
                            key = f"{result.provider}:{result.mediaId}"
                            favorited_info[key] = True

                    # 初始化AI匹配器并选择
                    from ..ai_matcher import AIMatcher
                    matcher = AIMatcher(ai_config)
                    ai_selected_index = await matcher.select_best_match(
                        query_info, all_search_results, favorited_info
                    )

                if ai_selected_index is not None:
                    best_match = all_search_results[ai_selected_index]
                    logger.info(f"Webhook 任务: AI匹配成功选择: {best_match.provider} - {best_match.title}")
                else:
                    # 检查是否启用传统匹配兜底
                    ai_fallback_enabled = (await config_manager.get("aiFallbackEnabled", "true")).lower() == 'true'
                    if ai_fallback_enabled:
                        logger.info("Webhook 任务: AI匹配未找到合适结果，降级到传统匹配")
                    else:
                        logger.warning("Webhook 任务: AI匹配未找到合适结果，且传统匹配兜底已禁用")
                        raise ValueError("AI匹配失败且传统匹配兜底已禁用")

            except Exception as e:
                # 检查是否启用传统匹配兜底
                ai_fallback_enabled = (await config_manager.get("aiFallbackEnabled", "true")).lower() == 'true'
                if ai_fallback_enabled:
                    logger.error(f"Webhook 任务: AI匹配失败，降级到传统匹配: {e}")
                else:
                    logger.error(f"Webhook 任务: AI匹配失败，且传统匹配兜底已禁用: {e}")
                    raise ValueError(f"AI匹配失败且传统匹配兜底已禁用: {e}")
                ai_selected_index = None

        # 如果AI选择成功，使用AI选择的结果
        if best_match is not None:
            logger.info(f"Webhook 任务: 使用AI选择的结果: {best_match.provider} - {best_match.title}")
            await progress_callback(50, f"在 {best_match.provider} 中找到最佳匹配项")

            current_time = get_now().strftime("%H:%M:%S")
            # 根据来源动态生成任务标题前缀
            if webhookSource == "media_server":
                source_prefix = "媒体库读取导入"
            elif webhookSource in ["emby", "jellyfin", "plex"]:
                source_prefix = f"Webhook自动导入 ({webhookSource.capitalize()})"
            else:
                source_prefix = f"Webhook自动导入 ({webhookSource})"

            if mediaType == "tv_series":
                task_title = f"{source_prefix}: {best_match.title} - S{season:02d}E{currentEpisodeIndex:02d} ({best_match.provider}) [{current_time}]"
            else:
                task_title = f"{source_prefix}: {best_match.title} ({best_match.provider}) [{current_time}]"
            unique_key = f"import-{best_match.provider}-{best_match.mediaId}-S{season}-ep{currentEpisodeIndex}"

            # 修正：优先使用搜索结果的年份，如果搜索结果没有年份则使用webhook传入的年份
            final_year = best_match.year if best_match.year is not None else year
            task_coro = lambda session, cb: generic_import_task(
                provider=best_match.provider, mediaId=best_match.mediaId, year=final_year,
                animeTitle=best_match.title, mediaType=best_match.type,
                season=season, currentEpisodeIndex=currentEpisodeIndex, imageUrl=best_match.imageUrl, config_manager=config_manager, metadata_manager=metadata_manager,
                doubanId=doubanId, tmdbId=tmdbId, imdbId=imdbId, tvdbId=tvdbId, bangumiId=bangumiId, rate_limiter=rate_limiter,
                progress_callback=cb, session=session, manager=manager,
                task_manager=task_manager,
                title_recognition_manager=title_recognition_manager,
                selectedEpisodes=selectedEpisodes,
            )
            await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)

            # 根据来源动态生成成功消息
            if webhookSource == "media_server":
                success_message = f"已为源 '{best_match.provider}' 创建导入任务。"
            else:
                success_message = f"Webhook: 已为源 '{best_match.provider}' 创建导入任务。"
            raise TaskSuccess(success_message)

        # 传统匹配: 优先查找精确标记源 (需验证标题相似度)
        favorited_match = None

        for result in all_search_results:
            # 查找是否有相同provider和mediaId的源被标记
            stmt = (
                select(AS.isFavorited)
                .where(
                    AS.providerName == result.provider,
                    AS.mediaId == result.mediaId
                )
                .limit(1)
            )
            result_row = await session.execute(stmt)
            is_favorited = result_row.scalar_one_or_none()
            if is_favorited:
                # 验证标题相似度,避免错误匹配
                similarity = fuzz.token_set_ratio(animeTitle, result.title)
                logger.info(f"Webhook 任务: 找到精确标记源: {result.provider} - {result.title} (相似度: {similarity}%)")

                # 只有相似度 >= 60% 才使用精确标记源
                if similarity >= 60:
                    favorited_match = result
                    logger.info(f"Webhook 任务: 标题相似度验证通过 ({similarity}% >= 60%)")
                    break
                else:
                    logger.warning(f"Webhook 任务: 标题相似度过低 ({similarity}% < 60%)，跳过此精确标记源")

        # 检查是否启用顺延机制
        fallback_enabled = (await config_manager.get("webhookFallbackEnabled", "false")).lower() == 'true'

        if favorited_match:
            best_match = favorited_match
            logger.info(f"Webhook 任务: 使用精确标记源: {best_match.provider} - {best_match.title}")
        elif not fallback_enabled:
            # 顺延机制关闭，使用第一个结果 (已经是分数最高的)
            if all_search_results:
                best_match = all_search_results[0]
                logger.info(f"Webhook 任务: 顺延机制已关闭，选择第一个结果: {best_match.provider} - {best_match.title}")
            else:
                logger.warning(f"Webhook 任务: 顺延机制已关闭，但搜索结果为空，无法选择结果")

        if best_match is not None:
            await progress_callback(50, f"在 {best_match.provider} 中找到最佳匹配项")

            current_time = get_now().strftime("%H:%M:%S")
            # 根据来源动态生成任务标题前缀
            if webhookSource == "media_server":
                source_prefix = "媒体库读取导入"
            elif webhookSource in ["emby", "jellyfin", "plex"]:
                source_prefix = f"Webhook自动导入 ({webhookSource.capitalize()})"
            else:
                source_prefix = f"Webhook自动导入 ({webhookSource})"

            if mediaType == "tv_series":
                task_title = f"{source_prefix}: {best_match.title} - S{season:02d}E{currentEpisodeIndex:02d} ({best_match.provider}) [{current_time}]"
            else:
                task_title = f"{source_prefix}: {best_match.title} ({best_match.provider}) [{current_time}]"
            unique_key = f"import-{best_match.provider}-{best_match.mediaId}-S{season}-ep{currentEpisodeIndex}"

            # 修正：优先使用搜索结果的年份，如果搜索结果没有年份则使用webhook传入的年份
            final_year = best_match.year if best_match.year is not None else year
            task_coro = lambda session, cb: generic_import_task(
                provider=best_match.provider, mediaId=best_match.mediaId, year=final_year,
                animeTitle=best_match.title, mediaType=best_match.type,
                season=season, currentEpisodeIndex=currentEpisodeIndex, imageUrl=best_match.imageUrl, config_manager=config_manager, metadata_manager=metadata_manager,
                doubanId=doubanId, tmdbId=tmdbId, imdbId=imdbId, tvdbId=tvdbId, bangumiId=bangumiId, rate_limiter=rate_limiter,
                progress_callback=cb, session=session, manager=manager,
                task_manager=task_manager,
                title_recognition_manager=title_recognition_manager,
                selectedEpisodes=selectedEpisodes,
            )
            await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)

            # 根据来源动态生成成功消息
            if webhookSource == "media_server":
                success_message = f"已为源 '{best_match.provider}' 创建导入任务。"
            else:
                success_message = f"Webhook: 已为源 '{best_match.provider}' 创建导入任务。"
            raise TaskSuccess(success_message)

        # 顺延机制启用：依次验证候选源 (按分数从高到低)
        logger.info(f"🔄 Webhook 顺延机制: 已启用，共有 {len(all_search_results)} 个候选源待验证")
        for attempt, candidate in enumerate(all_search_results, 1):
            logger.info(f"→ [{attempt}/{len(all_search_results)}] 正在验证: {candidate.provider} - {candidate.title} (ID: {candidate.mediaId}, 类型: {candidate.type})")
            try:
                scraper = manager.get_scraper(candidate.provider)
                if not scraper:
                    logger.warning(f"    {attempt}. {candidate.provider} - 无法获取scraper，跳过")
                    continue

                # 获取分集列表进行验证
                episodes = await scraper.get_episodes(candidate.mediaId, db_media_type=candidate.type)
                if not episodes:
                    logger.warning(f"    {attempt}. {candidate.provider} - 没有分集列表，跳过")
                    continue

                # 如果是电影，只匹配电影类型的候选源
                if mediaType == "movie":
                    if candidate.type != "movie":
                        logger.warning(f"    {attempt}. {candidate.provider} - 类型不匹配 (搜索电影，但候选源是{candidate.type})，跳过")
                        continue
                    logger.info(f"    {attempt}. {candidate.provider} - 验证通过 (电影)")
                # 如果是电视剧，检查是否有目标集数
                else:
                    target_episode = None
                    for ep in episodes:
                        if ep.episodeIndex == currentEpisodeIndex:
                            target_episode = ep
                            break

                    if not target_episode:
                        logger.warning(f"    {attempt}. {candidate.provider} - 没有第 {currentEpisodeIndex} 集，跳过")
                        continue

                    logger.info(f"    {attempt}. {candidate.provider} - 验证通过")

                best_match = candidate
                break
            except Exception as e:
                logger.warning(f"    {attempt}. {candidate.provider} - 验证失败: {e}")
                continue

        if not best_match:
            logger.warning(f"Webhook 任务: 所有候选源都无法提供有效分集")
            raise ValueError(f"所有候选源都无法提供第 {currentEpisodeIndex} 集")

        # 提交导入任务
        await progress_callback(50, f"在 {best_match.provider} 中找到最佳匹配项")

        current_time = get_now().strftime("%H:%M:%S")
        # 根据来源动态生成任务标题前缀
        if webhookSource == "media_server":
            source_prefix = "媒体库读取导入"
        elif webhookSource in ["emby", "jellyfin", "plex"]:
            source_prefix = f"Webhook自动导入 ({webhookSource.capitalize()})"
        else:
            source_prefix = f"Webhook自动导入 ({webhookSource})"

        if mediaType == "tv_series":
            task_title = f"{source_prefix}: {best_match.title} - S{season:02d}E{currentEpisodeIndex:02d} ({best_match.provider}) [{current_time}]"
        else:
            task_title = f"{source_prefix}: {best_match.title} ({best_match.provider}) [{current_time}]"
        unique_key = f"import-{best_match.provider}-{best_match.mediaId}-S{season}-ep{currentEpisodeIndex}"

        # 修正：优先使用搜索结果的年份，如果搜索结果没有年份则使用webhook传入的年份
        final_year = best_match.year if best_match.year is not None else year
        task_coro = lambda session, cb: generic_import_task(
            provider=best_match.provider, mediaId=best_match.mediaId, year=final_year,
            animeTitle=best_match.title, mediaType=best_match.type,
            season=season, currentEpisodeIndex=currentEpisodeIndex, imageUrl=best_match.imageUrl, config_manager=config_manager, metadata_manager=metadata_manager,
            doubanId=doubanId, tmdbId=tmdbId, imdbId=imdbId, tvdbId=tvdbId, bangumiId=bangumiId, rate_limiter=rate_limiter,
            progress_callback=cb, session=session, manager=manager,
            task_manager=task_manager,
            title_recognition_manager=title_recognition_manager,
            selectedEpisodes=selectedEpisodes,
        )
        await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)

        # 根据来源动态生成成功消息
        if webhookSource == "media_server":
            success_message = f"已为源 '{best_match.provider}' 创建导入任务。"
        else:
            success_message = f"Webhook: 已为源 '{best_match.provider}' 创建导入任务。"
        raise TaskSuccess(success_message)
    except TaskSuccess:
        raise
    except Exception as e:
        logger.error(f"Webhook 搜索与分发任务发生严重错误: {e}", exc_info=True)
        raise

