import logging
import re
from typing import Any, Callable, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from thefuzz import fuzz

from .. import crud
from ..rate_limiter import RateLimiter
from ..scraper_manager import ScraperManager
from ..metadata_manager import MetadataSourceManager
from ..task_manager import TaskManager, TaskSuccess
from ..tasks import generic_import_task
from ..utils import parse_search_keyword
from ..timezone import get_now

logger = logging.getLogger(__name__)

# 当多个候选条目的模糊匹配分数与最高分差值 <= 该阈值时，视为“同等最优”并全部下载。
# 目前为 0 表示只有完全相同最高分的才一起下载，后续如果需要放宽可改成 1~3。
FUZZY_TIE_SCORE_DELTA = 10


def _is_movie_by_title(title: str) -> bool:
    """
    通过标题中的关键词（如“剧场版”）判断是否为电影。
    """
    if not title:
        return False
    # 关键词列表，不区分大小写
    movie_keywords = ["剧场版", "劇場版", "movie", "映画"]
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in movie_keywords)


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
    rate_limiter: RateLimiter
):
    """
    Webhook 触发的后台任务：搜索所有源，找到最佳匹配，并为该匹配分发一个新的、具体的导入任务。
    """
    try:
        logger.info(f"Webhook 任务: 开始为 '{animeTitle}' (S{season:02d}E{currentEpisodeIndex:02d}) 查找最佳源...")
        progress_callback(5, "正在检查已收藏的源...")

        # 1. 优先查找已收藏的源 (Favorited Source)
        # 步骤 1a: 首先通过标题和季度找到库中的作品
        existing_anime = await crud.find_anime_by_title_and_season(session, animeTitle, season)
        if existing_anime:
            anime_id = existing_anime['id']
            # 步骤 1b: 然后查找该作品下是否有精确标记的源
            favorited_source = await crud.find_favorited_source_for_anime(session, anime_id)
            if favorited_source:
                logger.info(f"Webhook 任务: 找到已收藏的源 '{favorited_source['providerName']}'，将直接使用此源。")
                progress_callback(10, f"找到已收藏的源: {favorited_source['providerName']}")

                # 直接使用这个源的信息创建导入任务
                task_title = f"Webhook自动导入: {favorited_source['animeTitle']} - S{season:02d}E{currentEpisodeIndex:02d} ({favorited_source['providerName']})"
                unique_key = f"import-{favorited_source['providerName']}-{favorited_source['mediaId']}-ep{currentEpisodeIndex}"
                task_coro = lambda session, cb: generic_import_task(
                    provider=favorited_source['providerName'], mediaId=favorited_source['mediaId'], animeTitle=favorited_source['animeTitle'], year=year,
                    mediaType=favorited_source['mediaType'], season=season, currentEpisodeIndex=currentEpisodeIndex,
                    imageUrl=favorited_source['imageUrl'], doubanId=doubanId, tmdbId=tmdbId, imdbId=imdbId, tvdbId=tvdbId, metadata_manager=metadata_manager,
                    bangumiId=bangumiId, rate_limiter=rate_limiter,
                    progress_callback=cb, session=session, manager=manager,
                    task_manager=task_manager
                )
                await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)
                raise TaskSuccess(f"Webhook: 已为收藏源 '{favorited_source['providerName']}' 创建导入任务。")

        # 2. 如果没有收藏源，则并发搜索所有启用的源
        logger.info(f"Webhook 任务: 未找到收藏源，开始并发搜索所有启用的源...")
        progress_callback(20, "并发搜索所有源...")

        # 关键修复：像UI一样，先解析搜索关键词，分离出纯标题
        parsed_keyword = parse_search_keyword(searchKeyword)
        search_title_only = parsed_keyword["title"]
        logger.info(f"Webhook 任务: 已将搜索词 '{searchKeyword}' 解析为标题 '{search_title_only}' 进行搜索。")

        all_search_results = await manager.search_all(
            [search_title_only], episode_info={"season": season, "episode": currentEpisodeIndex}
        )

        if not all_search_results:
            raise ValueError(f"未找到 '{animeTitle}' 的任何可用源。")

        # 3. 从所有源的返回结果中，根据类型、季度和标题相似度选择最佳匹配项
        ordered_settings = await crud.get_all_scraper_settings(session)
        provider_order = {s['providerName']: s['displayOrder'] for s in ordered_settings}

        valid_candidates = []
        for item in all_search_results:
            if item.type == 'tv_series' and _is_movie_by_title(item.title):
                item.type = 'movie'
                item.season = 1

            type_match = (item.type == mediaType)
            season_match = (item.season == season) if mediaType == 'tv_series' else True

            if type_match and season_match:
                valid_candidates.append(item)

        if not valid_candidates:
            raise ValueError(f"未找到 '{animeTitle}' 的精确匹配项。")

        # 对候选进行排序：先按标题相似度得分，其次按 provider 的显示顺序
        valid_candidates.sort(
            key=lambda item: (fuzz.token_set_ratio(animeTitle, item.title), -provider_order.get(item.provider, 999)),
            reverse=True
        )
        # info 输出 valid_candidates
        logger.info(f"Webhook 任务: 找到 {len(valid_candidates)} 个有效候选源，按相似度排序如下:")
        for idx, candidate in enumerate(valid_candidates, start=1):
            score = fuzz.token_set_ratio(animeTitle, candidate.title)
            logger.info(f"  {idx}. {candidate.provider} - {candidate.title} (ID: {candidate.mediaId}) [Score: {score}]")

        # 取得最高的匹配分数
        top_score = fuzz.token_set_ratio(animeTitle, valid_candidates[0].title)
        # 收集与最高分差值 <= 阈值 的所有候选（即视为“同等最优”）
        top_matches = []
        for c in valid_candidates:
            score = fuzz.token_set_ratio(animeTitle, c.title)
            if top_score - score <= FUZZY_TIE_SCORE_DELTA:
                top_matches.append((c, score))
            else:
                break  # 因为已排序，后续分数只会更低

        # 去重（以 provider + mediaId 作为唯一键）
        seen_keys = set()
        unique_top_matches = []
        for c, score in top_matches:
            key_ = (c.provider, c.mediaId)
            if key_ not in seen_keys:
                seen_keys.add(key_)
                unique_top_matches.append((c, score))

        best_match = unique_top_matches[0][0]

        if len(unique_top_matches) > 1:
            logger.info(
                "Webhook 任务: 发现多个同分最高匹配 (分数: %s)。将全部创建导入任务: %s", 
                top_score,
                [f"{c.provider}:{c.title}" for c, _ in unique_top_matches]
            )
        else:
            logger.info(
                "Webhook 任务: 在所有源中找到唯一最佳匹配项 '%s' (来自: %s) 分数: %s", 
                best_match.title, best_match.provider, top_score
            )

        if len(unique_top_matches) == 1:
            logger.info(f"Webhook 任务: 在所有源中找到最佳匹配项 '{best_match.title}' (来自: {best_match.provider})，将为其创建导入任务。")
        else:
            logger.info(
                "Webhook 任务: 将为 %d 个同分最高的匹配项创建导入任务。", len(unique_top_matches)
            )

        progress_callback(55, f"准备创建 {len(unique_top_matches)} 个导入任务")

        # 批量创建任务
        current_time = get_now().strftime("%H:%M:%S")
        if len(unique_top_matches) > 1:
            created_titles = []
            total = len(unique_top_matches)
            for idx, (match_item, score) in enumerate(unique_top_matches, start=1):
                if mediaType == "tv_series":
                    task_title = (
                        f"Webhook（{webhookSource}）自动导入[{idx}/{total}]："
                        f"{match_item.title} - S{season:02d}E{currentEpisodeIndex:02d} ({match_item.provider}) [{current_time}]"
                    )
                else:
                    task_title = (
                        f"Webhook（{webhookSource}）自动导入[{idx}/{total}]："
                        f"{match_item.title} ({match_item.provider}) [{current_time}]"
                    )

                unique_key = f"import-{match_item.provider}-{match_item.mediaId}-ep{currentEpisodeIndex}"
                task_coro = lambda session, cb, mi=match_item: generic_import_task(
                    provider=mi.provider, mediaId=mi.mediaId, year=year,
                    animeTitle=mi.title, mediaType=mi.type,
                    season=season, currentEpisodeIndex=currentEpisodeIndex, imageUrl=mi.imageUrl, metadata_manager=metadata_manager,
                    doubanId=doubanId, tmdbId=tmdbId, imdbId=imdbId, tvdbId=tvdbId, bangumiId=bangumiId, rate_limiter=rate_limiter,
                    progress_callback=cb, session=session, manager=manager,
                    task_manager=task_manager
                )
                await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)
                created_titles.append(task_title)

            progress_callback(90, f"已创建 {len(created_titles)} 个导入任务")
            raise TaskSuccess(
                f"Webhook: 已为 {len(created_titles)} 个最高匹配源创建导入任务。"
            )
        else:
            # 单一最佳匹配项
            if mediaType == "tv_series":
                task_title = f"Webhook（{webhookSource}）自动导入：{best_match.title} - S{season:02d}E{currentEpisodeIndex:02d} ({best_match.provider}) [{current_time}]"
            else:  # movie
                task_title = f"Webhook（{webhookSource}）自动导入：{best_match.title} ({best_match.provider}) [{current_time}]"
            unique_key = f"import-{best_match.provider}-{best_match.mediaId}-ep{currentEpisodeIndex}"
            task_coro = lambda session, cb: generic_import_task(
                provider=best_match.provider, mediaId=best_match.mediaId, year=year,
                animeTitle=best_match.title, mediaType=best_match.type,
                season=season, currentEpisodeIndex=currentEpisodeIndex, imageUrl=best_match.imageUrl, metadata_manager=metadata_manager,
                doubanId=doubanId, tmdbId=tmdbId, imdbId=imdbId, tvdbId=tvdbId, bangumiId=bangumiId, rate_limiter=rate_limiter,
                progress_callback=cb, session=session, manager=manager,  # 修正：使用由TaskManager提供的session和cb
                task_manager=task_manager
            )
            await task_manager.submit_task(task_coro, task_title, unique_key=unique_key)
            raise TaskSuccess(f"Webhook: 已为源 '{best_match.provider}' 创建导入任务。")
    except TaskSuccess:
        raise
    except Exception as e:
        logger.error(f"Webhook 搜索与分发任务发生严重错误: {e}", exc_info=True)
        raise