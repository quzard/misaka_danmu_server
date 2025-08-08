import logging
from typing import Any, Dict

from .base import BaseWebhook
from ..scraper_manager import ScraperManager
from .tasks import webhook_search_and_dispatch_task

logger = logging.getLogger(__name__)

class JellyfinWebhook(BaseWebhook):
    async def handle(self, payload: Dict[str, Any]):
        event_type = payload.get("NotificationType")
        if event_type not in ["ItemAdded"]:
            logger.info(f"Webhook: 忽略非 'ItemAdded' 的事件 (类型: {event_type})")
            return

        item_type = payload.get("ItemType")
        if item_type not in ["Episode", "Movie"]:
            logger.info(f"Webhook: 忽略非 'Episode' 或 'Movie' 的媒体项 (类型: {item_type})")
            return

        # 提取通用信息
        tmdb_id = payload.get("Provider_tmdb")
        imdb_id = payload.get("Provider_imdb")
        tvdb_id = payload.get("Provider_tvdb")
        douban_id = payload.get("Provider_doubanid")
        
        # 根据媒体类型分别处理
        if item_type == "Episode":
            series_title = payload.get("SeriesName")
            # 修正：使用正确的键名来获取季度和集数
            season_number = payload.get("SeasonNumber")
            episode_number = payload.get("EpisodeNumber")
            
            if not all([series_title, season_number is not None, episode_number is not None]):
                logger.warning(f"Webhook: 忽略一个剧集，因为缺少系列标题、季度或集数信息。")
                return

            logger.info(f"Webhook: 收到剧集 '{series_title}' S{season_number:02d}E{episode_number:02d}' 的入库通知。")
            
            task_title = f"Webhook（jellyfin）搜索: {series_title} - S{season_number:02d}E{episode_number:02d}"
            search_keyword = f"{series_title} S{season_number:02d}E{episode_number:02d}"
            media_type = "tv_series"
            anime_title = series_title
            
        elif item_type == "Movie":
            movie_title = payload.get("Name")
            if not movie_title:
                logger.warning(f"Webhook: 忽略一个电影，因为缺少标题信息。")
                return
            
            logger.info(f"Webhook: 收到电影 '{movie_title}' 的入库通知。")
            
            task_title = f"Webhook（jellyfin）搜索: {movie_title}"
            search_keyword = movie_title
            media_type = "movie"
            season_number = 1
            episode_number = 1 # 电影按单集处理
            anime_title = movie_title
        
        # 新逻辑：总是触发全网搜索任务，并附带元数据ID
        logger.info(f"Webhook: 准备为 '{anime_title}' 创建全网搜索任务，并附加元数据ID (TMDB: {tmdb_id}, IMDb: {imdb_id}, TVDB: {tvdb_id}, Douban: {douban_id})。")

        # 动态创建一个 ScraperManager 实例以供导入任务使用
        scraper_manager = ScraperManager(self.pool)
        await scraper_manager.load_and_sync_scrapers()

        # 使用新的、专门的 webhook 任务
        task_coro = lambda callback: webhook_search_and_dispatch_task(
            anime_title=anime_title,
            media_type=media_type,
            season=season_number,
            current_episode_index=episode_number,
            search_keyword=search_keyword,
            douban_id=str(douban_id) if douban_id else None,
            tmdb_id=str(tmdb_id) if tmdb_id else None,
            imdb_id=str(imdb_id) if imdb_id else None,
            tvdb_id=str(tvdb_id) if tvdb_id else None,
            webhook_source='jellyfin',
            progress_callback=callback,
            pool=self.pool,
            manager=scraper_manager,
            task_manager=self.task_manager
        )
        await self.task_manager.submit_task(task_coro, task_title)