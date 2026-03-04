import json
import logging
import re
from typing import Optional

from fastapi import HTTPException, Request, status

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

        logger.info(f"Emby Webhook: 收到请求，请求: {json.dumps(payload, indent=4, ensure_ascii=False)}")

        event_type = payload.get("Event")
        # 兼容本地扩展事件：评分/标记已看
        if event_type not in ["library.new", "item.rate", "item.markplayed"]:
            logger.info(f"Webhook: 忽略非 'library.new' / 'item.rate' / 'item.markplayed' 事件 (类型: {event_type})")
            return

        item = payload.get("Item", {})
        if not item:
            logger.warning("Emby Webhook: 负载中缺少 'Item' 信息。")
            return

        item_type = item.get("Type")
        if item_type not in ["Episode", "Movie", "Series"]:
            logger.info(f"Webhook: 忽略非 'Episode'、'Movie' 或 'Series' 的媒体项 (类型: {item_type})")
            return

        # 提取通用信息（兼容不同大小写/命名）
        provider_ids = item.get("ProviderIds", {})
        tmdb_id = provider_ids.get("Tmdb") or provider_ids.get("TMDB") or provider_ids.get("tmdb")
        imdb_id = provider_ids.get("Imdb") or provider_ids.get("IMDB") or provider_ids.get("imdb")
        tvdb_id = provider_ids.get("Tvdb") or provider_ids.get("TVDB") or provider_ids.get("tvdb")
        douban_id = provider_ids.get("DoubanID") or provider_ids.get("Douban") or provider_ids.get("douban")
        bangumi_id = provider_ids.get("Bangumi") or provider_ids.get("bangumi")
        year = item.get("ProductionYear")

        selected_episodes: Optional[list[int]] = None
        ep_range_str = ""

        # 根据媒体类型分别处理
        if item_type == "Episode":
            series_title = item.get("SeriesName")
            season_number = item.get("ParentIndexNumber")
            episode_number = item.get("IndexNumber")

            if not all([series_title, season_number is not None, episode_number is not None]):
                logger.warning("Webhook: 忽略一个剧集，因为缺少系列标题、季度或集数信息。")
                return

            logger.info(
                f"Emby Webhook: 解析到剧集 - 标题: '{series_title}', 类型: Episode, 季: {season_number}, 集: {episode_number}"
            )

            task_title = f"Webhook（emby）搜索: {series_title} - S{season_number:02d}E{episode_number:02d}"
            search_keyword = f"{series_title} S{season_number:02d}E{episode_number:02d}"
            media_type = "tv_series"
            anime_title = series_title

        elif item_type == "Movie":
            movie_title = item.get("Name")
            if not movie_title:
                logger.warning("Webhook: 忽略一个电影，因为缺少标题信息。")
                return

            logger.info(f"Emby Webhook: 解析到电影 - 标题: '{movie_title}', 类型: Movie")

            task_title = f"Webhook（emby）搜索: {movie_title}"
            search_keyword = movie_title
            media_type = "movie"
            season_number = 1
            episode_number = 1  # 电影按单集处理
            anime_title = movie_title

        else:  # Series
            # 优先采用上游聚合通知逻辑：从 Description 中解析季号和集数范围
            series_title = item.get("Name") or item.get("OriginalTitle") or item.get("SortName")
            if not series_title:
                logger.warning("Emby Webhook: Series 通知缺少标题，忽略。")
                return

            description = payload.get("Description", "") or ""
            season_number: Optional[int] = None

            # 解析 "S02 E01-E06" 格式
            season_match = re.search(r"S(\d+)", description, re.IGNORECASE)
            if season_match:
                season_number = int(season_match.group(1))

            ep_range_match = re.search(r"E(\d+)\s*-\s*E(\d+)", description, re.IGNORECASE)
            ep_single_match = re.search(r"E(\d+)", description, re.IGNORECASE)
            if ep_range_match:
                ep_start = int(ep_range_match.group(1))
                ep_end = int(ep_range_match.group(2))
                selected_episodes = list(range(ep_start, ep_end + 1))
                ep_range_str = f"E{ep_start:02d}-E{ep_end:02d}"
            elif ep_single_match:
                ep_start = int(ep_single_match.group(1))
                selected_episodes = [ep_start]
                ep_range_str = f"E{ep_start:02d}"

            # 兜底：若未能解析出季号，则回退到“按季探测后整季导入”
            if season_number is None:
                logger.warning(
                    f"Emby Webhook: Series 通知无法解析季号，回退为按季探测整季导入。Description='{description}'"
                )

                try:
                    search_results = await self.scraper_manager.search_all([series_title])
                except Exception as e:
                    logger.error(f"为整剧 '{series_title}' 探测季信息时搜索失败: {e}", exc_info=True)
                    search_results = []

                seasons_found = sorted(
                    {
                        r.season
                        for r in search_results
                        if r.type == "tv_series" and isinstance(r.season, int) and r.season > 0
                    }
                )
                if not seasons_found:
                    seasons_found = [1]
                    logger.info("未能从搜索结果推断季信息，回退为 S01。")
                else:
                    logger.info(f"为 '{series_title}' 检测到季列表: {seasons_found}")

                for s in seasons_found:
                    task_title = f"Webhook（emby）搜索: {series_title} - S{s:02d} 全季"
                    search_keyword = f"{series_title} S{s:02d}"
                    unique_key = f"webhook-search-{series_title}-S{s}-FULL"

                    task_payload = {
                        "animeTitle": series_title,
                        "mediaType": "tv_series",
                        "season": s,
                        "currentEpisodeIndex": None,
                        "year": year,
                        "searchKeyword": search_keyword,
                        "doubanId": str(douban_id) if douban_id else None,
                        "tmdbId": str(tmdb_id) if tmdb_id else None,
                        "imdbId": str(imdb_id) if imdb_id else None,
                        "tvdbId": str(tvdb_id) if tvdb_id else None,
                        "bangumiId": str(bangumi_id) if bangumi_id else None,
                        "selectedEpisodes": None,
                    }

                    await self.dispatch_task(
                        task_title=task_title,
                        unique_key=unique_key,
                        payload=task_payload,
                        webhook_source=webhook_source,
                    )
                return

            logger.info(
                f"Emby Webhook: 解析到聚合通知 - 标题: '{series_title}', 季: {season_number}, "
                f"集数范围: {ep_range_str or '未知'}, selectedEpisodes={selected_episodes}"
            )

            episode_number = None
            task_title = f"Webhook（emby）聚合搜索: {series_title} - S{season_number:02d} {ep_range_str}".strip()
            search_keyword = f"{series_title} S{season_number:02d}"
            media_type = "tv_series"
            anime_title = series_title

        # 统一：触发全网搜索任务，并附带元数据 ID
        ep_suffix = f"E{episode_number}" if episode_number is not None else (ep_range_str or "全季")
        unique_key = f"webhook-search-{anime_title}-S{season_number}-{ep_suffix}"

        logger.info(
            f"Webhook: 准备为 '{anime_title}' 创建全网搜索任务，并附加元数据ID "
            f"(TMDB: {tmdb_id}, IMDb: {imdb_id}, TVDB: {tvdb_id}, Douban: {douban_id})。"
        )

        task_payload = {
            "animeTitle": anime_title,
            "mediaType": media_type,
            "season": season_number,
            "currentEpisodeIndex": episode_number,
            "year": year,
            "searchKeyword": search_keyword,
            "doubanId": str(douban_id) if douban_id else None,
            "tmdbId": str(tmdb_id) if tmdb_id else None,
            "imdbId": str(imdb_id) if imdb_id else None,
            "tvdbId": str(tvdb_id) if tvdb_id else None,
            "bangumiId": str(bangumi_id) if bangumi_id else None,
            "selectedEpisodes": selected_episodes if item_type == "Series" else None,
        }

        await self.dispatch_task(
            task_title=task_title,
            unique_key=unique_key,
            payload=task_payload,
            webhook_source=webhook_source,
        )
