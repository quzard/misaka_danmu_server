import logging
import re
from typing import Optional
from fastapi import Request, HTTPException, status

from .base import BaseWebhook

logger = logging.getLogger(__name__)

class EmbyWebhook(BaseWebhook):
    async def handle(self, request: Request, webhook_source: str):
        # 处理器现在负责解析请求体。
        # Emby 通常发送 application/json。
        try:
            payload = await request.json()
        except Exception:
            self.logger.error("Emby Webhook: 无法解析请求体为JSON。")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请求体不是有效的JSON。")

        event_type = payload.get("Event")
        # 我们只关心新媒体入库的事件, 兼容 emby 的 'library.new' 和 jellyfin 的 'item.add'
        if event_type not in ["library.new"]:
            logger.info(f"Webhook: 忽略非 'item.add' 或 'library.new' 的事件 (类型: {event_type})")
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
        tmdb_id = provider_ids.get("Tmdb")
        imdb_id = provider_ids.get("IMDB") # 修正：Emby 使用大写的 "IMDB"
        tvdb_id = provider_ids.get("Tvdb")
        douban_id = provider_ids.get("DoubanID") # Emby 可能使用 DoubanID
        bangumi_id = provider_ids.get("Bangumi")
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
            # 聚合通知：Emby 批量入库多集时会发送 Type=Series 的 library.new 事件
            # 季号和集数范围在 Description 中，格式为 "S02 E01-E06\n\nTmdbId: ..."
            series_title = item.get("Name")
            if not series_title:
                logger.warning("Emby Webhook: 聚合通知缺少 Series 标题，忽略。")
                return

            description = payload.get("Description", "")
            season_number: Optional[int] = None
            # 解析 "S02 E01-E06" 格式
            season_match = re.search(r'S(\d+)', description, re.IGNORECASE)
            if season_match:
                season_number = int(season_match.group(1))

            if season_number is None:
                logger.warning(f"Emby Webhook: 聚合通知 Description 中无法解析季号，Description='{description}'，忽略。")
                return

            # 解析集数范围 "E01-E06" → [1,2,3,4,5,6]
            selected_episodes: Optional[list] = None
            ep_range_str = ""
            ep_range_match = re.search(r'E(\d+)\s*-\s*E(\d+)', description, re.IGNORECASE)
            ep_single_match = re.search(r'E(\d+)', description, re.IGNORECASE)
            if ep_range_match:
                ep_start = int(ep_range_match.group(1))
                ep_end = int(ep_range_match.group(2))
                selected_episodes = list(range(ep_start, ep_end + 1))
                ep_range_str = f"E{ep_start:02d}-E{ep_end:02d}"
            elif ep_single_match:
                ep_start = int(ep_single_match.group(1))
                selected_episodes = [ep_start]
                ep_range_str = f"E{ep_start:02d}"

            logger.info(
                f"Emby Webhook: 解析到聚合通知 - 标题: '{series_title}', 季: {season_number}, "
                f"集数范围: {ep_range_str or '未知'}, selectedEpisodes={selected_episodes}"
            )

            # currentEpisodeIndex=None + selectedEpisodes=[1..N]：以一个任务导入指定集数
            episode_number = None
            task_title = f"Webhook（emby）聚合搜索: {series_title} - S{season_number:02d} {ep_range_str}"
            search_keyword = f"{series_title} S{season_number:02d}"
            media_type = "tv_series"
            anime_title = series_title

        # 新逻辑：总是触发全网搜索任务，并附带元数据ID
        _ep_range_str = ep_range_str if item_type == "Series" else ""
        ep_suffix = f"E{episode_number}" if episode_number is not None else _ep_range_str or "全季"
        unique_key = f"webhook-search-{anime_title}-S{season_number}-{ep_suffix}"
        logger.info(f"Webhook: 准备为 '{anime_title}' 创建全网搜索任务，并附加元数据ID (TMDB: {tmdb_id}, IMDb: {imdb_id}, TVDB: {tvdb_id}, Douban: {douban_id})。")

        # 将所有需要的信息打包成 payload
        task_payload = {
            "animeTitle": anime_title, "mediaType": media_type, "season": season_number,
            "currentEpisodeIndex": episode_number, "year": year, "searchKeyword": search_keyword,
            "doubanId": str(douban_id) if douban_id else None,
            "tmdbId": str(tmdb_id) if tmdb_id else None,
            "imdbId": str(imdb_id) if imdb_id else None,
            "tvdbId": str(tvdb_id) if tvdb_id else None,
            "bangumiId": str(bangumi_id) if bangumi_id else None,
            "selectedEpisodes": selected_episodes if item_type == "Series" else None,
        }

        await self.dispatch_task(
            task_title=task_title, unique_key=unique_key,
            payload=task_payload, webhook_source=webhook_source
        )