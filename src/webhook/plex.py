import logging
import json
from typing import Any, Dict
from fastapi import Request, HTTPException, status

from .base import BaseWebhook

logger = logging.getLogger(__name__)

class PlexWebhook(BaseWebhook):
    async def handle(self, request: Request, webhook_source: str):
        # 记录收到webhook请求
        self.logger.info(f"Plex Webhook: 收到请求")
        self.logger.info(f"Headers: {dict(request.headers)}")

        content_type = request.headers.get("content-type", "")

        # 根据Content-Type判断请求格式
        if "multipart/form-data" in content_type:
            # Plex原生webhook - multipart/form-data格式
            self.logger.info("检测到Plex原生webhook格式 (multipart/form-data)")
            try:
                form_data = await request.form()
                payload = dict(form_data)
                self.logger.info(f"Plex原生Webhook表单数据: {payload}")
                await self._handle_plex_native(payload, webhook_source)
            except Exception as e:
                self.logger.error(f"Plex原生Webhook: 无法解析multipart/form-data: {e}")
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无法解析multipart/form-data")

        elif "application/json" in content_type:
            # Tautulli webhook - JSON格式
            self.logger.info("检测到Tautulli webhook格式 (application/json)")
            try:
                payload = await request.json()
                self.logger.info(f"Tautulli Webhook JSON数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")

                if self._is_tautulli_webhook(payload):
                    await self._handle_tautulli(payload, webhook_source)
                else:
                    self.logger.warning("JSON格式但不是有效的Tautulli webhook格式")
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的Tautulli webhook格式")
            except json.JSONDecodeError as e:
                self.logger.error(f"Tautulli Webhook: 无法解析JSON: {e}")
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无法解析JSON")
        else:
            self.logger.warning(f"未知的Content-Type: {content_type}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的Content-Type")

    def _is_tautulli_webhook(self, payload: Dict) -> bool:
        """检测是否为Tautulli webhook格式"""
        # Tautulli webhook特征：包含media_type、title、season、episode字段
        tautulli_fields = {"media_type", "title", "season", "episode"}
        return tautulli_fields.issubset(payload.keys())

    async def _handle_plex_native(self, payload: Dict, webhook_source: str):
        """处理Plex原生webhook - multipart/form-data格式"""
        # Plex原生webhook发送multipart/form-data格式
        # payload实际上是表单数据，JSON在payload字段中

        # 从表单数据中提取JSON payload
        json_payload_str = payload.get("payload")
        if not json_payload_str:
            self.logger.warning("Plex原生Webhook: 表单数据中缺少 'payload' 字段")
            return

        try:
            json_payload = json.loads(json_payload_str)
        except json.JSONDecodeError as e:
            self.logger.error(f"Plex原生Webhook: 无法解析payload JSON: {e}")
            return

        # 检查事件类型
        event = json_payload.get("event")
        if event != "library.new":
            self.logger.info(f"Plex原生Webhook: 忽略非 'library.new' 事件 (事件类型: {event})")
            return

        # 获取媒体信息
        metadata = json_payload.get("Metadata", {})
        if not metadata:
            self.logger.warning("Plex原生Webhook: 负载中缺少 'Metadata' 信息")
            return

        # 获取媒体类型并映射
        raw_media_type = metadata.get("type")

        # Plex原生类型映射：show -> episode, movie -> movie
        if raw_media_type == "show":
            media_type = "episode"
        elif raw_media_type == "movie":
            media_type = "movie"
        else:
            self.logger.info(f"Plex原生Webhook: 忽略不支持的媒体类型 (原始类型: {raw_media_type})")
            return

        # 获取用户信息
        account = json_payload.get("Account", {})
        user_name = account.get("title", "Unknown")

        if media_type == "episode":
            # 处理剧集
            series_title = metadata.get("grandparentTitle", "")
            season_number = metadata.get("parentIndex", 1)
            episode_number = metadata.get("index", 1)
            
            if not series_title:
                self.logger.warning("Plex原生Webhook: 剧集缺少系列标题")
                return

            self.logger.info(f"Plex原生Webhook: 处理剧集 - {series_title} S{season_number:02d}E{episode_number:02d}")

            # 提取Provider IDs
            guid_list = metadata.get("Guid", [])
            provider_ids = self._extract_provider_ids(guid_list)

            await self.dispatch_task(
                task_title=f"{series_title} S{season_number:02d}E{episode_number:02d}",
                unique_key=f"plex_episode_{series_title}_{season_number}_{episode_number}_{user_name}",
                payload={
                    "animeTitle": series_title,
                    "season": season_number,
                    "episode": episode_number,
                    "tmdbId": provider_ids.get("tmdb"),
                    "imdbId": provider_ids.get("imdb"),
                    "tvdbId": provider_ids.get("tvdb"),
                    "doubanId": provider_ids.get("douban"),
                    "bangumiId": provider_ids.get("bangumi"),
                    "userName": user_name,
                    "mediaType": "episode"
                },
                webhook_source=webhook_source
            )

        elif media_type == "movie":
            # 处理电影
            movie_title = metadata.get("title", "")
            year = metadata.get("year")
            
            if not movie_title:
                self.logger.warning("Plex原生Webhook: 电影缺少标题")
                return

            self.logger.info(f"Plex原生Webhook: 处理电影 - {movie_title} ({year})")

            # 提取Provider IDs
            guid_list = metadata.get("Guid", [])
            provider_ids = self._extract_provider_ids(guid_list)

            await self.dispatch_task(
                task_title=f"{movie_title} ({year})" if year else movie_title,
                unique_key=f"plex_movie_{movie_title}_{year}_{user_name}",
                payload={
                    "animeTitle": movie_title,
                    "year": year,
                    "tmdbId": provider_ids.get("tmdb"),
                    "imdbId": provider_ids.get("imdb"),
                    "tvdbId": provider_ids.get("tvdb"),
                    "doubanId": provider_ids.get("douban"),
                    "bangumiId": provider_ids.get("bangumi"),
                    "userName": user_name,
                    "mediaType": "movie"
                },
                webhook_source=webhook_source
            )

    async def _handle_tautulli(self, payload: Dict, webhook_source: str):
        """处理Tautulli webhook"""
        # 注意：Tautulli webhook需要配置为只在library.new事件时触发
        # 这里不检查事件类型，因为Tautulli的自定义模板中没有事件字段
        # 用户需要在Tautulli中配置触发条件为"Recently Added"

        # 获取媒体类型
        media_type = payload.get("media_type", "").lower()
        if media_type not in ["episode", "movie"]:
            self.logger.info(f"Tautulli Webhook: 忽略非 'episode' 或 'movie' 的媒体项 (类型: {media_type})")
            return

        # 获取基本信息
        title = payload.get("title", "")
        ori_title = payload.get("ori_title", "")
        user_name = payload.get("user_name", "Unknown")

        if not title:
            self.logger.warning("Tautulli Webhook: 缺少标题信息")
            return

        if media_type == "episode":
            # 处理剧集
            season = payload.get("season", 1)
            episode = payload.get("episode", 1)
            
            self.logger.info(f"Tautulli Webhook: 处理剧集 - {title} S{season:02d}E{episode:02d}")

            await self.dispatch_task(
                task_title=f"{title} S{season:02d}E{episode:02d}",
                unique_key=f"tautulli_episode_{title}_{season}_{episode}_{user_name}",
                payload={
                    "animeTitle": title,
                    "originalTitle": ori_title,
                    "season": season,
                    "episode": episode,
                    "userName": user_name,
                    "mediaType": "episode"
                },
                webhook_source=webhook_source
            )

        elif media_type == "movie":
            # 处理电影
            release_date = payload.get("release_date", "")
            year = None
            if release_date:
                try:
                    year = int(release_date.split("-")[0])
                except (ValueError, IndexError):
                    pass
            
            self.logger.info(f"Tautulli Webhook: 处理电影 - {title} ({year})")

            await self.dispatch_task(
                task_title=f"{title} ({year})" if year else title,
                unique_key=f"tautulli_movie_{title}_{year}_{user_name}",
                payload={
                    "animeTitle": title,
                    "originalTitle": ori_title,
                    "year": year,
                    "userName": user_name,
                    "mediaType": "movie"
                },
                webhook_source=webhook_source
            )

    def _extract_provider_ids(self, guid_list: list) -> Dict[str, str]:
        """从Plex的Guid列表中提取各种provider ID"""
        provider_ids = {}
        
        for guid_item in guid_list:
            guid_id = guid_item.get("id", "")
            
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
