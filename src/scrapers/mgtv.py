import asyncio
import logging
import time
import json
import re
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config_manager import ConfigManager
from .. import models, crud
from ..utils import parse_search_keyword
from .base import BaseScraper, get_season_from_title

scraper_responses_logger = logging.getLogger("scraper_responses")

# --- Pydantic Models for Mgtv API ---

# 修正：此模型现在严格遵循C#代码的逻辑，通过属性派生出ID、类型和年份，而不是直接解析。
class MgtvSearchItem(BaseModel):
    title: str
    url: str
    desc: Optional[List[str]] = None
    source: Optional[str] = None
    img: Optional[str] = None
    video_count: int = Field(0, alias="videoCount")

    @field_validator('title', mode='before')
    @classmethod
    def clean_title_html(cls, v: Any) -> str:
        if isinstance(v, str):
            return re.sub(r'<[^>]+>', '', v)
        return str(v)

    @property
    def id(self) -> Optional[str]:
        if not self.url:
            return None
        # 从URL中提取 collection_id, e.g., /b/301218/3605252.html -> 301218
        match = re.search(r'/b/(\d+)/', self.url)
        return match.group(1) if match else None

    @property
    def type_name(self) -> str:
        if not self.desc or not self.desc[0]:
            return ""
        # 从描述字符串中提取类型, e.g., "类型:动漫/..." -> "动漫"
        return self.desc[0].split('/')[0].replace("类型:", "").strip()

    @property
    def year(self) -> Optional[int]:
        if not self.desc or not self.desc[0]:
            return None
        match = re.search(r'[12][890][0-9][0-9]', self.desc[0])
        try:
            return int(match.group(0)) if match else None
        except (ValueError, TypeError):
            return None

class MgtvSearchContent(BaseModel):
    type: str
    # 修正：将data类型改为 List[Dict]，以处理API返回的异构列表
    data: List[Dict[str, Any]]

class MgtvSearchData(BaseModel):
    contents: List[MgtvSearchContent]

class MgtvSearchResult(BaseModel):
    data: MgtvSearchData

class MgtvEpisode(BaseModel):
    source_clip_id: str = Field(alias="src_clip_id")
    clip_id: str = Field(alias="clip_id")
    title: str = Field(alias="t1")
    title2: str = Field("", alias="t2")
    title3: Optional[str] = Field(None, alias="t3")
    time: Optional[str] = None
    video_id: str = Field(alias="video_id")
    timestamp: Optional[str] = Field(None, alias="ts")

class MgtvEpisodeListTab(BaseModel):
    month: str = Field(alias="m")

class MgtvEpisodeListData(BaseModel):
    list: List[MgtvEpisode]
    # 修正：根据API的实际响应，分页标签的字段名是 'tab_m' 而不是 'tabs'
    tabs: List[MgtvEpisodeListTab] = Field(alias="tab_m")

class MgtvEpisodeListResult(BaseModel):
    data: MgtvEpisodeListData

class MgtvControlBarrage(BaseModel):
    cdn_host: Optional[str] = Field("bullet-ali.hitv.com", alias="cdn_host")
    cdn_version: Optional[str] = Field(None, alias="cdn_version")

class MgtvControlBarrageResult(BaseModel):
    data: Optional[MgtvControlBarrage] = None

class MgtvVideoInfo(BaseModel):
    time: str

    @property
    def total_minutes(self) -> int:
        parts = self.time.split(':')
        try:
            if len(parts) == 2:
                return (int(parts[0]) * 60 + int(parts[1])) // 60 + 1
            if len(parts) == 3:
                return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) // 60 + 1
        except (ValueError, IndexError):
            return 0
        return 0

class MgtvVideoInfoData(BaseModel):
    info: MgtvVideoInfo

class MgtvVideoInfoResult(BaseModel):
    data: MgtvVideoInfoData

class MgtvCommentColorRGB(BaseModel):
    r: int
    g: int
    b: int

class MgtvCommentColor(BaseModel):
    color_left: MgtvCommentColorRGB = Field(alias="color_left")

class MgtvComment(BaseModel):
    id: int
    content: str
    time: int
    type: int
    uuid: str
    color: Optional[MgtvCommentColor] = Field(None, alias="v2_color")

class MgtvCommentSegmentData(BaseModel):
    # 修正：将 items 设为 Optional，以处理API在无弹幕的分段中可能不返回此字段的情况。
    items: Optional[List[MgtvComment]] = None
    next: int = 0

class MgtvCommentSegmentResult(BaseModel):
    data: Optional[MgtvCommentSegmentData] = None

# --- Main Scraper Class ---

class MgtvScraper(BaseScraper):
    provider_name = "mgtv"
    handled_domains = ["www.mgtv.com"]
    referer = "https://www.mgtv.com/"
    test_url = "https://www.mgtv.com"
    _PROVIDER_SPECIFIC_BLACKLIST_DEFAULT = r"^(.*?)(抢先(看|版)|加更(版)?|花絮|预告|特辑|(特别|惊喜|纳凉)?企划|彩蛋|专访|幕后(花絮)?|直播|纯享|未播|衍生|番外|合伙人手记|会员(专享|加长)|片花|精华|看点|速看|解读|reaction|超前营业|超前(vlog)?|陪看(记)?|.{3,}篇|影评)(.*?)$"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager):
        super().__init__(session_factory, config_manager)
        self._api_lock = asyncio.Lock()
        self._last_request_time = 0
        # 根据用户反馈，0.5秒的请求间隔在某些网络环境下仍然过快，
        # 适当增加延迟以提高稳定性。
        self._min_interval = 1.0
        self.client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensures the httpx client is initialized, with proxy support."""
        # 检查代理配置是否发生变化
        new_proxy_config = await self._get_proxy_for_provider()
        if self.client and new_proxy_config != self._current_proxy_config:
            self.logger.info("MGTV: 代理配置已更改，正在重建HTTP客户端...")
            await self.client.aclose()
            self.client = None

        if self.client is None:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.mgtv.com/",
                "Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty",
            }
            self.client = await self._create_client(headers=headers)
        
        return self.client

    async def _request_with_rate_limit(self, method: str, url: str, **kwargs) -> httpx.Response:
        async with self._api_lock:
            now = time.time()
            time_since_last = now - self._last_request_time
            if time_since_last < self._min_interval:
                await asyncio.sleep(self._min_interval - time_since_last)
            client = await self._ensure_client()
            response = await client.request(method, url, **kwargs)
            self._last_request_time = time.time()
            return response

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """
        Performs a cached search for Mgtv content.
        It caches the base results for a title and then filters them based on season.
        """
        parsed = parse_search_keyword(keyword)
        search_title = parsed['title']
        search_season = parsed['season']

        cache_key = f"search_base_{self.provider_name}_{search_title}"
        cached_results = await self._get_from_cache(cache_key)

        if cached_results:
            self.logger.info(f"MGTV: 从缓存中命中基础搜索结果 (title='{search_title}')")
            all_results = [models.ProviderSearchInfo.model_validate(r) for r in cached_results]
            # 修复：为缓存结果设置正确的currentEpisodeIndex
            for item in all_results:
                item.currentEpisodeIndex = episode_info.get("episode") if episode_info else None
        else:
            self.logger.info(f"MGTV: 缓存未命中，正在为标题 '{search_title}' 执行网络搜索...")
            all_results = await self._perform_network_search(search_title, episode_info)
            if all_results:
                await self._set_to_cache(cache_key, [r.model_dump() for r in all_results], 'search_ttl_seconds', 3600)

        if search_season is None:
            return all_results

        # Filter results by season
        final_results = [item for item in all_results if item.season == search_season]
        self.logger.info(f"MGTV: 为 S{search_season} 过滤后，剩下 {len(final_results)} 个结果。")
        return final_results

    async def _get_episode_count(self, media_id: str) -> Optional[int]:
        """Helper to fetch only the episode count for a given media_id."""
        try:
            # Use a small size to minimize data transfer, as we only need the 'total' count.
            url = f"https://pcweb.api.mgtv.com/variety/showlist?collection_id={media_id}&page=1&size=1&_support=10000000"
            response = await self._request_with_rate_limit("GET", url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"MGTV Episode Count Response (media_id={media_id}): {response.text}")
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 200 and data.get("data"):
                total = data["data"].get("total")
                if total is not None:
                    self.logger.info(f"MGTV: 成功获取 media_id={media_id} 的总集数: {total}")
                    return int(total)
        except Exception as e:
            self.logger.warning(f"MGTV: 获取 media_id={media_id} 的总集数失败: {e}")
        return None

    async def _perform_network_search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """Performs the actual network search for Mgtv."""
        self.logger.info(f"MGTV: 正在为 '{keyword}' 执行网络搜索...")
        url = f"https://mobileso.bz.mgtv.com/msite/search/v2?q={keyword}&pc=30&pn=1&sort=-99&ty=0&du=0&pt=0&corr=1&abroad=0&_support=10000000000000000"
        
        try:
            response = await self._request_with_rate_limit("GET", url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"MGTV Search Response (keyword='{keyword}'): {response.text}")
            response.raise_for_status()
            search_result = MgtvSearchResult.model_validate(response.json())

            results = []
            if search_result.data and search_result.data.contents:
                for content in search_result.data.contents:
                    if content.type != "media":
                        continue
                    for item_dict in content.data:
                        try:
                            # 修正：在循环内部单独验证每个项目
                            item = MgtvSearchItem.model_validate(item_dict)
                            # 新增：只处理芒果TV自有的内容 (source为'imgo')
                            if item.source != "imgo":
                                self.logger.debug(f"MGTV: 跳过一个非芒果TV自有的搜索结果: {item.title} (源: {item.source})")
                                continue

                            if not item.id:
                                continue
                            
                            media_type = "movie" if item.type_name == "电影" else "tv_series"
                            
                            # For movies, episode count is always 1. For TV, it will be fetched later.
                            episode_count = 1 if media_type == "movie" else None

                            provider_search_info = models.ProviderSearchInfo(
                                provider=self.provider_name,
                                mediaId=item.id,
                                title=item.title.replace(":", "："),
                                type=media_type,
                                season=get_season_from_title(item.title),
                                year=item.year,
                                imageUrl=item.img,
                                episodeCount=episode_count,
                                currentEpisodeIndex=episode_info.get("episode") if episode_info else None
                            )
                            results.append(provider_search_info)
                        except ValidationError:
                            # 安全地跳过不符合我们期望结构的项目（如广告、按钮等）
                            self.logger.debug(f"MGTV: 跳过一个不符合预期的搜索结果项: {item_dict}")
                            continue            
            
            # Concurrently fetch episode counts for TV series
            async def fetch_and_set_count(p_info: models.ProviderSearchInfo):
                if p_info.type == "tv_series" and p_info.mediaId:
                    count = await self._get_episode_count(p_info.mediaId)
                    if count is not None:
                        p_info.episodeCount = count
            
            tasks = [fetch_and_set_count(res) for res in results if res.type == 'tv_series']
            if tasks:
                self.logger.info(f"MGTV: 正在为 {len(tasks)} 个电视剧/动漫结果并发获取总集数...")
                await asyncio.gather(*tasks)

            self.logger.info(f"MGTV: 网络搜索 '{keyword}' 完成，找到 {len(results)} 个结果。")
            if results:
                log_results = "\n".join([f"  - {r.title} (ID: {r.mediaId}, 类型: {r.type}, 年份: {r.year or 'N/A'}, 集数: {r.episodeCount or 'N/A'})" for r in results])
                self.logger.info(f"MGTV: 搜索结果列表:\n{log_results}")
            return results
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            self.logger.warning(f"MGTV: 搜索 '{keyword}' 时连接超时或网络错误: {e}")
            return []
        except Exception as e:
            self.logger.error(f"MGTV: 搜索 '{keyword}' 失败: {e}", exc_info=True)
            return []

    async def get_info_from_url(self, url: str) -> Optional[models.ProviderSearchInfo]:
        """从芒果TV URL中提取作品信息。"""
        self.logger.info(f"MGTV: 正在从URL提取信息: {url}")
        
        # 从URL中提取 collection_id
        match = re.search(r'/b/(\d+)', url)
        if not match:
            self.logger.warning(f"MGTV: 无法从URL中解析出 collection_id: {url}")
            return None
        
        collection_id = match.group(1)
        series_url = f"https://www.mgtv.com/b/{collection_id}/"

        try:
            response = await self._request_with_rate_limit("GET", series_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            title_tag = soup.select_one("h1.title")
            if not title_tag:
                self.logger.error(f"MGTV: 无法从系列页面 (collection_id={collection_id}) 解析标题。")
                return None
            
            title = title_tag.text.strip()
            image_url = soup.select_one("div.v-img img")["src"] if soup.select_one("div.v-img img") else None
            
            # 尝试通过计算分集链接数量来获取总集数
            episode_count = len(soup.select(".episode-list-box a[href*='/b/']"))
            media_type = "movie" if episode_count == 1 else "tv_series"

            return models.ProviderSearchInfo(
                provider=self.provider_name, mediaId=collection_id, title=title,
                type=media_type, season=get_season_from_title(title),
                imageUrl=image_url, episodeCount=episode_count if episode_count > 0 else None
            )
        except Exception as e:
            self.logger.error(f"MGTV: 解析系列页面 (collection_id={collection_id}) 时发生错误: {e}", exc_info=True)
            return None

    async def get_episodes(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        self.logger.info(f"MGTV: 正在为 media_id={media_id} 获取分集列表...")

        # --- 新增：电影类型的专门处理逻辑 ---
        if db_media_type == 'movie':
            self.logger.info(f"MGTV: 检测到媒体类型为电影 (media_id={media_id})，将获取正片。")
            url = f"https://pcweb.api.mgtv.com/variety/showlist?allowedRC=1&collection_id={media_id}&month=&page=1&_support=10000000"
            try:
                response = await self._request_with_rate_limit("GET", url)
                if await self._should_log_responses():
                    scraper_responses_logger.debug(f"MGTV Movie Episodes Response (media_id={media_id}): {response.text}")
                response.raise_for_status()
                result = MgtvEpisodeListResult.model_validate(response.json())

                if result.data and result.data.list:
                    # 智能地寻找正片：
                    # 1. 优先寻找 `isIntact` 为 "1" 的条目，这通常是正片。
                    main_feature = next((ep for ep in result.data.list if ep.isIntact == "1"), None)
                    
                    # 2. 如果找不到，则回退到寻找第一个不是预告片 (`isnew` 不为 "2") 的条目。
                    if not main_feature:
                        main_feature = next((ep for ep in result.data.list if ep.isnew != "2"), None)

                    # 3. 如果还是找不到，作为最后的备用方案，直接使用列表中的第一个条目。
                    if not main_feature:
                        main_feature = result.data.list[0] if result.data.list else None

                    if main_feature:
                        # 电影的真实标题通常在 t3 字段，t1 是描述。
                        title = main_feature.title3 or main_feature.title or "正片"
                        return [
                            models.ProviderEpisodeInfo(
                                provider=self.provider_name,
                                episodeId=f"{media_id},{main_feature.video_id}",
                                title=title,
                                episodeIndex=1, # 电影总是第1集
                                url=f"https://www.mgtv.com/b/{media_id}/{main_feature.video_id}.html"
                            )
                        ]
            except Exception as e:
                self.logger.error(f"MGTV: 获取电影分集失败 (media_id={media_id}): {e}", exc_info=True)
                return []
        # --- 电影处理逻辑结束 ---
        
        all_episodes: List[MgtvEpisode] = []
        month = ""
        page_index = 0
        total_pages = 1 # Start with 1 to enter the loop

        try:
            while page_index < total_pages:
                url = f"https://pcweb.api.mgtv.com/variety/showlist?allowedRC=1&collection_id={media_id}&month={month}&page=1&_support=10000000"
                response = await self._request_with_rate_limit("GET", url)
                if await self._should_log_responses():
                    scraper_responses_logger.debug(f"MGTV Episodes Response (media_id={media_id}, month={month}): {response.text}")
                response.raise_for_status()
                result = MgtvEpisodeListResult.model_validate(response.json())

                if result.data and result.data.list:
                    # Filter episodes that belong to the current collection
                    all_episodes.extend([ep for ep in result.data.list if ep.source_clip_id == media_id])

                if page_index == 0:
                    total_pages = len(result.data.tabs) if result.data and result.data.tabs else 1
                
                page_index += 1
                if page_index < total_pages and result.data and result.data.tabs:
                    month = result.data.tabs[page_index].month
                else:
                    break # No more pages

            raw_episodes = all_episodes

            # 统一过滤逻辑
            # 修正：Mgtv源只应使用其专属的黑名单，以避免全局规则误杀。
            provider_pattern_str = await self.config_manager.get(f"{self.provider_name}_episode_blacklist_regex", self._PROVIDER_SPECIFIC_BLACKLIST_DEFAULT)
            blacklist_pattern = re.compile(provider_pattern_str, re.IGNORECASE) if provider_pattern_str else None
            if blacklist_pattern:
                raw_episodes = [ep for ep in raw_episodes if not blacklist_pattern.search(f"{ep.title2} {ep.title}".strip())]

            # Apply custom blacklist from config
            blacklist_pattern = await self.get_episode_blacklist_pattern()
            if blacklist_pattern:
                raw_episodes = [ep for ep in raw_episodes if not blacklist_pattern.search(f"{ep.title2} {ep.title}".strip())]

            # 排序和编号
            def get_sort_keys(episode: MgtvEpisode) -> tuple:
                ep_num_match = re.search(r'第(\d+)集', episode.title2)
                ep_num = int(ep_num_match.group(1)) if ep_num_match else float('inf')
                timestamp = episode.timestamp or "9999-99-99 99:99:99.9"
                return (ep_num, timestamp)

            sorted_episodes = sorted(raw_episodes, key=get_sort_keys)

            provider_episodes = [
                models.ProviderEpisodeInfo(
                    provider=self.provider_name,
                    episodeId=f"{media_id},{ep.video_id}",
                    title=f"{ep.title2} {ep.title}".strip(),
                    episodeIndex=i + 1,
                    url=f"https://www.mgtv.com/b/{media_id}/{ep.video_id}.html"
                ) for i, ep in enumerate(sorted_episodes)
            ]

            if target_episode_index:
                return [ep for ep in provider_episodes if ep.episodeIndex == target_episode_index]
            
            return provider_episodes

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            self.logger.warning(f"MGTV: 获取分集列表失败 (media_id={media_id})，连接超时或网络错误: {e}")
            return []
        except Exception as e:
            self.logger.error(f"MGTV: 获取分集列表失败 (media_id={media_id}): {e}", exc_info=True)
            return []

    async def get_comments(self, episode_id: str, progress_callback: Optional[Callable] = None) -> List[dict]:
        try:
            cid, vid = episode_id.split(',')
        except (ValueError, IndexError):
            self.logger.error(f"MGTV: 无效的 episode_id 格式: '{episode_id}'")
            return []

        self.logger.info(f"MGTV: 正在为 cid={cid}, vid={vid} 获取弹幕...")

        # --- 策略 1: 使用 getctlbarrage (主策略) ---
        try:
            ctl_url = f"https://galaxy.bz.mgtv.com/getctlbarrage?version=8.1.39&abroad=0&uuid=&os=10.15.7&platform=0&mac=&vid={vid}&pid=&cid={cid}&ticket="
            ctl_response = await self._request_with_rate_limit("GET", ctl_url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"MGTV Control Barrage Response (cid={cid}, vid={vid}): {ctl_response.text}")
            ctl_response.raise_for_status()
            ctl_result = MgtvControlBarrageResult.model_validate(ctl_response.json())

            if ctl_result.data and ctl_result.data.cdn_version:
                self.logger.info("MGTV: 正在使用主策略 (getctlbarrage) 获取弹幕。")
                video_info_url = f"https://pcweb.api.mgtv.com/video/info?allowedRC=1&cid={cid}&vid={vid}&change=3&datatype=1&type=1&_support=10000000"
                video_info_response = await self._request_with_rate_limit("GET", video_info_url)
                if await self._should_log_responses():
                    scraper_responses_logger.debug(f"MGTV Video Info Response (cid={cid}, vid={vid}): {video_info_response.text}")
                video_info_response.raise_for_status()
                video_info_result = MgtvVideoInfoResult.model_validate(video_info_response.json())

                if video_info_result.data and video_info_result.data.info:
                    total_minutes = video_info_result.data.info.total_minutes
                    all_comments = []
                    for minute in range(total_minutes):
                        if progress_callback:
                            progress = int((minute + 1) / total_minutes * 100) if total_minutes > 0 else 100
                            await progress_callback(progress, f"正在下载分段 {minute + 1}/{total_minutes}")

                        segment_url = f"https://{ctl_result.data.cdn_host}/{ctl_result.data.cdn_version}/{minute}.json"
                        try:
                            segment_response = await self._request_with_rate_limit("GET", segment_url)
                            if await self._should_log_responses():
                                scraper_responses_logger.debug(f"MGTV Danmaku Segment Response (vid={vid}, minute={minute}): status={segment_response.status_code}")
                            segment_response.raise_for_status()
                            segment_data = MgtvCommentSegmentResult.model_validate(segment_response.json())
                            if segment_data.data and segment_data.data.items:
                                all_comments.extend(segment_data.data.items)
                        except Exception as seg_e:
                            self.logger.warning(f"MGTV: 下载弹幕分段 {minute} 失败，跳过。错误: {seg_e}")
                    
                    return self._format_comments(all_comments)
        except Exception as e:
            self.logger.warning(f"MGTV: 主弹幕获取策略失败，将尝试备用策略 #1。错误: {e}")

        # --- 策略 2: 使用 opbarrage (备用策略 #1) ---
        self.logger.info("MGTV: 正在使用备用策略 #1 (opbarrage) 获取弹幕。")
        try:
            all_comments = []
            time_offset = 0
            while True:
                if progress_callback:
                    # 假设大部分视频时长在200分钟内，以此估算进度
                    progress = min(95, int((time_offset / (200 * 60)) * 100))
                    await progress_callback(progress, f"正在下载分段 (time={time_offset})")

                fallback_url = f"https://galaxy.bz.mgtv.com/cdn/opbarrage?vid={vid}&pid=&cid={cid}&ticket=&time={time_offset}&allowedRC=1"
                fallback_response = await self._request_with_rate_limit("GET", fallback_url)
                if await self._should_log_responses():
                    scraper_responses_logger.debug(f"MGTV Fallback Danmaku Response (vid={vid}, time={time_offset}): {fallback_response.text}")
                fallback_response.raise_for_status()
                fallback_result = MgtvCommentSegmentResult.model_validate(fallback_response.json())

                if fallback_result.data and fallback_result.data.items:
                    all_comments.extend(fallback_result.data.items)
                    time_offset = fallback_result.data.next
                    if time_offset == 0:
                        break
                else:
                    break
            
            if progress_callback: progress_callback(100, "弹幕处理完成")
            return self._format_comments(all_comments)

        except Exception as e:
            self.logger.warning(f"MGTV: 备用策略 #1 (opbarrage) 失败，将尝试备用策略 #2。错误: {e}")

        # --- 策略 3: 使用 bullet-ws (备用策略 #2) ---
        self.logger.info("MGTV: 正在使用备用策略 #2 (bullet-ws) 获取弹幕。")
        try:
            ws_url = f"https://bullet-ws.hitv.com/bullet/role/all/{vid}"
            ws_response = await self._request_with_rate_limit("GET", ws_url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"MGTV Fallback #2 Danmaku Response (vid={vid}): {ws_response.text}")
            ws_response.raise_for_status()
            ws_data = ws_response.json()

            all_comments = []
            if ws_data.get("status") == 200 and ws_data.get("data"):
                for item in ws_data["data"]["items"]:
                    try:
                        # 手动构造 MgtvComment 模型以复用格式化逻辑
                        style_json = json.loads(item.get("style", "{}"))
                        color_data = {"color_left": style_json.get("color", {"r":255,"g":255,"b":255})}
                        all_comments.append(MgtvComment(
                            id=item.get("id", 0), content=item.get("content", ""), time=item.get("time", 0),
                            type=style_json.get("pos", 0), uuid="", color=MgtvCommentColor.model_validate(color_data)
                        ))
                    except (json.JSONDecodeError, ValidationError):
                        continue
            return self._format_comments(all_comments)
        except Exception as e:
            self.logger.error(f"MGTV: 所有弹幕获取策略均失败 (episode_id={episode_id})。最终错误: {e}", exc_info=True)
        return []

    def _format_comments(self, comments: List[MgtvComment]) -> List[dict]:
        # 新增：按弹幕ID去重
        unique_comments = {c.id: c for c in comments}.values()
        
        formatted_comments = []
        for c in unique_comments:
            mode = 1 # 滚动
            if c.type == 1: mode = 5 # 顶部
            elif c.type == 2: mode = 4 # 底部

            color = 16777215 # 白色
            if c.color and c.color.color_left:
                rgb = c.color.color_left
                color = (rgb.r << 16) | (rgb.g << 8) | rgb.b

            timestamp = c.time / 1000.0
            # 修正：直接在此处添加字体大小 '25'，确保数据源的正确性
            p_string = f"{timestamp:.3f},{mode},25,{color},[{self.provider_name}]"
            
            formatted_comments.append({
                "cid": str(c.id),
                "p": p_string,
                "m": c.content,
                "t": round(timestamp, 2)
            })
        return formatted_comments

    async def get_id_from_url(self, url: str) -> Optional[Dict[str, str]]:
        """从芒果TV URL中提取 collection_id 和 video_id。"""
        match = re.search(r'/b/(\d+)/(\d+)\.html', url)
        if match:
            cid, vid = match.groups()
            self.logger.info(f"MGTV: 从URL {url} 解析到 cid={cid}, vid={vid}")
            return {"cid": cid, "vid": vid}
        self.logger.warning(f"MGTV: 无法从URL中解析出 cid 和 vid: {url}")
        return None

    def format_episode_id_for_comments(self, provider_episode_id: Any) -> str:
        if isinstance(provider_episode_id, dict):
            return f"{provider_episode_id.get('cid')},{provider_episode_id.get('vid')}"
        return str(provider_episode_id)
