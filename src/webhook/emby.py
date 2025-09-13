import logging
from typing import Any, Dict
from fastapi import Request, HTTPException, status

from .base import BaseWebhook
from ..scraper_manager import ScraperManager
from .tasks import webhook_search_and_dispatch_task
import json

logger = logging.getLogger(__name__)

class EmbyWebhook(BaseWebhook):
    async def handle(self, request: Request):
        # 处理器现在负责解析请求体。
        # Emby 通常发送 application/json。
        try:
            payload = await request.json()
        except Exception:
            self.logger.error("Emby Webhook: 无法解析请求体为JSON。")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请求体不是有效的JSON。")
        logger.info(f"Emby Webhook: 收到请求，请求: {json.dumps(payload, indent=4)}")
        event_type = payload.get("Event")
        # 我们只关心新媒体入库的事件, 兼容 emby 的 'library.new' 和 jellyfin 的 'item.add'
        if event_type not in ["item.markplayed", "library.new", "item.rate"]:
            logger.info(f"Webhook: 忽略非 'item.add', 'item.rate' 或 'library.new' 的事件 (类型: {event_type})")
            return

        item = payload.get("Item", {})
        if not item:
            logger.warning("Emby Webhook: 负载中缺少 'Item' 信息。")
            return

        item_type = item.get("Type")
        if item_type not in ["Episode", "Movie", "Series"]:
            logger.info(f"Webhook: 忽略非 'Episode'、'Movie' 或 'Series' 的媒体项 (类型: {item_type})")
            return

        # 提取通用信息
        provider_ids = item.get("ProviderIds", {})
        # 兼容不同大小写/命名
        tmdb_id = provider_ids.get("Tmdb") or provider_ids.get("TMDB") or provider_ids.get("tmdb")
        imdb_id = provider_ids.get("Imdb") or provider_ids.get("IMDB") or provider_ids.get("imdb")
        tvdb_id = provider_ids.get("Tvdb") or provider_ids.get("TVDB") or provider_ids.get("tvdb")
        douban_id = provider_ids.get("DoubanID") or provider_ids.get("Douban") or provider_ids.get("douban")
        bangumi_id = provider_ids.get("Bangumi") or provider_ids.get("bangumi")
        year = item.get("ProductionYear")
        
        # 根据媒体类型分别处理
        if item_type == "Episode":
            series_title = item.get("SeriesName")
            # 修正：使用正确的键名来获取季度和集数
            season_number = item.get("ParentIndexNumber")
            episode_number = item.get("IndexNumber")
            
            if not all([series_title, season_number is not None, episode_number is not None]):
                logger.warning(f"Webhook: 忽略一个剧集，因为缺少系列标题、季度或集数信息。")
                return

            logger.info(f"Emby Webhook: 解析到剧集 - 标题: '{series_title}', 类型: Episode, 季: {season_number}, 集: {episode_number}")
            logger.info(f"Webhook: 收到剧集 '{series_title}' S{season_number:02d}E{episode_number:02d}' 的入库通知。")
            
            task_title = f"Webhook（emby）搜索: {series_title} - S{season_number:02d}E{episode_number:02d}"
            search_keyword = f"{series_title} S{season_number:02d}E{episode_number:02d}"
            media_type = "tv_series"
            anime_title = series_title
            
        elif item_type == "Movie":
            movie_title = item.get("Name")
            if not movie_title:
                logger.warning(f"Webhook: 忽略一个电影，因为缺少标题信息。")
                return
            
            logger.info(f"Emby Webhook: 解析到电影 - 标题: '{movie_title}', 类型: Movie")
            logger.info(f"Webhook: 收到电影 '{movie_title}' 的入库通知。")
            
            task_title = f"Webhook（emby）搜索: {movie_title}"
            search_keyword = movie_title
            media_type = "movie"
            season_number = 1
            episode_number = 1 # 电影按单集处理
            anime_title = movie_title
        elif item_type == "Series":
            # 收藏/评分剧集（整部剧），没有具体季/集信息，这里默认 S1E1 作为触发点
            series_title = item.get("Name") or item.get("OriginalTitle") or item.get("SortName")
            if not series_title:
                logger.warning("Webhook: 忽略一个剧集（Series），因为缺少标题信息。")
                return

            logger.info(f"Emby Webhook: 解析到剧集（整部）- 标题: '{series_title}', 类型: Series")
            logger.info(f"Webhook: 收到剧集 '{series_title}' 的收藏/评分通知（Series 级别）。")

            # 新增：整剧收藏时，尝试导入“所有季（整季）”。
            media_type = "tv_series"
            anime_title = series_title

            # 1) 先通过全网搜索探测可用的季列表
            try:
                search_results = await self.scraper_manager.search_all([series_title])
            except Exception as e:
                logger.error(f"为整剧 '{series_title}' 探测季信息时搜索失败: {e}", exc_info=True)
                search_results = []

            seasons_found = sorted({r.season for r in search_results if r.type == 'tv_series' and isinstance(r.season, int) and r.season > 0})
            if not seasons_found:
                seasons_found = [1]
                logger.info(f"未能从搜索结果推断季信息，回退为 S01。")
            else:
                logger.info(f"为 '{series_title}' 检测到季列表: {seasons_found}")

            # 2) 为每个季提交一个“整季导入”任务（currentEpisodeIndex=None）
            for s in seasons_found:
                task_title = f"Webhook（emby）搜索: {series_title} - S{s:02d} 全季"
                search_keyword = f"{series_title} S{s:02d}"
                unique_key = f"webhook-search-{anime_title}-S{s}-FULL"

                logger.info(
                    f"Webhook: 准备为 '{anime_title}' 的 S{s:02d} 创建整季导入搜索任务，附加元数据ID (TMDB: {tmdb_id}, IMDb: {imdb_id}, TVDB: {tvdb_id}, Douban: {douban_id})。"
                )

                task_coro = lambda session, callback, season_val=s: webhook_search_and_dispatch_task(
                    animeTitle=anime_title,
                    mediaType=media_type,
                    season=season_val,
                    currentEpisodeIndex=None,
                    year=year,
                    searchKeyword=search_keyword,
                    doubanId=str(douban_id) if douban_id else None,
                    tmdbId=str(tmdb_id) if tmdb_id else None,
                    imdbId=str(imdb_id) if imdb_id else None,
                    tvdbId=str(tvdb_id) if tvdb_id else None,
                    bangumiId=str(bangumi_id) if bangumi_id else None,
                    webhookSource='emby',
                    progress_callback=callback,
                    session=session,
                    metadata_manager=self.metadata_manager,
                    manager=self.scraper_manager, # type: ignore
                    task_manager=self.task_manager,
                    rate_limiter=self.rate_limiter
                )
                await self.task_manager.submit_task(task_coro, task_title, unique_key=unique_key)
            # 整剧模式下，已按季提交完任务，提前返回
            return
        
        # 新逻辑：总是触发全网搜索任务，并附带元数据ID
        unique_key = f"webhook-search-{anime_title}-S{season_number}-E{episode_number}"
        logger.info(f"Webhook: 准备为 '{anime_title}' 创建全网搜索任务，并附加元数据ID (TMDB: {tmdb_id}, IMDb: {imdb_id}, TVDB: {tvdb_id}, Douban: {douban_id})。")

        # 使用新的、专门的 webhook 任务
        task_coro = lambda session, callback: webhook_search_and_dispatch_task(
            animeTitle=anime_title,
            mediaType=media_type,
            season=season_number,
            currentEpisodeIndex=episode_number,
            year=year,
            searchKeyword=search_keyword,
            doubanId=str(douban_id) if douban_id else None,
            tmdbId=str(tmdb_id) if tmdb_id else None,
            imdbId=str(imdb_id) if imdb_id else None,
            tvdbId=str(tvdb_id) if tvdb_id else None,
            bangumiId=str(bangumi_id) if bangumi_id else None,
            webhookSource='emby',
            progress_callback=callback,
            session=session,
            metadata_manager=self.metadata_manager,
            manager=self.scraper_manager, # type: ignore
            task_manager=self.task_manager,
            rate_limiter=self.rate_limiter
        )
        await self.task_manager.submit_task(task_coro, task_title, unique_key=unique_key)