"""Jellyfin 的 fork 扩展：用户手动标记已看、收藏或点赞时补弹幕，对应 emby.py 里的 item.markplayed / item.rate。

Jellyfin Webhook 插件（Generic 目的地）需要勾选 UserDataSaved 事件，以及 Episodes、Movies、Seasons、Series 条目类型；
建议再加请求头 Content-Type: application/json（插件默认发 text/plain，misaka 会对每个请求记一条警告）。

文件名以下划线开头：WebhookManager 自动发现处理器时会跳过它。
"""
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from ._season_probe import SeasonProbeMixin

logger = logging.getLogger(__name__)

# 同一集（或同一季、整部剧、电影）在这段时间内只触发一次
_TRIGGER_TTL_SECONDS = 3600
_recent_triggers: Dict[tuple, float] = {}


def _user_data_trigger(payload: Dict[str, Any]) -> Optional[str]:
    """UserDataSaved 里只有两种是用户主动操作：标记已看，以及收藏/点赞。播放进度、播放完成、导入等都忽略。

    - 对整季或整部剧标记已看时，Jellyfin 会为其中每一集各发一次 TogglePlayed。
    - 同一条目有多个版本时，Jellyfin 把已看同步给其他版本（Video.PropagatePlayedState）也用 TogglePlayed，
      但不改播放次数；手动标记已看则保证播放次数至少为 1。靠 PlayCount 区分两者。
    """
    reason = payload.get("SaveReason")
    if reason == "TogglePlayed":
        if str(payload.get("Played")).lower() != "true":
            return None
        try:
            play_count = int(payload.get("PlayCount") or 0)
        except (TypeError, ValueError):
            play_count = 0
        return "标记已看" if play_count >= 1 else None
    if reason == "UpdateUserRating" and "true" in (str(payload.get("Favorite")).lower(), str(payload.get("Likes")).lower()):
        return "收藏"
    return None


def _claim_trigger(payload: Dict[str, Any]) -> bool:
    """短时去重。重看多版本条目时，服务端每次进度上报都会给其他版本发 TogglePlayed；
    TaskManager 的 unique_key 只在任务运行期间去重，挡不住任务结束后的下一次。"""
    item_type = payload.get("ItemType")
    if item_type == "Series":
        key = (item_type, payload.get("ItemId"))
    else:
        key = (item_type, payload.get("SeriesName") or payload.get("Name"), payload.get("SeasonNumber"), payload.get("EpisodeNumber"))

    now = time.monotonic()
    for k, t in list(_recent_triggers.items()):
        if now - t >= _TRIGGER_TTL_SECONDS:
            del _recent_triggers[k]
    if key in _recent_triggers:
        return False
    _recent_triggers[key] = now
    return True


def _premiere_year(payload: Dict[str, Any]) -> Optional[int]:
    """与上游 jellyfin.py 相同：取 PremiereDate 的年份。"""
    if premiere_date_str := payload.get("PremiereDate"):
        try:
            return datetime.fromisoformat(premiere_date_str.replace("Z", "+00:00")).year
        except (ValueError, TypeError):
            logger.warning(f"Webhook: 无法从Jellyfin的PremiereDate '{premiere_date_str}' 解析年份。")
    return None


class JellyfinForkMixin(SeasonProbeMixin):
    async def _route_fork_event(self, payload: Dict[str, Any], event_type: Optional[str], webhook_source: str) -> Optional[str]:
        """在上游处理之前调用。返回交给上游处理的事件类型；返回 None 表示已在这里处理完。"""
        # 所在季目录没有编号时，插件发来的单集事件不带 SeasonNumber。
        # 有集号的按第 1 季处理，与 Jellyfin 给这些单集的 ParentIndexNumber 一致。
        if (
            event_type in ["ItemAdded", "UserDataSaved"]
            and payload.get("ItemType") == "Episode"
            and payload.get("SeasonNumber") is None
            and payload.get("EpisodeNumber") is not None
        ):
            logger.info(f"Jellyfin Webhook: '{payload.get('SeriesName')}' E{payload.get('EpisodeNumber')} 所在季没有编号，按第 1 季处理。")
            payload["SeasonNumber"] = 1

        if event_type != "UserDataSaved":
            return event_type

        trigger = _user_data_trigger(payload)
        if not trigger:
            # 播放进度每隔几秒就会触发一次，只记 debug
            logger.debug(f"Jellyfin Webhook: 忽略 UserDataSaved 事件 (SaveReason: {payload.get('SaveReason')})")
            return None

        item_type = payload.get("ItemType")
        if item_type not in ["Episode", "Movie", "Season", "Series"]:
            logger.info(f"Webhook: 忽略非 'Episode'、'Movie'、'Season' 或 'Series' 的媒体项 (类型: {item_type})")
            return None

        title = payload.get("SeriesName") or payload.get("Name")
        if not _claim_trigger(payload):
            logger.info(f"Jellyfin Webhook: {item_type} '{title}' 一小时内已触发过，忽略。")
            return None
        logger.info(f"Jellyfin Webhook: 用户{trigger}了 {item_type} '{title}'，触发弹幕搜索。")

        if item_type in ["Episode", "Movie"]:
            # 其余处理与新入库相同，交给上游流程
            return "ItemAdded"
        if item_type == "Season" and payload.get("SeasonNumber") is not None:
            await self._dispatch_jellyfin_season(payload, webhook_source)
        else:
            # 整部剧，或没有季号的季：后台探测季列表后逐季整季导入
            await self._dispatch_jellyfin_series(payload, webhook_source)
        return None

    def _jellyfin_base_payload(self, payload: Dict[str, Any], series_title: str, series_id: Any, season_id: Any) -> Dict[str, Any]:
        tmdb_id = payload.get("Provider_tmdb")
        imdb_id = payload.get("Provider_imdb")
        tvdb_id = payload.get("Provider_tvdb")
        douban_id = payload.get("Provider_doubanid")
        bangumi_id = payload.get("Provider_bangumi")
        return {
            "animeTitle": series_title,
            "mediaType": "tv_series",
            "currentEpisodeIndex": None,
            "year": _premiere_year(payload),
            "doubanId": str(douban_id) if douban_id else None,
            "tmdbId": str(tmdb_id) if tmdb_id else None,
            "imdbId": str(imdb_id) if imdb_id else None,
            "tvdbId": str(tvdb_id) if tvdb_id else None,
            "bangumiId": str(bangumi_id) if bangumi_id else None,
            "selectedEpisodes": None,
            "mediaServerType": "jellyfin",
            "mediaServerSeriesId": str(series_id) if series_id else None,
            "mediaServerSeasonId": str(season_id) if season_id else None,
            "mediaServerEpisodeId": None,
        }

    async def _dispatch_jellyfin_season(self, payload: Dict[str, Any], webhook_source: str):
        """整季：直接分发整季导入，季的 ItemId 作为 mediaServerSeasonId。"""
        series_title = payload.get("SeriesName")
        season = payload.get("SeasonNumber")
        if not series_title:
            logger.warning("Jellyfin Webhook: 整季的事件缺少系列标题，忽略。")
            return

        base_payload = self._jellyfin_base_payload(payload, series_title, payload.get("SeriesId"), payload.get("ItemId"))
        await self.dispatch_task(
            task_title=f"Webhook（jellyfin）搜索: {series_title} - S{season:02d} 全季",
            unique_key=f"webhook-search-{series_title}-S{season}-全季",
            payload={**base_payload, "season": season, "searchKeyword": f"{series_title} S{season:02d}"},
            webhook_source=webhook_source,
        )

    async def _dispatch_jellyfin_series(self, payload: Dict[str, Any], webhook_source: str):
        if payload.get("ItemType") == "Series":
            series_title, series_id = payload.get("Name"), payload.get("ItemId")
        else:
            series_title, series_id = payload.get("SeriesName"), payload.get("SeriesId")
        if not series_title:
            logger.warning("Jellyfin Webhook: 整部剧的事件缺少标题，忽略。")
            return

        base_payload = self._jellyfin_base_payload(payload, series_title, series_id, None)
        await self._dispatch_by_season_probe(series_title, base_payload, webhook_source, "jellyfin")
