"""按季探测整部剧并逐季分发整季导入任务（fork 扩展，Emby 与 Jellyfin 共用）。

媒体服务器发来"整部剧"级别的事件（例如收藏一部剧）时，事件里没有季号。
这里在后台全网搜索这部剧，推断出有哪些季，再为每一季分发整季导入任务。

文件名以下划线开头：WebhookManager 自动发现处理器时会跳过它。
"""
import asyncio
import logging
import re
from typing import Any, Dict

from fastapi import HTTPException, status
from thefuzz import fuzz

from src.utils.filename_parser import normalize_title

logger = logging.getLogger(__name__)

# 持有后台季探测任务的引用，防止被垃圾回收
_background_tasks: set = set()


def _comparable_title(title: str) -> str:
    """去掉季度后缀、空格和全角冒号差异，用于判断搜索结果是否为同一部作品。"""
    return normalize_title(title or "").replace("：", ":").replace(" ", "").lower()


class SeasonProbeMixin:
    """与 BaseWebhook 一起使用：依赖 self.config_manager、self.scraper_manager、self.dispatch_task。"""

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

    async def _dispatch_by_season_probe(
        self, series_title: str, base_payload: Dict[str, Any], webhook_source: str, server_label: str
    ):
        """探测需要全网搜索：先按开关/过滤规则拦截，再放到后台执行，不阻塞媒体服务器的回调。"""
        if not await self._is_webhook_accepted(series_title):
            return

        task = asyncio.create_task(
            self._probe_seasons_and_dispatch(series_title, base_payload, webhook_source, server_label)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    async def _probe_seasons_and_dispatch(
        self, series_title: str, base_payload: Dict[str, Any], webhook_source: str, server_label: str
    ):
        """后台全网搜索整剧，推断季列表，并为每一季分发整季导入任务。"""
        prefix = f"Webhook（{server_label}）"
        try:
            try:
                search_results = await self.scraper_manager.search_all([series_title])
            except Exception as e:
                logger.error(f"{prefix}: 为整剧 '{series_title}' 探测季信息时搜索失败: {e}", exc_info=True)
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
                logger.info(f"{prefix}: 未能从搜索结果推断 '{series_title}' 的季信息，回退为 S01。")
            else:
                logger.info(f"{prefix}: 为 '{series_title}' 检测到季列表: {seasons_found}")

            for s in seasons_found:
                try:
                    await self.dispatch_task(
                        task_title=f"Webhook（{server_label}）搜索: {series_title} - S{s:02d} 全季",
                        unique_key=f"webhook-search-{series_title}-S{s}-全季",
                        payload={**base_payload, "season": s, "searchKeyword": f"{series_title} S{s:02d}"},
                        webhook_source=webhook_source,
                    )
                except HTTPException as e:
                    # 同一季的任务已在队列中（409）时跳过这一季，继续分发后面的季
                    if e.status_code != status.HTTP_409_CONFLICT:
                        raise
                    logger.info(f"{prefix}: '{series_title}' S{s:02d} 全季任务已在队列中，跳过。")
        except Exception as e:
            logger.error(f"{prefix}: 为 '{series_title}' 按季探测并分发任务失败: {e}", exc_info=True)
