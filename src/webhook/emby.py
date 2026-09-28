import asyncio
import logging
import re
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from thefuzz import fuzz

from src.utils.filename_parser import normalize_title
from .base import BaseWebhook

logger = logging.getLogger(__name__)

# 持有后台季探测任务的引用，防止被垃圾回收
_background_tasks: set = set()


def _comparable_title(title: str) -> str:
    """去掉季度后缀、空格和全角冒号差异，用于判断搜索结果是否为同一部作品。"""
    return normalize_title(title or "").replace("：", ":").replace(" ", "").lower()


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

        # 处理删除事件
        if event_type == "library.deleted":
            await self._handle_delete(payload, webhook_source)
            return

        # 兼容本地扩展事件：评分/标记已看
        if event_type not in ["library.new", "item.rate", "item.markplayed"]:
            logger.info(
                f"Webhook: 忽略非 'library.new' / 'item.rate' / 'item.markplayed' / 'library.deleted' 事件 (类型: {event_type})"
            )
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
        emby_item_id = str(item.get("Id", "")) if item.get("Id") else None
        emby_series_id = str(item.get("SeriesId", "")) if item.get("SeriesId") else None
        emby_season_id = str(item.get("SeasonId", "")) if item.get("SeasonId") else None

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

                # 探测需要全网搜索：先按开关/过滤规则拦截，再放到后台执行，不阻塞 Emby 回调
                if not await self._is_webhook_accepted(series_title):
                    return

                base_payload = {
                    "animeTitle": series_title,
                    "mediaType": "tv_series",
                    "currentEpisodeIndex": None,
                    "year": year,
                    "doubanId": str(douban_id) if douban_id else None,
                    "tmdbId": str(tmdb_id) if tmdb_id else None,
                    "imdbId": str(imdb_id) if imdb_id else None,
                    "tvdbId": str(tvdb_id) if tvdb_id else None,
                    "bangumiId": str(bangumi_id) if bangumi_id else None,
                    "selectedEpisodes": None,
                    "mediaServerType": "emby",
                    "mediaServerSeriesId": emby_series_id or emby_item_id,
                    "mediaServerSeasonId": emby_season_id,
                    "mediaServerEpisodeId": None,
                }
                task = asyncio.create_task(
                    self._probe_seasons_and_dispatch(series_title, base_payload, webhook_source)
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
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
            # 媒体服务三级 ID
            "mediaServerType": "emby",
            # Episode → SeriesId; Movie → Item.Id 自身; Series → Item.Id 自身
            "mediaServerSeriesId": emby_series_id or emby_item_id,
            "mediaServerSeasonId": emby_season_id,
            # Episode → Item.Id; Movie → Item.Id（电影按单集处理）; Series → None
            "mediaServerEpisodeId": emby_item_id if item_type in ("Episode", "Movie") else None,
        }

        await self.dispatch_task(
            task_title=task_title,
            unique_key=unique_key,
            payload=task_payload,
            webhook_source=webhook_source,
        )

    async def _is_webhook_accepted(self, anime_title: str) -> bool:
        """与 BaseWebhook.dispatch_task 相同的开关/过滤判断，用于在耗时的季探测前提前拦截。"""
        if (await self.config_manager.get("webhookEnabled", "true")).lower() != "true":
            self.logger.info("Webhook 功能已全局禁用，忽略请求。")
            return False

        filter_regex_str = await self.config_manager.get("webhookFilterRegex", "")
        if not filter_regex_str:
            return True
        filter_mode = await self.config_manager.get("webhookFilterMode", "blacklist")
        try:
            matched = re.search(filter_regex_str, anime_title, re.IGNORECASE) is not None
        except re.error:
            return True  # 无效正则由 dispatch_task 记录并忽略
        if (filter_mode == "blacklist" and matched) or (filter_mode == "whitelist" and not matched):
            self.logger.info(f"Webhook 请求 '{anime_title}' 因匹配过滤规则而被忽略。")
            return False
        return True

    async def _probe_seasons_and_dispatch(self, series_title: str, base_payload: Dict[str, Any], webhook_source: str):
        """后台全网搜索整剧，推断季列表，并为每一季分发整季导入任务。"""
        try:
            try:
                search_results = await self.scraper_manager.search_all([series_title])
            except Exception as e:
                logger.error(f"为整剧 '{series_title}' 探测季信息时搜索失败: {e}", exc_info=True)
                search_results = []

            # 只采信标题与本剧一致的结果，避免把同名前缀的其他作品的季数算进来
            target = _comparable_title(series_title)
            seasons_found = sorted(
                {
                    r.season
                    for r in search_results
                    if r.type == "tv_series"
                    and isinstance(r.season, int)
                    and r.season > 0
                    and fuzz.ratio(_comparable_title(r.title), target) >= 90
                }
            )
            if not seasons_found:
                seasons_found = [1]
                logger.info(f"未能从搜索结果推断 '{series_title}' 的季信息，回退为 S01。")
            else:
                logger.info(f"为 '{series_title}' 检测到季列表: {seasons_found}")

            for s in seasons_found:
                await self.dispatch_task(
                    task_title=f"Webhook（emby）搜索: {series_title} - S{s:02d} 全季",
                    unique_key=f"webhook-search-{series_title}-S{s}-全季",
                    payload={**base_payload, "season": s, "searchKeyword": f"{series_title} S{s:02d}"},
                    webhook_source=webhook_source,
                )
        except Exception as e:
            logger.error(f"Emby Webhook: 为 '{series_title}' 按季探测并分发任务失败: {e}", exc_info=True)

    async def _handle_delete(self, payload: dict, webhook_source: str):
        """处理 Emby library.deleted 事件，联动删除弹幕数据。"""
        from src.tasks.webhook_delete import handle_webhook_delete

        item = payload.get("Item", {})
        if not item:
            logger.info("Emby Webhook 删除: 负载中缺少 'Item' 信息，忽略。")
            return

        item_type = item.get("Type")
        if item_type not in ["Episode", "Season", "Series", "Movie"]:
            logger.info(f"Emby Webhook 删除: 忽略非 Episode/Season/Series/Movie 类型 (类型: {item_type})")
            return

        item_id = str(item.get("Id", ""))
        series_id = str(item.get("SeriesId", "")) if item.get("SeriesId") else None
        season_id = str(item.get("SeasonId", "")) if item.get("SeasonId") else None
        season_number = item.get("ParentIndexNumber") if item_type == "Season" else None
        title = item.get("SeriesName") or item.get("Name") or item_id

        logger.info(f"Emby Webhook 删除: 收到 {item_type} 删除事件 - '{title}' (ItemId={item_id})")

        async with self._session_factory() as session:
            await handle_webhook_delete(
                session=session,
                config_manager=self.config_manager,
                server_type="emby",
                item_type=item_type,
                item_id=item_id,
                series_id=series_id,
                season_id=season_id,
                season_number=season_number,
                title=title,
            )
