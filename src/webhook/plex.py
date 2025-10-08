import logging
import json
from typing import Any, Dict
from fastapi import Request, HTTPException, status

from .base import BaseWebhook
from ..scraper_manager import ScraperManager

logger = logging.getLogger(__name__)

class PlexWebhook(BaseWebhook):
    async def handle(self, request: Request, webhook_source: str):
        # 记录收到webhook请求
        self.logger.info(f"Plex Webhook: 收到请求")
        self.logger.info(f"Headers: {dict(request.headers)}")

        # 处理器现在负责解析请求体。
        # Plex 发送 JSON 格式的请求。
        try:
            payload = await request.json()
        except Exception:
            self.logger.error("Plex Webhook: 无法解析请求体为JSON。")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请求体不是有效的JSON。")

        # 记录完整的webhook请求内容
        self.logger.info(f"Plex Webhook完整请求: {json.dumps(payload, indent=2, ensure_ascii=False)}")

        # 检查事件类型
        event = payload.get("event")
        if event != "library.new":
            self.logger.info(f"Plex Webhook: 忽略非 'library.new' 事件 (事件类型: {event})")
            return

        # 获取媒体信息
        metadata = payload.get("Metadata", {})
        if not metadata:
            self.logger.warning("Plex Webhook: 负载中缺少 'Metadata' 信息")
            return

        # 获取媒体类型
        media_type = metadata.get("type")
        if media_type not in ["episode", "movie"]:
            self.logger.info(f"Plex Webhook: 忽略非 'episode' 或 'movie' 的媒体项 (类型: {media_type})")
            return

        # 提取通用信息
        guid_list = metadata.get("Guid", [])
        provider_ids = self._extract_provider_ids(guid_list)
        
        tmdb_id = provider_ids.get("tmdb")
        imdb_id = provider_ids.get("imdb")
        tvdb_id = provider_ids.get("tvdb")
        # Plex可能不直接支持豆瓣和Bangumi ID，但我们保留字段以备将来使用
        douban_id = provider_ids.get("douban")
        bangumi_id = provider_ids.get("bangumi")
        
        year = metadata.get("year")
        
        self.logger.info(f"提取的Provider IDs: TMDB={tmdb_id}, IMDB={imdb_id}, TVDB={tvdb_id}")

        # 根据媒体类型分别处理
        if media_type == "episode":
            # 处理剧集
            episode_title = metadata.get("title", "")
            series_title = metadata.get("grandparentTitle", "")  # 剧集的系列标题
            season_number = metadata.get("parentIndex")  # 季数
            episode_number = metadata.get("index")  # 集数
            
            if not all([series_title, season_number is not None, episode_number is not None]):
                self.logger.warning("Plex Webhook: 忽略剧集，因为缺少系列标题、季度或集数信息")
                self.logger.warning(f"系列标题: {series_title}, 季数: {season_number}, 集数: {episode_number}")
                return

            self.logger.info(f"Plex Webhook: 解析到剧集 - 系列: '{series_title}', 集标题: '{episode_title}', S{season_number:02d}E{episode_number:02d}")
            
            task_title = f"Webhook（plex）搜索: {series_title} - S{season_number:02d}E{episode_number:02d}"
            search_keyword = f"{series_title} S{season_number:02d}E{episode_number:02d}"
            final_media_type = "tv_series"
            anime_title = series_title
            
        elif media_type == "movie":
            # 处理电影
            movie_title = metadata.get("title", "")
            if not movie_title:
                self.logger.warning("Plex Webhook: 忽略电影，因为缺少标题信息")
                return
            
            self.logger.info(f"Plex Webhook: 解析到电影 - 标题: '{movie_title}'")
            
            task_title = f"Webhook（plex）搜索: {movie_title}"
            search_keyword = movie_title
            final_media_type = "movie"
            season_number = 1
            episode_number = 1  # 电影按单集处理
            anime_title = movie_title

        # 创建搜索任务
        unique_key = f"webhook-plex-search-{anime_title}-S{season_number}-E{episode_number}"
        self.logger.info(f"Plex Webhook: 准备为 '{anime_title}' 创建全网搜索任务，并附加元数据ID")

        # 将所有需要的信息打包成 payload
        task_payload = {
            "animeTitle": anime_title,
            "mediaType": final_media_type,
            "season": season_number,
            "currentEpisodeIndex": episode_number,
            "year": year,
            "searchKeyword": search_keyword,
            "doubanId": str(douban_id) if douban_id else None,
            "tmdbId": str(tmdb_id) if tmdb_id else None,
            "imdbId": str(imdb_id) if imdb_id else None,
            "tvdbId": str(tvdb_id) if tvdb_id else None,
            "bangumiId": str(bangumi_id) if bangumi_id else None,
        }

        await self.dispatch_task(
            task_title=task_title,
            unique_key=unique_key,
            payload=task_payload,
            webhook_source=webhook_source
        )

    def _extract_provider_ids(self, guid_list):
        """
        从Plex的Guid列表中提取provider IDs
        
        Plex的Guid格式示例：
        - "plex://movie/5d776b59ad5437001f79c6f8"
        - "imdb://tt0111161"
        - "tmdb://278"
        - "tvdb://290434"
        """
        provider_ids = {}
        
        for guid_info in guid_list:
            if isinstance(guid_info, dict):
                guid_id = guid_info.get("id", "")
            else:
                guid_id = str(guid_info)
            
            self.logger.debug(f"处理GUID: {guid_id}")
            
            # 解析不同的provider格式
            if guid_id.startswith("imdb://"):
                provider_ids["imdb"] = guid_id.replace("imdb://", "")
            elif guid_id.startswith("tmdb://"):
                provider_ids["tmdb"] = guid_id.replace("tmdb://", "")
            elif guid_id.startswith("tvdb://"):
                provider_ids["tvdb"] = guid_id.replace("tvdb://", "")
            elif guid_id.startswith("douban://"):
                provider_ids["douban"] = guid_id.replace("douban://", "")
            elif guid_id.startswith("bangumi://"):
                provider_ids["bangumi"] = guid_id.replace("bangumi://", "")
        
        return provider_ids
