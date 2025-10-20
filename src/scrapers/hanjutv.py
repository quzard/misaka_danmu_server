#!/usr/bin/env python3
"""
韩剧TV (HanjuTV) 弹幕搜索源
支持韩剧、综艺、电影、美剧的搜索和弹幕获取
"""

import asyncio
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
import httpx

from .. import models
from .base import BaseScraper, get_season_from_title
from ..config_manager import ConfigManager


class HanjuTVScraper(BaseScraper):
    """韩剧TV弹幕爬虫"""

    # 类属性：提供商名称（必须）
    provider_name = "hanjutv"

    # 处理的域名列表
    handled_domains = ["hanjutv.com", "www.hanjutv.com", "hxqapi.hiyun.tv"]

    # Referer
    referer = "https://hanjutv.com/"

    # 测试URL
    test_url = "https://hxqapi.hiyun.tv"

    # 速率限制配额（-1 表示无限制）
    rate_limit_quota = -1

    # 提供商特定的分集黑名单（正则表达式）
    _PROVIDER_SPECIFIC_BLACKLIST_DEFAULT = r"^(.*?)(预告|花絮|特辑|彩蛋|专访|幕后|直播|纯享|未播|衍生|番外|会员|片花|精华|看点|速看|解读|影评|解说|吐槽|盘点)(.*?)$"

    # 分类映射（映射为数据库接受的类型）
    CATEGORY_MAP = {
        1: "tv_series",  # 韩剧
        2: "tv_series",  # 综艺
        3: "movie",      # 电影
        5: "tv_series"   # 美剧
    }

    def build_media_url(self, media_id: str) -> Optional[str]:
        """构造韩剧TV播放页面URL"""
        return f"https://hanju.com/series/{media_id}"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager):
        super().__init__(session_factory, config_manager)
        self.display_name = "韩剧TV"
        self.base_url = "https://hxqapi.hiyun.tv"
        self.danmu_url = "https://hxqapi.zmdcq.com"
        self.logger = logging.getLogger(self.__class__.__name__)

        # HTTP 客户端（延迟初始化）
        self.client: Optional[httpx.AsyncClient] = None

        # API 速率限制
        self._api_lock = asyncio.Lock()
        self._last_request_time = 0.0
        self._min_interval = 0.3  # 最小请求间隔（秒）
    
    async def _ensure_client(self) -> httpx.AsyncClient:
        """
        确保 HTTP 客户端已初始化，支持代理

        Returns:
            httpx.AsyncClient: HTTP 客户端实例
        """
        # 检查代理配置是否发生变化
        current_proxy = await self._get_proxy_for_provider()
        if self.client is None or self._current_proxy_config != current_proxy:
            if self.client:
                await self.client.aclose()

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": self.referer,
            }
            self.client = await self._create_client(headers=headers)

        return self.client

    async def close(self):
        """关闭 HTTP 客户端"""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        发送 HTTP 请求（带速率限制）

        Args:
            method: HTTP 方法
            url: 请求 URL
            **kwargs: 其他请求参数

        Returns:
            httpx.Response: HTTP 响应
        """
        async with self._api_lock:
            # 速率限制
            now = time.time()
            dt = now - self._last_request_time
            if dt < self._min_interval:
                await asyncio.sleep(self._min_interval - dt)

            # 发送请求
            client = await self._ensure_client()
            response = await client.request(method, url, **kwargs)
            self._last_request_time = time.time()

            return response

    @staticmethod
    def convert_to_ascii_sum(sid: str) -> int:
        """
        djb2 哈希算法将 string 转成 id
        
        Args:
            sid: 剧集ID字符串
            
        Returns:
            int: 生成的唯一ID (至少5位数)
        """
        hash_value = 5381
        for char in sid:
            hash_value = ((hash_value * 33) ^ ord(char)) & 0xFFFFFFFF
        hash_value = hash_value % 9999999
        return hash_value if hash_value >= 10000 else hash_value + 10000
    
    @staticmethod
    def get_category(category_id: int) -> str:
        """
        获取分类名称（返回数据库接受的类型）

        Args:
            category_id: 分类ID

        Returns:
            str: 分类名称 ('tv_series', 'movie', 'ova', 'other')
        """
        return HanjuTVScraper.CATEGORY_MAP.get(category_id, "other")
    
    async def _search_raw(self, keyword: str) -> List[Dict[str, Any]]:
        """
        搜索剧集（内部方法，返回原始数据）

        Args:
            keyword: 搜索关键词

        Returns:
            List[Dict]: 搜索结果列表
        """
        try:
            url = f"{self.base_url}/wapi/search/aggregate/search"
            params = {
                "keyword": keyword,
                "scope": 101,
                "page": 1
            }

            response = await self._request("GET", url, params=params)
            response.raise_for_status()
            data = response.json()

            # 判断响应数据是否有效
            if not data or "seriesData" not in data or "seriesList" not in data["seriesData"]:
                self.logger.warning(f"[HanjuTV] 搜索返回数据无效: {keyword}")
                return []

            series_list = data["seriesData"]["seriesList"]
            self.logger.info(f"[HanjuTV] 搜索到 {len(series_list)} 个结果")

            # 为每个结果生成唯一 animeId
            results = []
            for anime in series_list:
                anime_id = self.convert_to_ascii_sum(anime["sid"])
                results.append({
                    **anime,
                    "animeId": anime_id
                })

            return results

        except Exception as e:
            self.logger.error(f"HanjuTV 搜索失败: {keyword}, 错误: {e}")
            return []
    
    async def get_detail(self, sid: str) -> Optional[Dict[str, Any]]:
        """
        获取剧集详情

        Args:
            sid: 剧集ID

        Returns:
            Optional[Dict]: 剧集详情，失败返回 None
        """
        try:
            url = f"{self.base_url}/wapi/series/series/detail"
            params = {"sid": sid}

            response = await self._request("GET", url, params=params)
            response.raise_for_status()
            data = response.json()

            if not data or "series" not in data:
                self.logger.warning(f"HanjuTV 获取详情失败: sid={sid}")
                return None

            return data["series"]

        except Exception as e:
            self.logger.error(f"HanjuTV 获取详情异常: sid={sid}, 错误: {e}")
            return None
    
    async def get_episodes_raw(self, sid: str) -> List[Dict[str, Any]]:
        """
        获取原始剧集列表

        Args:
            sid: 剧集ID

        Returns:
            List[Dict]: 剧集列表（按集数排序）
        """
        try:
            url = f"{self.base_url}/wapi/series/series/detail"
            params = {"sid": sid}

            response = await self._request("GET", url, params=params)
            response.raise_for_status()
            data = response.json()

            if not data or "episodes" not in data:
                self.logger.warning(f"HanjuTV 获取剧集列表失败: sid={sid}")
                return []

            episodes = data["episodes"]
            # 按 serialNo 排序
            sorted_episodes = sorted(episodes, key=lambda x: x.get("serialNo", 0))
            return sorted_episodes

        except Exception as e:
            self.logger.error(f"HanjuTV 获取剧集列表异常: sid={sid}, 错误: {e}")
            return []
    
    async def fetch_danmaku(self, pid: str, progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """
        获取弹幕（分页获取所有弹幕）

        Args:
            pid: 播放ID
            progress_callback: 进度回调函数

        Returns:
            List[Dict]: 原始弹幕列表
        """
        all_danmus = []
        from_axis = 0
        max_axis = 100000000

        try:
            if progress_callback:
                await progress_callback(5, "开始获取韩剧TV弹幕")

            while from_axis < max_axis:
                url = f"{self.danmu_url}/api/danmu/playItem/list"
                params = {
                    "fromAxis": from_axis,
                    "pid": pid,
                    "toAxis": max_axis
                }

                response = await self._request("GET", url, params=params)
                response.raise_for_status()
                data = response.json()

                # 拼接当前页的弹幕
                if data and "danmus" in data:
                    all_danmus.extend(data["danmus"])

                # 获取下一页的起始位置
                next_axis = data.get("nextAxis", max_axis)
                if next_axis >= max_axis:
                    break

                from_axis = next_axis

                # 更新进度
                if progress_callback:
                    progress = min(85, 5 + int(len(all_danmus) / 100))
                    await progress_callback(progress, f"已获取 {len(all_danmus)} 条弹幕")

            if progress_callback:
                await progress_callback(85, f"原始弹幕 {len(all_danmus)} 条，正在规范化")

            return all_danmus

        except Exception as e:
            self.logger.error(f"HanjuTV 弹幕获取异常: pid={pid}, 错误: {e}")
            return all_danmus  # 返回已收集的弹幕
    
    def format_danmaku(self, raw_danmus: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        格式化弹幕为标准格式

        Args:
            raw_danmus: 原始弹幕列表

        Returns:
            List[Dict]: 格式化后的弹幕列表

        标准格式：
        {
            "cid": str,  # 弹幕ID（字符串）
            "p": "timestamp,mode,size,color,[provider]",  # 弹幕参数
            "m": str,  # 弹幕内容
            "t": float  # 时间戳（秒，浮点数）
        }

        HanjuTV 原始格式：
        {
            "did": int,  # 弹幕ID
            "t": int,  # 时间戳（毫秒）
            "tp": int,  # 弹幕类型（1=滚动，5=顶部，4=底部）
            "sc": int,  # 颜色（十进制）
            "con": str  # 弹幕内容
        }
        """
        formatted = []
        for danmu in raw_danmus:
            try:
                # 提取字段
                did = danmu.get('did', 0)
                timestamp_ms = danmu.get('t', 0)
                mode = danmu.get('tp', 1)  # 弹幕类型
                color = danmu.get('sc', 16777215)  # 颜色（默认白色）
                content = danmu.get('con', '')

                # 转换时间戳（毫秒 -> 秒）
                timestamp = timestamp_ms / 1000.0

                # 构建标准格式
                # p 字段格式：timestamp,mode,size,color,[provider]
                # size 固定为 25（标准字体大小）
                p_string = f"{timestamp:.2f},{mode},25,{color},[{self.provider_name}]"

                formatted.append({
                    'cid': str(did),  # 转换为字符串
                    'p': p_string,
                    'm': content,
                    't': timestamp  # 保持浮点数
                })
            except (KeyError, ValueError, TypeError) as e:
                self.logger.warning(f"弹幕格式化失败: {danmu}, 错误: {e}")
                continue

        return formatted
    
    async def get_comments(self, pid: str, progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """
        获取并格式化弹幕（完整流程）

        Args:
            pid: 播放ID
            progress_callback: 进度回调函数

        Returns:
            List[Dict]: 格式化后的弹幕列表
        """
        # 1. 获取原始弹幕
        raw_danmus = await self.fetch_danmaku(pid, progress_callback)

        # 2. 格式化弹幕
        formatted_danmus = self.format_danmaku(raw_danmus)

        if progress_callback:
            await progress_callback(100, f"弹幕处理完成，共 {len(formatted_danmus)} 条")

        return formatted_danmus

    # ==================== BaseScraper 接口实现 ====================

    async def search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """
        搜索媒体（实现 BaseScraper 接口）

        Args:
            keyword: 搜索关键词
            episode_info: 剧集信息（可选）

        Returns:
            List[ProviderSearchInfo]: 搜索结果列表
        """
        # 检查缓存
        cache_key = f"search_{self.provider_name}_{keyword}"
        cached = await self._get_from_cache(cache_key)
        if cached is not None:
            return [models.ProviderSearchInfo.model_validate(item) for item in cached]

        # 执行搜索
        search_results = await self._search_raw(keyword)

        if not search_results:
            return []

        # 转换为 ProviderSearchInfo 格式
        provider_results = []
        for idx, anime in enumerate(search_results):
            # 获取详情以获取分类信息
            detail = await self.get_detail(anime["sid"])
            if not detail:
                continue

            # 获取剧集列表以获取集数
            episodes = await self.get_episodes_raw(anime["sid"])

            # 构建标题
            year = anime.get("updateTime")
            if year:
                try:
                    from datetime import datetime
                    # 尝试转换为整数
                    year_int = int(year)

                    # 判断是否是时间戳（毫秒级，13位数字）
                    if year_int > 10000000000:  # 毫秒级时间戳
                        # 转换为秒级时间戳
                        timestamp = year_int / 1000
                        year = datetime.fromtimestamp(timestamp).year
                    elif year_int > 1000000000:  # 秒级时间戳
                        year = datetime.fromtimestamp(year_int).year
                    else:  # 直接是年份
                        year = year_int
                except (ValueError, TypeError) as e:
                    # 如果不是纯数字，尝试解析 ISO 格式日期
                    try:
                        year_str = str(year) if not isinstance(year, str) else year
                        year = datetime.fromisoformat(year_str.replace('Z', '+00:00')).year
                    except Exception:
                        # 如果解析失败，设置为 None
                        year = None

            category = self.get_category(detail.get("category", 0))
            title = anime.get("name", "")

            provider_results.append(models.ProviderSearchInfo(
                provider=self.provider_name,
                mediaId=anime["sid"],
                title=title,
                type=category,
                season=get_season_from_title(title),
                year=year,
                imageUrl=anime.get("image", {}).get("thumb", ""),
                episodeCount=len(episodes),
                currentEpisodeIndex=episode_info.get("episode") if episode_info else None,
                url=self.build_media_url(anime["sid"])
            ))

        # 缓存结果
        if provider_results:
            await self._set_to_cache(
                cache_key,
                [r.model_dump() for r in provider_results],
                f"{self.provider_name}_search_cache_ttl",
                3600  # 默认1小时
            )

        return provider_results

    async def get_episodes(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        """
        获取剧集列表（实现 BaseScraper 接口）

        Args:
            media_id: 媒体ID (sid)
            target_episode_index: 目标集数索引（可选）
            db_media_type: 数据库媒体类型（可选）

        Returns:
            List[ProviderEpisodeInfo]: 剧集信息列表
        """
        # 检查缓存
        cache_key = f"episodes_{self.provider_name}_{media_id}"
        if target_episode_index is None and db_media_type is None:
            cached = await self._get_from_cache(cache_key)
            if cached is not None:
                return [models.ProviderEpisodeInfo.model_validate(e) for e in cached]

        # 获取剧集列表
        episodes = await self.get_episodes_raw(media_id)

        if not episodes:
            return []

        # 转换为 ProviderEpisodeInfo 格式
        provider_episodes = []
        for i, ep in enumerate(episodes):
            serial_no = ep.get('serialNo', i+1)  # 获取集数，如果没有则使用索引+1
            ep_title = ep.get("title", "").strip()
            if not ep_title:
                ep_title = f"第{serial_no}集"
            else:
                ep_title = f"第{serial_no}集：{ep_title}"

            pid = ep.get("pid", "")
            if not pid:
                continue

            provider_episodes.append(models.ProviderEpisodeInfo(
                provider=self.provider_name,
                episodeId=pid,
                title=ep_title,  # 修复：使用正确的字段名 title
                episodeIndex=serial_no,  # 修复：使用 serialNo 而不是索引
                url=f"https://hanjutv.com/play/{media_id}/{pid}"  # 修复：使用正确的字段名 url
            ))

        # 缓存结果
        if provider_episodes:
            await self._set_to_cache(
                cache_key,
                [e.model_dump() for e in provider_episodes],
                f"{self.provider_name}_episodes_cache_ttl",
                3600  # 默认1小时
            )

        return provider_episodes

    async def get_info_from_url(self, url: str) -> Optional[models.ProviderSearchInfo]:
        """
        从 HanjuTV URL 中提取作品信息

        Args:
            url: HanjuTV URL

        Returns:
            Optional[ProviderSearchInfo]: 作品信息，失败返回 None
        """
        # URL 格式: https://hanjutv.com/play/{sid} 或 /play/{sid}/{pid}
        match = re.search(r'/play/([^/]+)', url)
        if not match:
            self.logger.warning(f"HanjuTV: 无法从URL中解析出 sid: {url}")
            return None

        sid = match.group(1)

        try:
            # 获取详情
            detail = await self.get_detail(sid)
            if not detail:
                return None

            # 获取剧集列表
            episodes = await self.get_episodes_raw(sid)

            # 构建作品信息
            title = detail.get("name", "")
            year = detail.get("updateTime")
            if year:
                try:
                    from datetime import datetime
                    # 尝试转换为整数
                    year_int = int(year)

                    # 判断是否是时间戳（毫秒级，13位数字）
                    if year_int > 10000000000:  # 毫秒级时间戳
                        # 转换为秒级时间戳
                        timestamp = year_int / 1000
                        year = datetime.fromtimestamp(timestamp).year
                    elif year_int > 1000000000:  # 秒级时间戳
                        year = datetime.fromtimestamp(year_int).year
                    else:  # 直接是年份
                        year = year_int
                except (ValueError, TypeError):
                    # 如果不是纯数字，尝试解析 ISO 格式日期
                    try:
                        year_str = str(year) if not isinstance(year, str) else year
                        year = datetime.fromisoformat(year_str.replace('Z', '+00:00')).year
                    except Exception:
                        # 如果解析失败，设置为 None
                        year = None

            category = self.get_category(detail.get("category", 0))

            return models.ProviderSearchInfo(
                provider=self.provider_name,
                mediaId=sid,
                title=title,
                type=category,
                season=get_season_from_title(title),
                year=year,
                imageUrl=detail.get("image", {}).get("thumb", ""),
                episodeCount=len(episodes),
                url=self.build_media_url(sid)
            )

        except Exception as e:
            self.logger.error(f"HanjuTV: 从URL提取信息时发生错误 (sid={sid}): {e}", exc_info=True)
            return None

    async def get_id_from_url(self, url: str) -> Optional[str]:
        """
        从 HanjuTV URL 中提取分集ID (pid)

        Args:
            url: HanjuTV URL

        Returns:
            Optional[str]: 分集ID，失败返回 None
        """
        # URL 格式: https://hanjutv.com/play/{sid}/{pid}
        match = re.search(r'/play/[^/]+/([^/]+)', url)
        if match:
            return match.group(1)

        return None

    def format_episode_id_for_comments(self, provider_episode_id: Any) -> str:
        """
        格式化分集ID用于获取弹幕

        Args:
            provider_episode_id: 提供商分集ID

        Returns:
            str: 格式化后的分集ID
        """
        return str(provider_episode_id)

