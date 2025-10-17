import asyncio
import hashlib
import json
import logging
import re
import time
import math
from typing import Any, Dict, List, Optional, Callable, Union
from urllib.parse import urlencode, quote
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..config_manager import ConfigManager
from .. import models
from ..utils import parse_search_keyword
from .base import BaseScraper, get_season_from_title

scraper_responses_logger = logging.getLogger("scraper_responses")

# --- Pydantic Models for Sohu API ---

class SohuComment(BaseModel):
    """搜狐弹幕单条数据模型"""
    v: float = Field(..., description="弹幕时间(秒)")
    c: str = Field(..., description="弹幕内容")
    t: Optional[Dict[str, Any]] = Field(None, description="弹幕样式信息")
    created: Optional[float] = Field(None, description="创建时间戳")
    uid: Optional[str] = Field(None, description="用户ID")
    i: Optional[str] = Field(None, description="弹幕ID")

class SohuDanmuInfo(BaseModel):
    """搜狐弹幕响应信息"""
    comments: List[SohuComment] = Field(default_factory=list)

class SohuDanmuResponse(BaseModel):
    """搜狐弹幕API响应模型"""
    info: Optional[SohuDanmuInfo] = None

class SohuVideo(BaseModel):
    """搜狐视频信息"""
    vid: Union[str, int] = Field(..., description="视频ID")
    video_name: Optional[str] = Field(None, description="视频标题")
    video_order: Optional[int] = Field(None, description="集数序号")
    url_html5: Optional[str] = Field(None, description="移动端URL")
    isFee: int = Field(0, description="是否付费 0=免费 1=会员")

class SohuPlaylistResponse(BaseModel):
    """搜狐播放列表API响应"""
    videos: List[SohuVideo] = Field(default_factory=list)

class SohuSearchVideoInfo(BaseModel):
    """搜狐搜索结果中的视频信息"""
    aid: Optional[int] = None
    kisId: Optional[int] = None
    album_name: Optional[str] = None
    year: Optional[int] = None
    director: Optional[str] = None
    main_actor: Optional[str] = None
    area: Optional[str] = None
    score: Optional[float] = None
    total_video_count: Optional[int] = None
    latest_video_count: Optional[int] = None
    videos: List[SohuVideo] = Field(default_factory=list)

class SohuSearchItem(BaseModel):
    """搜狐搜索结果项"""
    data_type: Optional[int] = None  # 有些item没有这个字段
    aid: Optional[int] = None
    kisId: Optional[int] = None
    album_name: Optional[str] = None
    year: Optional[int] = None
    director: Optional[str] = None
    main_actor: Optional[str] = None
    area: Optional[str] = None
    score: Optional[float] = None
    total_video_count: Optional[int] = None
    latest_video_count: Optional[int] = None
    videos: List[SohuVideo] = Field(default_factory=list)
    # 单个视频字段
    vid: Optional[Union[str, int]] = None
    video_name: Optional[str] = None
    # 类型相关字段
    category_name: Optional[str] = None  # 分类名称，如"电影"、"电视剧"、"动漫"、"综艺"

class SohuSearchData(BaseModel):
    """搜狐搜索响应数据"""
    items: List[SohuSearchItem] = Field(default_factory=list)

class SohuSearchResult(BaseModel):
    """搜狐搜索API响应"""
    status: int
    data: Optional[SohuSearchData] = None

class SohuScraper(BaseScraper):
    """搜狐视频弹幕获取器"""

    provider_name = "sohu"
    provider_display_name = "搜狐视频"
    handled_domains = ["tv.sohu.com", "m.tv.sohu.com", "so.tv.sohu.com"]
    referer = "https://tv.sohu.com/"
    test_url = "https://tv.sohu.com"

    # 位置映射：搜狐 -> B站格式
    POSITION_MAP = {
        1: 1,  # 滚动弹幕
        4: 5,  # 顶部弹幕
        5: 4,  # 底部弹幕
    }
    
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager):
        super().__init__(session_factory, config_manager)
        self.base_url = "https://tv.sohu.com"
        self.danmu_api_url = "https://api.danmu.tv.sohu.com/dmh5/dmListAll"
        self.search_api_url = "https://m.so.tv.sohu.com/search/pc/keyword"
        self.playlist_api_url = "https://pl.hd.sohu.com/videolist"
        self.api_key = "f351515304020cad28c92f70f002261c"
    
    async def search(
        self,
        keyword: str,
        episode_info: Optional[Dict[str, Any]] = None
    ) -> List[models.ProviderSearchInfo]:
        """
        搜索搜狐视频内容

        Args:
            keyword: 搜索关键词
            episode_info: 分集信息（可选）

        Returns:
            搜索结果列表
        """
        try:
            self.logger.info(f"开始搜索: {keyword}")

            # 构造搜索URL
            params = {
                'key': keyword,
                'type': '1',
                'page': '1',
                'page_size': '20',
                'user_id': '',
                'tabsChosen': '0',
                'poster': '4',
                'tuple': '6',
                'extSource': '1',
                'show_star_detail': '3',
                'pay': '1',
                'hl': '3',
                'uid': str(int(time.time() * 1000)),
                'passport': '',
                'plat': '-1',
                'ssl': '0'
            }

            # 设置请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://so.tv.sohu.com/',
                'Origin': 'https://so.tv.sohu.com'
            }

            # 发送请求
            async with await self._create_client() as client:
                response = await client.get(
                    self.search_api_url,
                    params=params,
                    headers=headers
                )
                
                if await self._should_log_responses():
                    scraper_responses_logger.debug(f"Sohu Search Response: {response.text}")
                
                response.raise_for_status()

            # 解析响应
            try:
                search_result = SohuSearchResult.model_validate(response.json())
            except (json.JSONDecodeError, ValidationError) as e:
                self.logger.error(f"搜狐: 解析搜索响应失败: {e}")
                return []

            if not search_result.data or not search_result.data.items:
                self.logger.info(f"搜狐视频: 搜索 '{keyword}' 未找到结果。")
                return []

            # 处理搜索结果
            results: List[models.ProviderSearchInfo] = []
            for item in search_result.data.items:
                # 只处理剧集类型 (data_type=257)
                if item.data_type != 257:
                    continue
                
                if not item.aid or not item.album_name:
                    continue

                # 清理标题中的高亮标记
                title = item.album_name.replace('<<<', '').replace('>>>', '')

                # 提取季度信息
                season = get_season_from_title(title)

                # 映射类型
                media_type = self._map_category_to_type(item.category_name)

                # 过滤掉不支持的类型
                if media_type is None:
                    self.logger.debug(f"搜狐视频: 过滤不支持的类型 '{item.category_name}': {title}")
                    continue

                results.append(models.ProviderSearchInfo(
                    provider=self.provider_name,
                    mediaId=str(item.aid),
                    title=title,
                    type=media_type,
                    year=item.year,
                    season=season,
                    episodeCount=item.total_video_count or 0
                ))

            self.logger.info(f"搜狐视频: 网络搜索 '{keyword}' 完成，找到 {len(results)} 个结果。")
            return results

        except httpx.HTTPError as e:
            self.logger.error(f"搜狐视频: 搜索请求失败: {e}")
            return []
        except Exception as e:
            self.logger.error(f"搜狐视频: 搜索时发生未知错误: {e}", exc_info=True)
            return []
    
    async def get_episodes(
        self,
        media_id: str,
        db_media_type: str = "anime",
        season: int = 1
    ) -> List[models.ProviderEpisodeInfo]:
        """
        获取指定媒体的分集列表

        Args:
            media_id: 媒体ID (aid)
            db_media_type: 媒体类型
            season: 季度

        Returns:
            分集信息列表
        """
        try:
            self.logger.info(f"开始获取分集列表: media_id={media_id}")

            # 构造播放列表API URL
            params = {
                'playlistid': media_id,
                'api_key': self.api_key
            }

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://tv.sohu.com/'
            }

            # 发送请求
            async with await self._create_client() as client:
                response = await client.get(
                    self.playlist_api_url,
                    params=params,
                    headers=headers,
                    timeout=15.0
                )

                if await self._should_log_responses():
                    scraper_responses_logger.debug(f"Sohu Playlist Response (media_id={media_id}): {response.text}")

                response.raise_for_status()

            # 解析JSONP响应
            text = response.text
            if text.startswith('jsonp'):
                # 提取括号内的JSON
                start = text.find('(') + 1
                end = text.rfind(')')
                if start > 0 and end > start:
                    json_str = text[start:end]
                    data = json.loads(json_str)
                else:
                    self.logger.error(f"搜狐视频: 无法解析JSONP响应")
                    return []
            else:
                data = json.loads(text)

            # 提取视频列表
            videos = data.get('videos', [])
            if not videos:
                self.logger.warning(f"搜狐视频: 未找到分集列表 (media_id={media_id})")
                return []

            # 转换为标准格式
            episodes: List[models.ProviderEpisodeInfo] = []
            for i, video in enumerate(videos):
                vid = video.get('vid', '')
                title = video.get('name', f'第{i+1}集')
                url = video.get('pageUrl', '')

                # 转换为HTTPS
                if url.startswith('http://'):
                    url = url.replace('http://', 'https://')

                episode = models.ProviderEpisodeInfo(
                    provider=self.provider_name,
                    episodeId=str(vid),
                    episodeIndex=i + 1,
                    title=title,
                    url=url
                )
                episodes.append(episode)

            self.logger.info(f"搜狐视频: 成功获取 {len(episodes)} 个分集 (media_id={media_id})")
            return episodes

        except httpx.HTTPError as e:
            self.logger.error(f"搜狐视频: 获取分集列表失败: {e}")
            return []
        except Exception as e:
            self.logger.error(f"搜狐视频: 获取分集列表时发生未知错误: {e}", exc_info=True)
            return []

    async def get_comments(
        self,
        episode_id: str,
        progress_callback: Optional[Callable] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        获取指定分集的弹幕

        Args:
            episode_id: 分集ID (vid)
            progress_callback: 进度回调函数

        Returns:
            弹幕列表，格式为 [{'cid': '', 'p': '时间,类型,字号,颜色,[来源]', 'm': '弹幕内容', 't': 时间}, ...]
        """
        try:
            self.logger.info(f"开始获取弹幕: episode_id={episode_id}")

            if progress_callback:
                await progress_callback(10, "正在获取弹幕...")

            # 获取视频时长（用于确定需要获取多少段弹幕）
            # 默认最大7200秒（2小时）
            max_time = 7200

            # 分段获取弹幕（60秒一段）
            all_comments: List[SohuComment] = []
            segment_duration = 60
            total_segments = max_time // segment_duration

            for i, start in enumerate(range(0, max_time, segment_duration)):
                end = start + segment_duration
                comments = await self._get_danmu_segment(episode_id, '0', start, end)

                if comments:
                    all_comments.extend(comments)
                    self.logger.debug(f"获取第 {start//60+1} 分钟: {len(comments)} 条弹幕")
                elif start > 600:  # 10分钟后无数据可能到末尾
                    break

                # 更新进度
                if progress_callback:
                    progress = 10 + int((i + 1) / total_segments * 70)
                    await progress_callback(progress, f"已获取 {i + 1}/{total_segments} 个时间段")

                # 避免请求过快
                await asyncio.sleep(0.1)

            if not all_comments:
                self.logger.info(f"搜狐视频: 未找到弹幕 (episode_id={episode_id})")
                return []

            if progress_callback:
                await progress_callback(85, "正在格式化弹幕...")

            # 转换为标准格式
            formatted_comments: List[Dict[str, Any]] = []
            for comment in all_comments:
                try:
                    # 解析颜色
                    color = self._parse_color(comment)

                    # 解析位置（默认滚动弹幕）
                    position = 1

                    # 时间（秒）
                    time_val = float(comment.v)

                    # 构造p属性：时间,模式,字体大小,颜色,[来源]
                    p_string = f"{time_val:.2f},{position},25,{color},[{self.provider_name}]"

                    formatted_comments.append({
                        'cid': comment.i or '',
                        'p': p_string,
                        'm': comment.c,
                        't': round(time_val, 2)
                    })

                except Exception as e:
                    self.logger.warning(f"格式化弹幕失败: {e}, 弹幕数据: {comment}")
                    continue

            if progress_callback:
                await progress_callback(100, f"获取完成，共 {len(formatted_comments)} 条弹幕")

            self.logger.info(f"搜狐视频: 成功获取 {len(formatted_comments)} 条弹幕 (episode_id={episode_id})")
            return formatted_comments

        except Exception as e:
            self.logger.error(f"搜狐视频: 获取弹幕时发生错误: {e}", exc_info=True)
            return None

    async def _get_danmu_segment(
        self,
        vid: str,
        aid: str,
        start: int,
        end: int
    ) -> List[SohuComment]:
        """
        获取单个时间段的弹幕数据

        Args:
            vid: 视频ID
            aid: 专辑ID
            start: 开始时间（秒）
            end: 结束时间（秒）

        Returns:
            弹幕列表
        """
        try:
            params = {
                'act': 'dmlist_v2',
                'vid': vid,
                'aid': aid,
                'pct': '2',
                'time_begin': str(start),
                'time_end': str(end),
                'dct': '1',
                'request_from': 'h5_js'
            }

            async with await self._create_client() as client:
                response = await client.get(
                    self.danmu_api_url,
                    params=params,
                    timeout=10.0
                )

                response.raise_for_status()

            # 解析响应
            try:
                danmu_result = SohuDanmuResponse.model_validate(response.json())
                if danmu_result.info and danmu_result.info.comments:
                    return danmu_result.info.comments
            except (json.JSONDecodeError, ValidationError) as e:
                self.logger.error(f"搜狐视频: 解析弹幕响应失败: {e}")

            return []

        except httpx.HTTPError as e:
            self.logger.debug(f"搜狐视频: 获取弹幕段失败 (vid={vid}, {start}-{end}s): {e}")
            return []
        except Exception as e:
            self.logger.error(f"搜狐视频: 获取弹幕段时发生错误: {e}")
            return []

    def _parse_color(self, comment: SohuComment) -> int:
        """
        解析弹幕颜色值

        Args:
            comment: 弹幕对象

        Returns:
            颜色值（整数）
        """
        try:
            if comment.t and 'c' in comment.t:
                color = comment.t['c']

                # 处理十六进制颜色
                if isinstance(color, str) and color.startswith('#'):
                    return int(color[1:], 16)

                # 处理数字字符串
                if isinstance(color, str):
                    return int(color, 16) if not color.isdigit() else int(color)

                # 处理整数
                return int(color)
        except (ValueError, KeyError, TypeError):
            pass

        # 默认白色
        return 16777215

    async def _should_log_responses(self) -> bool:
        """检查是否应该记录原始响应"""
        debug_enabled = await self.config_manager.get("debugEnabled", "false")
        return debug_enabled.lower() == "true"

    def _map_category_to_type(self, category_name: Optional[str]) -> Optional[str]:
        """
        将搜狐视频的分类名称映射到标准类型

        Args:
            category_name: 分类名称，如"电影"、"电视剧"、"动漫"、"综艺"、"纪录片"

        Returns:
            标准类型: 'movie' 或 'tv_series'，如果不是支持的类型则返回None
        """
        if not category_name:
            return None  # 没有分类信息，过滤掉

        category_lower = category_name.lower()

        # 电影类型
        if '电影' in category_lower or 'movie' in category_lower:
            return 'movie'

        # 电视剧、动漫、综艺、纪录片等映射为tv_series
        if any(keyword in category_lower for keyword in ['电视剧', '动漫', '综艺', '纪录片', 'tv', 'anime', 'variety']):
            return 'tv_series'

        # 其他类型不支持，返回None进行过滤
        return None

    async def get_info_from_url(self, url: str) -> Optional[models.ProviderSearchInfo]:
        """
        从搜狐视频URL中提取作品信息

        Args:
            url: 搜狐视频作品URL

        Returns:
            作品信息，如果解析失败则返回None
        """
        try:
            # 从URL中提取aid
            # 支持的URL格式:
            # https://tv.sohu.com/s2017/fyqm2zqdf/
            # http://tv.sohu.com/item/MTI4NzY5Mw==.html

            # 尝试从详情页URL提取
            match = re.search(r'tv\.sohu\.com/s\d+/([^/]+)', url)
            if match:
                # 这种URL需要访问页面获取aid
                async with await self._create_client() as client:
                    response = await client.get(url, timeout=10)
                    aid_match = re.search(r'var\s+playlistId\s*=\s*["\']?(\d+)["\']?', response.text)
                    if aid_match:
                        aid = aid_match.group(1)
                        # 获取标题
                        title_match = re.search(r'<title>([^<]+)</title>', response.text)
                        title = title_match.group(1).split('_')[0].strip() if title_match else ''

                        return models.ProviderSearchInfo(
                            provider=self.provider_name,
                            mediaId=aid,
                            title=title,
                            type='tv_series',
                            season=get_season_from_title(title)
                        )

            # 尝试从item URL提取
            match = re.search(r'tv\.sohu\.com/item/([^/]+)\.html', url)
            if match:
                # 这种URL也需要访问页面
                async with await self._create_client() as client:
                    response = await client.get(url, timeout=10)
                    aid_match = re.search(r'var\s+playlistId\s*=\s*["\']?(\d+)["\']?', response.text)
                    if aid_match:
                        aid = aid_match.group(1)
                        title_match = re.search(r'<title>([^<]+)</title>', response.text)
                        title = title_match.group(1).split('_')[0].strip() if title_match else ''

                        return models.ProviderSearchInfo(
                            provider=self.provider_name,
                            mediaId=aid,
                            title=title,
                            type='tv_series',
                            season=get_season_from_title(title)
                        )

            self.logger.warning(f"搜狐视频: 无法从URL中提取信息: {url}")
            return None

        except Exception as e:
            self.logger.error(f"搜狐视频: 从URL提取信息失败: {e}")
            return None

    async def get_id_from_url(self, url: str) -> Optional[Union[str, Dict[str, str]]]:
        """
        从搜狐视频URL中提取ID

        Args:
            url: 搜狐视频URL

        Returns:
            aid 或包含ID信息的字典
        """
        try:
            # 从作品URL中提取aid
            async with await self._create_client() as client:
                response = await client.get(url, timeout=10)
                aid_match = re.search(r'var\s+playlistId\s*=\s*["\']?(\d+)["\']?', response.text)
                if aid_match:
                    return aid_match.group(1)

            self.logger.warning(f"搜狐视频: 无法从URL中提取ID: {url}")
            return None

        except Exception as e:
            self.logger.error(f"搜狐视频: 从URL提取ID失败: {e}")
            return None

    async def close(self):
        """关闭资源"""
        # 搜狐视频scraper没有需要关闭的持久连接
        pass

