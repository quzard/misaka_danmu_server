import asyncio
import hashlib
import json
import logging
import re
import time
import math
from typing import Any, Dict, List, Optional, Callable, Union
from urllib.parse import urlencode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..config_manager import ConfigManager
from .. import models
from ..utils import parse_search_keyword
from .base import BaseScraper, get_season_from_title

scraper_responses_logger = logging.getLogger("scraper_responses")

# --- Pydantic Models for Letv API ---

class LetvDanmuItem(BaseModel):
    """乐视弹幕单条数据模型"""
    model_config = {"populate_by_name": True}

    id: str = Field(alias="_id")
    txt: str
    start: float
    position: int
    color: str
    addtime: int
    uid: Optional[str] = None

class LetvDanmuResponse(BaseModel):
    """乐视弹幕API响应模型"""
    code: int
    data: Optional[Dict[str, Any]] = None

class LetvScraper(BaseScraper):
    """乐视网弹幕获取器"""
    
    provider_name = "le"
    provider_display_name = "乐视网"
    
    # 位置映射：乐视 -> B站格式
    POSITION_MAP = {
        4: 1,  # 滚动弹幕
        3: 4,  # 底部弹幕
        1: 5,  # 顶部弹幕
        2: 1,  # 其他 -> 滚动
    }
    
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager):
        super().__init__(session_factory, config_manager)
        self.base_url = "https://www.le.com"
        self.danmu_api_url = "https://hd-my.le.com/danmu/list"
    
    async def search(
        self,
        keyword: str,
        episode_info: Optional[Dict[str, Any]] = None
    ) -> List[models.ProviderSearchInfo]:
        """
        搜索乐视网内容

        Args:
            keyword: 搜索关键词
            episode_info: 分集信息（可选）

        Returns:
            搜索结果列表
        """
        try:
            self.logger.info(f"开始搜索: {keyword}")

            # 构造搜索URL
            search_url = "https://so.le.com/s"
            params = {
                'wd': keyword,
                'from': 'pc',
                'ref': 'click',
                'click_area': 'search_button',
                'query': keyword,
                'is_default_query': '0',
                'module': 'search_rst_page'
            }

            # 设置请求头，模拟浏览器
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://so.le.com/',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin'
            }

            async with await self._create_client() as client:
                response = await client.get(search_url, params=params, headers=headers, timeout=15, follow_redirects=True)
                response.raise_for_status()
                html_content = response.text

            self.logger.debug(f"乐视网: 搜索请求成功，响应长度: {len(html_content)} 字符")

            # 解析HTML，提取data-info属性
            results = []

            # 使用正则表达式提取所有 data-info 属性
            # 注意：data-info 可能使用单引号或双引号包裹JSON
            pattern = r'<div class="So-detail[^"]*"[^>]*data-info=["\']({[^"\']+})["\']\s*>'
            matches = list(re.finditer(pattern, html_content))

            self.logger.debug(f"乐视网: 从HTML中找到 {len(matches)} 个 data-info 块")

            for match in matches:
                try:
                    data_info_str = match.group(1)
                    # 解析JSON数据
                    data_info = json.loads(data_info_str)

                    # 提取基本信息
                    pid = data_info.get('pid', '')
                    media_type_str = data_info.get('type', '')
                    total = data_info.get('total', '0')

                    if not pid:
                        continue

                    # 从HTML中提取标题和其他信息
                    # 查找对应的HTML块
                    start_pos = match.start()
                    # 查找结束标签，尝试多种可能的结束模式
                    end_patterns = ['</div>\n\t</div>', '</div>\n</div>', '</div></div>']
                    end_pos = -1
                    for end_pattern in end_patterns:
                        pos = html_content.find(end_pattern, start_pos)
                        if pos != -1:
                            end_pos = pos
                            break

                    if end_pos == -1:
                        # 如果找不到结束标签，尝试查找下一个 So-detail
                        next_match = html_content.find('<div class="So-detail', start_pos + 100)
                        if next_match != -1:
                            end_pos = next_match
                        else:
                            continue

                    html_block = html_content[start_pos:end_pos]

                    # 提取标题 - 支持多种格式
                    title_match = re.search(r'<h1>.*?title="([^"]+)"', html_block, re.DOTALL)
                    if not title_match:
                        # 尝试从 <a> 标签中提取
                        title_match = re.search(r'<a[^>]*title="([^"]+)"[^>]*class="j-baidu-a"', html_block)
                    title = title_match.group(1) if title_match else ''

                    # 提取海报
                    img_match = re.search(r'<img[^>]*(?:src|data-src|alt)="([^"]+)"', html_block)
                    image_url = img_match.group(1) if img_match else ''

                    # 提取年份 - 支持多种格式
                    year_match = re.search(r'年份：</b><b><a[^>]*>(\d{4})</a>', html_block)
                    if not year_match:
                        year_match = re.search(r'上映时间：</b><b><a[^>]*>(\d{4})</a>', html_block)
                    if not year_match:
                        # 尝试从 data-info 中获取年份（如果有的话）
                        year_match = re.search(r'y(\d{4})', data_info.get('keyWord', ''))
                    year = int(year_match.group(1)) if year_match else None

                    # 映射媒体类型
                    type_map = {
                        'tv': 'tv_series',
                        'movie': 'movie',
                        'cartoon': 'anime',
                        'comic': 'anime'
                    }
                    result_type = type_map.get(media_type_str, 'tv_series')

                    # 解析集数
                    episode_count = int(total) if total and total.isdigit() else 0

                    # 创建搜索结果
                    result = models.ProviderSearchInfo(
                        provider=self.provider_name,
                        mediaId=pid,
                        title=title,
                        type=result_type,
                        season=1,  # 乐视网不区分季度，默认为1
                        year=year,
                        imageUrl=image_url if image_url.startswith('http') else f"https:{image_url}" if image_url else None,
                        episodeCount=episode_count,
                        currentEpisodeIndex=episode_info.get("episode") if episode_info else None
                    )

                    results.append(result)
                    self.logger.debug(f"乐视网: 解析成功 - {title} (pid={pid}, type={result_type}, episodes={episode_count})")

                except Exception as e:
                    self.logger.warning(f"乐视网: 解析搜索结果项失败: {e}")
                    continue

            if results:
                self.logger.info(f"乐视网: 网络搜索 '{keyword}' 完成，找到 {len(results)} 个有效结果。")
                self.logger.info(f"乐视网: 搜索结果列表:")
                for r in results:
                    self.logger.info(f"  - {r.title} (ID: {r.mediaId}, 类型: {r.type}, 年份: {r.year})")
            else:
                self.logger.info(f"乐视网: 网络搜索 '{keyword}' 完成，找到 0 个结果。")

            return results

        except httpx.HTTPStatusError as e:
            self.logger.error(f"乐视网: HTTP请求失败 (状态码: {e.response.status_code}): {e}", exc_info=True)
            return []
        except Exception as e:
            self.logger.error(f"乐视网: 搜索失败: {e}", exc_info=True)
            return []
    
    async def get_episodes(
        self,
        media_id: str,
        target_episode_index: Optional[int] = None,
        progress_callback: Optional[Callable] = None
    ) -> List[models.ProviderEpisodeInfo]:
        """
        获取分集列表

        Args:
            media_id: 乐视作品ID (pid)
            target_episode_index: 目标集数（如果指定，只返回该集）
            progress_callback: 进度回调

        Returns:
            分集列表
        """
        try:
            self.logger.info(f"开始获取分集列表: media_id={media_id}")

            if progress_callback:
                await progress_callback(10, "正在获取分集信息...")

            # 构造作品页面URL（需要根据类型判断）
            # 先尝试电视剧页面
            urls_to_try = [
                f"https://www.le.com/tv/{media_id}.html",
                f"https://www.le.com/comic/{media_id}.html",
                f"https://www.le.com/playlet/{media_id}.html",
                f"https://www.le.com/movie/{media_id}.html"
            ]

            html_content = None
            async with await self._create_client() as client:
                for url in urls_to_try:
                    try:
                        response = await client.get(url, timeout=10)
                        if response.status_code == 200:
                            html_content = response.text
                            self.logger.debug(f"成功获取页面: {url}")
                            break
                    except Exception as e:
                        self.logger.debug(f"尝试URL失败 {url}: {e}")
                        continue

            if not html_content:
                self.logger.error(f"无法获取作品页面: media_id={media_id}")
                return []

            if progress_callback:
                await progress_callback(50, "正在解析分集列表...")

            # 从HTML中提取data-info
            data_info_match = re.search(r'data-info=\'({[^\']+})\'', html_content)
            if not data_info_match:
                self.logger.error(f"未找到data-info: media_id={media_id}")
                return []

            data_info = json.loads(data_info_match.group(1))
            vid_episode_str = data_info.get('vidEpisode', '')

            if not vid_episode_str:
                self.logger.warning(f"未找到分集信息: media_id={media_id}")
                return []

            # 解析vidEpisode: '1-26316591,2-26316374,3-26327049,...'
            episodes = []
            for item in vid_episode_str.split(','):
                try:
                    parts = item.split('-')
                    if len(parts) != 2:
                        continue

                    episode_index = int(parts[0])
                    video_id = parts[1]

                    # 如果指定了目标集数，只返回该集
                    if target_episode_index is not None and episode_index != target_episode_index:
                        continue

                    episode = models.ProviderEpisodeInfo(
                        provider=self.provider_name,
                        episodeId=video_id,
                        episodeIndex=episode_index,
                        title=f"第{episode_index}集",
                        officialUrl=f"https://www.le.com/ptv/vplay/{video_id}.html"
                    )

                    episodes.append(episode)

                except Exception as e:
                    self.logger.warning(f"解析分集失败: {item}, 错误: {e}")
                    continue

            if progress_callback:
                await progress_callback(100, f"获取完成，共 {len(episodes)} 集")

            self.logger.info(f"成功获取分集列表: media_id={media_id}, 共 {len(episodes)} 集")
            return episodes

        except Exception as e:
            self.logger.error(f"获取分集列表失败: {e}", exc_info=True)
            return []

    async def get_info_from_url(self, url: str) -> Optional[models.ProviderSearchInfo]:
        """
        从乐视网URL中提取作品信息

        Args:
            url: 乐视网作品URL

        Returns:
            作品信息，如果解析失败则返回None
        """
        try:
            # 从URL中提取media_id
            # 支持的URL格式:
            # https://www.le.com/tv/{pid}.html
            # https://www.le.com/comic/{pid}.html
            # https://www.le.com/playlet/{pid}.html
            # https://www.le.com/movie/{pid}.html
            match = re.search(r'le\.com/(?:tv|comic|playlet|movie)/(\d+)\.html', url)
            if not match:
                self.logger.warning(f"无法从URL中提取media_id: {url}")
                return None

            media_id = match.group(1)

            # 获取页面内容
            async with await self._create_client() as client:
                response = await client.get(url, timeout=10)
                if response.status_code != 200:
                    return None
                html_content = response.text

            # 解析data-info
            data_info_match = re.search(r'data-info=["\']({[^"\']+})["\']', html_content)
            if not data_info_match:
                return None

            data_info = json.loads(data_info_match.group(1))

            # 提取标题
            title_match = re.search(r'<title>([^<]+)</title>', html_content)
            title = title_match.group(1).split('-')[0].strip() if title_match else ''

            # 提取年份
            year_match = re.search(r'年份：</b><b><a[^>]*>(\d{4})</a>', html_content)
            if not year_match:
                year_match = re.search(r'上映时间：</b><b><a[^>]*>(\d{4})</a>', html_content)
            year = int(year_match.group(1)) if year_match else None

            # 提取海报
            img_match = re.search(r'<img[^>]*(?:src|data-src)="([^"]+)"', html_content)
            image_url = img_match.group(1) if img_match else None

            # 映射类型
            media_type_str = data_info.get('type', '')
            type_map = {
                'tv': 'tv_series',
                'movie': 'movie',
                'cartoon': 'anime',
                'comic': 'anime'
            }
            result_type = type_map.get(media_type_str, 'tv_series')

            # 总集数
            total = data_info.get('total', '0')
            episode_count = int(total) if total and total.isdigit() else 0

            return models.ProviderSearchInfo(
                provider=self.provider_name,
                mediaId=media_id,
                title=title,
                type=result_type,
                season=1,
                year=year,
                imageUrl=image_url if image_url and image_url.startswith('http') else f"https:{image_url}" if image_url else None,
                episodeCount=episode_count,
                currentEpisodeIndex=None
            )

        except Exception as e:
            self.logger.error(f"从URL提取信息失败: {e}", exc_info=True)
            return None

    async def get_id_from_url(self, url: str) -> Optional[Union[str, Dict[str, str]]]:
        """
        从乐视网URL中提取ID

        Args:
            url: 乐视网URL

        Returns:
            media_id 或包含ID信息的字典
        """
        try:
            # 从作品URL中提取media_id
            match = re.search(r'le\.com/(?:tv|comic|playlet|movie)/(\d+)\.html', url)
            if match:
                return match.group(1)

            # 从播放页URL中提取video_id
            match = re.search(r'le\.com/ptv/vplay/(\d+)\.html', url)
            if match:
                return {'video_id': match.group(1)}

            return None

        except Exception as e:
            self.logger.error(f"从URL提取ID失败: {e}", exc_info=True)
            return None

    async def close(self):
        """关闭资源"""
        # 乐视网scraper没有需要关闭的持久连接
        pass
    
    async def _get_video_duration(self, video_id: str) -> int:
        """获取视频时长（秒）"""
        try:
            async with await self._create_client() as client:
                url = f"{self.base_url}/ptv/vplay/{video_id}.html"
                response = await client.get(url, timeout=10)
                
                # 从页面中提取时长信息
                duration_match = re.search(r"duration['\"]?\s*:\s*['\"]?(\d+):(\d+)['\"]?", response.text)
                if duration_match:
                    minutes, seconds = map(int, duration_match.groups())
                    return minutes * 60 + seconds
                
                # 默认返回40分钟
                return 2400
        except Exception as e:
            self.logger.warning(f"获取视频时长失败: {e}，使用默认值2400秒")
            return 2400
    
    async def _get_danmu_segment(
        self,
        video_id: str,
        start_time: int,
        end_time: int,
        client: httpx.AsyncClient
    ) -> List[Dict[str, Any]]:
        """获取单个时间段的弹幕"""
        for attempt in range(3):
            try:
                params = {
                    'vid': video_id,
                    'start': start_time,
                    'end': end_time,
                    'callback': f'vjs_{int(time.time() * 1000)}'
                }
                
                response = await client.get(self.danmu_api_url, params=params, timeout=10)
                
                # 解析JSONP响应
                json_match = re.search(r'vjs_\d+\((.*)\)', response.text)
                if json_match:
                    data = json.loads(json_match.group(1))
                    if data.get('code') == 200 and 'data' in data:
                        danmu_list = data['data'].get('list', [])
                        self.logger.debug(f"获取时间段 {start_time}-{end_time}s 的弹幕: {len(danmu_list)} 条")
                        return danmu_list
                
                self.logger.warning(f"时间段 {start_time}-{end_time}s 返回数据格式异常")
                return []
                
            except Exception as e:
                self.logger.warning(f"获取时间段 {start_time}-{end_time}s 弹幕失败 (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    await asyncio.sleep(1)
        
        return []
    
    async def get_comments(
        self,
        episode_id: str,
        progress_callback: Optional[Callable] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        获取指定视频的弹幕
        
        Args:
            episode_id: 乐视视频ID
            progress_callback: 进度回调函数
            
        Returns:
            弹幕列表，格式为 [{'p': '时间,类型,字号,颜色,时间戳,弹幕池,用户ID,弹幕ID', 'm': '弹幕内容'}, ...]
        """
        try:
            video_id = episode_id
            self.logger.info(f"开始获取乐视视频 {video_id} 的弹幕")
            
            if progress_callback:
                await progress_callback(10, "正在获取视频时长...")
            
            # 获取视频时长
            duration = await self._get_video_duration(video_id)
            self.logger.info(f"视频时长: {duration}秒")
            
            # 计算需要请求的时间段（每段5分钟）
            segments = []
            for i in range(math.ceil(duration / 300)):
                start_time = i * 300
                end_time = min((i + 1) * 300, duration)
                segments.append((start_time, end_time))
            
            self.logger.info(f"将分 {len(segments)} 个时间段获取弹幕")
            
            if progress_callback:
                await progress_callback(20, f"正在获取弹幕 (共{len(segments)}个时间段)...")
            
            # 并发获取所有时间段的弹幕
            all_danmu = []
            async with await self._create_client() as client:
                tasks = [
                    self._get_danmu_segment(video_id, start, end, client)
                    for start, end in segments
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        self.logger.error(f"时间段 {i} 获取失败: {result}")
                    elif result:
                        all_danmu.extend(result)
                    
                    # 更新进度
                    if progress_callback:
                        progress = 20 + int((i + 1) / len(segments) * 60)
                        await progress_callback(progress, f"已获取 {i + 1}/{len(segments)} 个时间段")
            
            if not all_danmu:
                self.logger.warning(f"视频 {video_id} 未获取到任何弹幕")
                return []
            
            if progress_callback:
                await progress_callback(85, "正在去重和格式化...")
            
            # 去重（根据弹幕ID）
            unique_danmu = {}
            for danmu in all_danmu:
                # 支持两种字段名：id (Pydantic模型) 和 _id (原始JSON)
                danmu_id = danmu.get('id') or danmu.get('_id')
                if danmu_id and danmu_id not in unique_danmu:
                    unique_danmu[danmu_id] = danmu
            
            danmu_list = list(unique_danmu.values())
            self.logger.info(f"去重后弹幕数量: {len(danmu_list)} 条")
            
            # 按时间排序
            danmu_list.sort(key=lambda x: float(x.get('start', 0)))
            
            # 转换为标准格式（参考TX源的格式）
            formatted_comments = []
            for danmu in danmu_list:
                try:
                    # 位置转换
                    position = self.POSITION_MAP.get(int(danmu.get('position', 4)), 1)

                    # 时间（秒）
                    time_val = float(danmu.get('start', 0))

                    # 颜色（十六进制转十进制）
                    color_hex = danmu.get('color', 'FFFFFF')
                    color = int(color_hex, 16)

                    # 弹幕ID - 支持两种字段名
                    danmu_id = danmu.get('id') or danmu.get('_id', '')

                    # 弹幕内容
                    content = danmu.get('txt', '')

                    # 构造p属性：时间,模式,字体大小,颜色,[来源]
                    # 格式参考TX源：f"{timestamp:.2f},{mode},25,{color},[{self.provider_name}]"
                    p_string = f"{time_val:.2f},{position},25,{color},[{self.provider_name}]"

                    formatted_comments.append({
                        'cid': danmu_id,
                        'p': p_string,
                        'm': content,
                        't': round(time_val, 2)
                    })

                except Exception as e:
                    self.logger.warning(f"格式化弹幕失败: {e}, 弹幕数据: {danmu}")
                    continue
            
            if progress_callback:
                await progress_callback(100, f"获取完成，共 {len(formatted_comments)} 条弹幕")
            
            self.logger.info(f"成功获取乐视视频 {video_id} 的弹幕: {len(formatted_comments)} 条")
            return formatted_comments
            
        except Exception as e:
            self.logger.error(f"获取乐视弹幕失败: {e}", exc_info=True)
            return None

