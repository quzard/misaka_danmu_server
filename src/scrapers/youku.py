import asyncio
import hashlib
import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Union, Callable
from collections import defaultdict
from urllib.parse import urlencode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config_manager import ConfigManager
from .. import models
from ..utils import parse_search_keyword
from .base import BaseScraper, get_season_from_title

scraper_responses_logger = logging.getLogger("scraper_responses")

# --- Pydantic Models for Youku API ---

# Search
class YoukuSearchTitleDTO(BaseModel):
    display_name: str = Field(alias="displayName")

class YoukuPosterDTO(BaseModel):
    v_thumb_url: Optional[str] = Field(None, alias="vThumbUrl")

class YoukuSearchCommonData(BaseModel):
    show_id: str = Field(alias="showId")
    episode_total: int = Field(alias="episodeTotal")
    feature: str
    cats: Optional[str] = None  # 新增：节目分类字段
    is_youku: int = Field(alias="isYouku")
    has_youku: int = Field(alias="hasYouku")
    poster_dto: Optional[YoukuPosterDTO] = Field(None, alias="posterDTO")
    title_dto: YoukuSearchTitleDTO = Field(alias="titleDTO")

class YoukuSearchComponent(BaseModel):
    common_data: Optional[YoukuSearchCommonData] = Field(None, alias="commonData")
    component_map: Optional[Dict[str, Any]] = Field(None, alias="componentMap")

class YoukuSearchResult(BaseModel):
    page_component_list: Optional[List[YoukuSearchComponent]] = Field(None, alias="pageComponentList")

# Episodes
class YoukuEpisodeInfo(BaseModel):
    id: str
    title: str
    # 新增：添加 displayName 字段以捕获更完整的分集标题，特别是对于综艺节目
    display_name: Optional[str] = Field(None, alias="displayName")
    show_video_stage: Optional[str] = Field(None, alias="showVideoStage")
    stage: Optional[str] = None
    seq: Optional[str] = None
    duration: Optional[str] = None
    category: Optional[str] = None
    link: Optional[str] = None

    @property
    def clean_display_name(self) -> Optional[str]:
        """返回一个移除了日期前缀的 displayName。"""
        if not self.display_name:
            return None
        # 修正：更新正则表达式以保留“第X期”部分，并进一步移除“上/中/下”部分。
        # 新的模式会智能地区分两种情况：
        # 1. 如果日期后跟着“第X期”，则只移除日期。
        # 2. 如果日期后跟着冒号，则将日期和冒号一并移除。
        pattern = r'^(?:\d{2,4}-\d{2}-\d{2}|\d{2}-\d{2})\s*(?=(?:第\d+期))|^(?:\d{2,4}-\d{2}-\d{2}|\d{2}-\d{2})\s*:\s*'
        return re.sub(pattern, '', self.display_name).strip()


    @property
    def total_mat(self) -> int:
        try:
            duration_float = float(self.duration) if self.duration else 0.0
            return int(duration_float // 60) + 1
        except (ValueError, TypeError):
            return 0

class YoukuVideoResult(BaseModel):
    total: int
    videos: List[YoukuEpisodeInfo]

# Danmaku
class YoukuCommentProperty(BaseModel):
    color: int
    pos: int
    size: int

class YoukuComment(BaseModel):
    id: int
    content: str
    playat: int # milliseconds
    propertis: str
    uid: str

class YoukuDanmakuData(BaseModel):
    result: List[YoukuComment]

class YoukuDanmakuResult(BaseModel):
    data: YoukuDanmakuData

# 修正：更新模型以正确处理优酷API的成功和错误响应结构
class YoukuRpcData(BaseModel):
    result: str # This is a JSON string

class YoukuRpcResult(BaseModel):
    # 新增：添加 api, ret, v 字段以匹配真实响应
    api: str
    data: Optional[YoukuRpcData] = None # data 在出错时可能不存在
    ret: List[str]
    v: str

# --- Main Scraper Class ---

class YoukuScraper(BaseScraper):
    provider_name = "youku"
    handled_domains = ["v.youku.com"]
    referer = "https://v.youku.com"
    test_url = "https://v.youku.com"
    _PROVIDER_SPECIFIC_BLACKLIST_DEFAULT = r"^(.*?)(抢先(版|篇)?|加更(版|篇)?|花絮|预告|特辑|彩蛋|专访|幕后(故事|花絮)?|直播|纯享|未播|衍生|番外|会员(专属|加长)?|片花|精华|看点|速览|解读|reaction|影评)(.*?)$"

    # 新增：为令牌过期定义一个自定义异常
    class TokenExpiredError(Exception):
        """当检测到优酷弹幕令牌过期时引发。"""
        pass
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager):
        super().__init__(session_factory, config_manager)
        # Regexes from C#
        self.year_reg = re.compile(r"[12][890][0-9][0-9]")
        self.unused_words_reg = re.compile(r"<[^>]+>|【.+?】")

        self.client: Optional[httpx.AsyncClient] = None

        # For danmaku signing
        self._cna = ""
        self._token = ""

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensures the httpx client is initialized, with proxy support."""
        # 检查代理配置是否发生变化
        new_proxy_config = await self._get_proxy_for_provider()
        if self.client and new_proxy_config != self._current_proxy_config:
            self.logger.info("Youku: 代理配置已更改，正在重建HTTP客户端...")
            await self.client.aclose()
            self.client = None

        if self.client is None:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            self.client = await self._create_client(headers=headers, timeout=20.0, follow_redirects=True)
        
        return self.client

    async def get_episode_blacklist_pattern(self) -> Optional[re.Pattern]:
        """
        获取并编译用于过滤分集的正则表达式。
        此方法现在只使用数据库中配置的规则，如果规则为空，则不进行过滤。
        """
        # 1. 构造该源特定的配置键，确保与数据库键名一致
        provider_blacklist_key = f"{self.provider_name}_episode_blacklist_regex"
        
        # 2. 从数据库动态获取用户自定义规则
        custom_blacklist_str = await self.config_manager.get(provider_blacklist_key)

        # 3. 仅当用户配置了非空的规则时才进行过滤
        if custom_blacklist_str and custom_blacklist_str.strip():
            self.logger.info(f"正在为 '{self.provider_name}' 使用数据库中的自定义分集黑名单。")
            try:
                return re.compile(custom_blacklist_str, re.IGNORECASE)
            except re.error as e:
                self.logger.error(f"编译 '{self.provider_name}' 的分集黑名单时出错: {e}。规则: '{custom_blacklist_str}'")
        
        # 4. 如果规则为空或未配置，则不进行过滤
        return None

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        client = await self._ensure_client()
        return await client.request(method, url, **kwargs)

    async def search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """
        Performs a cached search for Youku content.
        It caches the base results for a title and then filters them based on season.
        """
        parsed = parse_search_keyword(keyword)
        search_title = parsed['title']
        search_season = parsed['season']

        cache_key = f"search_base_{self.provider_name}_{search_title}"
        cached_results = await self._get_from_cache(cache_key)

        if cached_results:
            self.logger.info(f"Youku: 从缓存中命中基础搜索结果 (title='{search_title}')")
            all_results = [models.ProviderSearchInfo.model_validate(r) for r in cached_results]
            # 修复：为缓存结果设置正确的currentEpisodeIndex
            for item in all_results:
                item.currentEpisodeIndex = episode_info.get("episode") if episode_info else None
        else:
            self.logger.info(f"Youku: 缓存未命中，正在为标题 '{search_title}' 执行网络搜索...")
            all_results = await self._perform_network_search(search_title, episode_info)
            if all_results:
                await self._set_to_cache(cache_key, [r.model_dump() for r in all_results], 'search_ttl_seconds', 3600)

        if search_season is None:
            return all_results

        # Filter results by season
        final_results = [item for item in all_results if item.season == search_season]
        self.logger.info(f"Youku: 为 S{search_season} 过滤后，剩下 {len(final_results)} 个结果。")
        return final_results

    async def _perform_network_search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """Performs the actual network search for Youku."""
        self.logger.info(f"Youku: 正在为 '{keyword}' 执行网络搜索...")
        ua_encoded = urlencode({"userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"})
        keyword_encoded = urlencode({"keyword": keyword})
        url = f"https://search.youku.com/api/search?{keyword_encoded}&{ua_encoded}&site=1&categories=0&ftype=0&ob=0&pg=1"
        
        results = []
        try:
            response = await self._request("GET", url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"Youku Search Response (keyword='{keyword}'): {response.text}")
            response.raise_for_status()
            data = YoukuSearchResult.model_validate(response.json())

            if not data.page_component_list:
                return []

            for component in data.page_component_list:
                common_data = component.common_data
                if not common_data or not common_data.title_dto or (common_data.is_youku != 1 and common_data.has_youku != 1):
                    continue
                
                title = common_data.title_dto.display_name
                if any(kw in title for kw in ["中配版", "抢先看", "非正片", "解读", "揭秘", "赏析", "《"]):
                    continue

                year_match = self.year_reg.search(common_data.feature)
                year = int(year_match.group(0)) if year_match else None
                
                cleaned_title = self.unused_words_reg.sub("", title).strip().replace(":", "：")
                
                # 新增：提取媒体类型并缓存
                media_type_detected = self._extract_media_type_from_response(common_data)
                media_type_cache_key = f"media_type_{common_data.show_id}"
                await self._set_to_cache(media_type_cache_key, media_type_detected, 'episodes_ttl_seconds', 3600)
                
                media_type = "movie" if "电影" in common_data.feature else "tv_series"
                
                current_episode = episode_info.get("episode") if episode_info else None

                provider_search_info = models.ProviderSearchInfo(
                    provider=self.provider_name,
                    mediaId=common_data.show_id,
                    title=cleaned_title,
                    type=media_type,
                    season=get_season_from_title(cleaned_title),
                    year=year,
                    imageUrl=common_data.poster_dto.v_thumb_url if common_data.poster_dto else None,
                    episodeCount=common_data.episode_total,
                    currentEpisodeIndex=current_episode
                )
                self.logger.debug(f"Youku: 创建的 ProviderSearchInfo: {provider_search_info.model_dump_json(indent=2)}")

                # 新增：缓存从搜索结果中获取的详细分集列表
                if component.component_map and "1052" in component.component_map:
                    episodes_component = component.component_map["1052"]
                    if episodes_component and "data" in episodes_component:
                        raw_episode_list = episodes_component["data"]
                        show_id = common_data.show_id
                        # 缓存键应与 get_episodes 中的逻辑匹配
                        ep_cache_key = f"episodes_from_search_{show_id}"
                        # 直接缓存原始的字典列表，在 get_episodes 中进行解析
                        await self._set_to_cache(ep_cache_key, raw_episode_list, 'episodes_ttl_seconds', 3600)
                        self.logger.info(f"Youku: 缓存了来自搜索的 {len(raw_episode_list)} 个详细分集 (show_id={show_id})")

                results.append(provider_search_info)

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            # 修正：对常见的网络错误只记录警告，避免在日志中产生大量堆栈跟踪。
            self.logger.warning(f"Youku: 网络搜索 '{keyword}' 时连接超时或网络错误: {e}")
        except Exception as e:
            self.logger.error(f"Youku: 网络搜索 '{keyword}' 失败: {e}", exc_info=True)

        self.logger.info(f"Youku: 网络搜索 '{keyword}' 完成，找到 {len(results)} 个有效结果。")
        if results:
            log_results = "\n".join([f"  - {r.title} (ID: {r.mediaId}, 类型: {r.type}, 年份: {r.year or 'N/A'})" for r in results])
            self.logger.info(f"Youku: 搜索结果列表:\n{log_results}")
        return results

    async def get_info_from_url(self, url: str) -> Optional[models.ProviderSearchInfo]:
        """从优酷URL中提取作品信息。"""
        self.logger.info(f"Youku: 正在从URL提取信息: {url}")
        
        try:
            response = await self._request("GET", url)
            response.raise_for_status()
            html_content = response.text

            # 1. 从页面中解析 show_id
            show_id_match = re.search(r'showid:"(\d+)"', html_content)
            if not show_id_match:
                self.logger.warning(f"Youku: 无法从页面HTML中解析出 show_id: {url}")
                return None
            show_id = show_id_match.group(1)

            # 2. 从页面中解析标题
            title_match = re.search(r'<title>(.*?)<\/title>', html_content)
            title = title_match.group(1).split('-')[0].strip() if title_match else "未知标题"
            cleaned_title = self.unused_words_reg.sub("", title).strip().replace(":", "：")

            # 3. 从页面中解析封面图
            image_match = re.search(r'<meta\s+property="og:image"\s+content="(.*?)"', html_content)
            image_url = image_match.group(1) if image_match else None

            # 4. 使用标题进行搜索，以获取更准确的元数据，然后通过show_id进行匹配
            search_results = await self.search(keyword=cleaned_title)
            best_match = next((r for r in search_results if r.mediaId == show_id), None)

            if best_match:
                return best_match
            else:
                # 如果搜索未找到，则基于已抓取的信息构建一个基础对象
                return models.ProviderSearchInfo(provider=self.provider_name, mediaId=show_id, title=cleaned_title, type="tv_series", season=get_season_from_title(cleaned_title), imageUrl=image_url)
        except Exception as e:
            self.logger.error(f"Youku: 从URL '{url}' 提取信息失败: {e}", exc_info=True)
            return None

    async def get_episodes(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        # 优酷的逻辑不区分电影和电视剧，都是从一个show_id获取列表，
        # 所以db_media_type在这里用不上，但为了接口统一还是保留参数。

        raw_episodes: List[YoukuEpisodeInfo] = []
        # 仅当请求完整列表时才尝试从缓存获取
        cache_key = f"episodes_raw_{media_id}"
        if target_episode_index is None:
            cached_episodes = await self._get_from_cache(cache_key)
            if cached_episodes is not None:
                self.logger.info(f"Youku: 从缓存中命中原始分集列表 (media_id={media_id})")
                raw_episodes = [YoukuEpisodeInfo.model_validate(e) for e in cached_episodes]
        
        # 如果缓存未命中或不需要缓存，则从网络获取
        if not raw_episodes:
            self.logger.info(f"Youku: 缓存未命中或需要特定分集，正在为 media_id={media_id} 执行网络获取...")
            network_episodes = []
            page = 1
            page_size = 100
            
            while True:
                try:
                    page_result = await self._get_episodes_page(media_id, page, page_size)
                    if not page_result or not page_result.videos:
                        break
                    
                    network_episodes.extend(page_result.videos)

                    # 修正：使用 page_result.total 来判断是否已获取所有分集
                    if len(network_episodes) >= page_result.total or len(page_result.videos) < page_size:
                        break
                    
                    page += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    self.logger.error(f"Youku: 获取分集页面 {page} 失败 (media_id={media_id}): {e}", exc_info=True)
                    break
            
            raw_episodes = network_episodes
            # 仅当请求完整列表且成功获取到数据时，才缓存原始数据
            if raw_episodes and target_episode_index is None:
                await self._set_to_cache(cache_key, [e.model_dump() for e in raw_episodes], 'episodes_ttl_seconds', 1800)

        final_episodes = await self._process_and_format_episodes(raw_episodes, target_episode_index, media_id)

        if target_episode_index:
            return [ep for ep in final_episodes if ep.episodeIndex == target_episode_index]
        return final_episodes

    async def _process_and_format_episodes(self, raw_episodes: List[YoukuEpisodeInfo], target_episode_index: Optional[int], media_id: str) -> List[models.ProviderEpisodeInfo]:
        """
        一个集中的辅助函数，用于过滤、格式化和编号原始的优酷分集列表。
        """
        # 获取媒体类型
        media_type_cache_key = f"media_type_{media_id}"
        media_type = await self._get_from_cache(media_type_cache_key) or 'variety'
        
        # 计算真实期数映射
        stage_to_episode = self._calculate_episode_number_from_stage(raw_episodes)
        
        # --- 关键修正：总是在获取数据后（无论来自缓存还是网络）应用过滤 ---
        provider_pattern_str = await self.config_manager.get(
            f"{self.provider_name}_episode_blacklist_regex", self._PROVIDER_SPECIFIC_BLACKLIST_DEFAULT
        )
        blacklist_pattern = re.compile(provider_pattern_str, re.IGNORECASE) if provider_pattern_str else None
        
        filtered_episodes = []
        if blacklist_pattern:
            filtered_out_log: Dict[str, List[str]] = defaultdict(list)

            for ep in raw_episodes:
                title_to_check = f"{ep.clean_display_name or ep.title}".strip()
                if blacklist_pattern.search(title_to_check):
                    filtered_out_log[blacklist_pattern.pattern].append(title_to_check)
                else:
                    filtered_episodes.append(ep)
            
            if filtered_out_log:
                for rule, titles in filtered_out_log.items():
                    self.logger.info(f"Youku: 根据黑名单规则 '{rule}' 过滤掉了 {len(titles)} 个分集: {', '.join(titles)}")
        else:
            filtered_episodes = raw_episodes

        # 在过滤后的列表上重新编号，使用媒体类型格式化标题
        final_episodes = [
            models.ProviderEpisodeInfo(
                provider=self.provider_name,
                episodeId=ep.id.replace("=", "_"),
                title=self._format_episode_title(ep, i + 1, media_type, stage_to_episode),
                episodeIndex=i + 1,
                url=ep.link
            ) for i, ep in enumerate(filtered_episodes)
        ]
        
        return final_episodes

    def _calculate_episode_number_from_stage(self, episodes: List[YoukuEpisodeInfo]) -> Dict[str, int]:
        """根据stage字段计算真实的期数"""
        stage_to_episode = {}
        unique_stages = sorted(set(ep.stage for ep in episodes if ep.stage))
        
        for i, stage in enumerate(unique_stages, 1):
            stage_to_episode[stage] = i
        
        return stage_to_episode

    async def _get_episodes_page(self, show_id: str, page: int, page_size: int) -> Optional[YoukuVideoResult]:
        client = await self._ensure_client()
        url = f"https://openapi.youku.com/v2/shows/videos.json?client_id=53e6cc67237fc59a&package=com.huawei.hwvplayer.youku&ext=show&show_id={show_id}&page={page}&count={page_size}"
        response = await client.get(url)
        if await self._should_log_responses():
            scraper_responses_logger.debug(f"Youku Episodes Page Response (show_id={show_id}, page={page}): {response.text}")
        response.raise_for_status()
        return YoukuVideoResult.model_validate(response.json())

    async def get_comments(self, episode_id: str, progress_callback: Optional[Callable] = None) -> Optional[List[dict]]:
        vid = episode_id.replace("_", "=")
        
        try:
            await self._ensure_token_cookie() # 首次获取令牌
            
            episode_info_url = f"https://openapi.youku.com/v2/videos/show_basic.json?client_id=53e6cc67237fc59a&package=com.huawei.hwvplayer.youku&video_id={vid}"
            episode_info_resp = await self._request("GET", episode_info_url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"Youku Episode Info Response (vid={vid}): {episode_info_resp.text}")
            episode_info_resp.raise_for_status()
            episode_info = YoukuEpisodeInfo.model_validate(episode_info_resp.json())
            total_mat = episode_info.total_mat

            if total_mat == 0:
                self.logger.warning(f"Youku: Video {vid} has duration 0, no danmaku to fetch.")
                return [] # 返回空列表表示成功但无内容

            all_comments = []
            # 修正：使用 while 循环以支持重试
            mat = 0
            while mat < total_mat:
                try:
                    if progress_callback:
                        progress = int((mat + 1) / total_mat * 100) if total_mat > 0 else 100
                        await progress_callback(progress, f"正在获取分段 {mat + 1}/{total_mat}")

                    comments_in_mat = await self._get_danmu_content_by_mat(vid, mat)
                    if comments_in_mat:
                        all_comments.extend(comments_in_mat)
                    
                    mat += 1 # 成功，处理下一段
                    await asyncio.sleep(0.2)
                except self.TokenExpiredError:
                    self.logger.warning(f"Youku: 令牌已过期，正在强制刷新并重试分段 {mat + 1}...")
                    await self._ensure_token_cookie(force_refresh=True)
                    # 不增加 mat，以便重试当前分段
                    continue

            if progress_callback:
                await progress_callback(100, "弹幕整合完成")

            return self._format_comments(all_comments)

        except self.TokenExpiredError:
            # 如果在循环外（例如第一次请求就失败且无法恢复）捕获到，则任务失败
            self.logger.error(f"Youku: 无法获取有效令牌，任务失败 (vid: {vid})")
            return None
        except Exception as e:
            self.logger.error(f"Youku: Failed to get danmaku for vid {vid}: {e}", exc_info=True)
            return None # 返回 None 表示获取失败

    async def _ensure_token_cookie(self, force_refresh: bool = False):
        """
        确保获取弹幕签名所需的 cna 和 _m_h5_tk cookie。
        此逻辑严格参考了 C# 代码，并针对网络环境进行了优化。
        """
        # 修正：在函数开头就确保客户端已初始化，以防止在后续代码中对 NoneType 对象进行操作。
        client = await self._ensure_client()

        # 步骤 1: 获取 'cna' cookie。它通常由优酷主站或其统计服务设置。
        # 我们优先访问主站，因为它更不容易出网络问题。
        cna_val = client.cookies.get("cna")
        if not cna_val or force_refresh:
            try:
                log_msg = "强制刷新 'cna' cookie..." if force_refresh else "'cna' cookie 未找到, 正在访问 youku.com 以获取..."
                self.logger.debug(f"Youku: {log_msg}")
                await client.get("https://www.youku.com/")
                cna_val = self.client.cookies.get("cna")
            except httpx.ConnectError as e:
                self.logger.warning(f"Youku: 无法连接到 youku.com 获取 'cna' cookie。错误: {e}")
        self._cna = cna_val or ""

        # 步骤 2: 获取 '_m_h5_tk' 令牌, 此请求可能依赖于 'cna' cookie 的存在。
        token_val = client.cookies.get("_m_h5_tk")
        if not token_val or force_refresh:
            try:
                log_msg = "强制刷新 '_m_h5_tk' cookie..." if force_refresh else "'_m_h5_tk' cookie 未找到, 正在从 acs.youku.com 请求..."
                self.logger.debug(f"Youku: {log_msg}")
                await client.get("https://acs.youku.com/h5/mtop.com.youku.aplatform.weakget/1.0/?jsv=2.5.1&appKey=24679788")
                token_val = client.cookies.get("_m_h5_tk")
            except httpx.ConnectError as e:
                self.logger.error(f"Youku: 无法连接到 acs.youku.com 获取令牌 cookie。弹幕获取很可能会失败。错误: {e}")
        
        self._token = token_val.split("_")[0] if token_val else ""
        if self._token:
            self.logger.info("Youku: 已成功获取/确认弹幕签名令牌。")
        else:
            self.logger.warning("Youku: 未能获取到弹幕签名所需的 token cookie (_m_h5_tk)，弹幕获取可能会失败。")
            raise self.TokenExpiredError("无法获取有效的 _m_h5_tk 令牌。")

    def _generate_msg_sign(self, msg_enc: str) -> str:
        s = msg_enc + "MkmC9SoIw6xCkSKHhJ7b5D2r51kBiREr"
        return hashlib.md5(s.encode('utf-8')).hexdigest().lower()

    def _generate_token_sign(self, t: str, app_key: str, data: str) -> str:
        s = "&".join([self._token, t, app_key, data])
        return hashlib.md5(s.encode('utf-8')).hexdigest().lower()

    async def _get_danmu_content_by_mat(self, vid: str, mat: int) -> Optional[List[YoukuComment]]:
        if not self._token:
            self.logger.error("Youku: Cannot get danmaku, _m_h5_tk is missing.")
            return []

        ctime = int(time.time() * 1000)
        msg = {
            "pid": 0, "ctype": 10004, "sver": "3.1.0", "cver": "v1.0",
            "ctime": ctime, "guid": self._cna, "vid": vid, "mat": mat,
            "mcount": 1, "type": 1
        }
        msg_ordered_str = json.dumps(dict(sorted(msg.items())), separators=(',', ':'))
        msg_enc = base64.b64encode(msg_ordered_str.encode('utf-8')).decode('utf-8')
        
        msg['msg'] = msg_enc
        msg['sign'] = self._generate_msg_sign(msg_enc)
        
        app_key = "24679788"
        data_payload = json.dumps(msg, separators=(',', ':'))
        t = str(int(time.time() * 1000))
        
        params = {
            "jsv": "2.7.0",
            "appKey": app_key,
            "t": t,
            "sign": self._generate_token_sign(t, app_key, data_payload),
            "api": "mopen.youku.danmu.list",
            "v": "1.0",
            "type": "originaljson",
            "dataType": "jsonp",
            "timeout": "20000",
            "jsonpIncPrefix": "utility"
        }
        
        url = f"https://acs.youku.com/h5/mopen.youku.danmu.list/1.0/?{urlencode(params)}"
        
        response = await self._request(
            "POST",
            url,
            data={"data": data_payload},
            headers={"Referer": "https://v.youku.com"}
        )
        if await self._should_log_responses():
            scraper_responses_logger.debug(f"Youku Danmaku Segment Response (vid={vid}, mat={mat}): {response.text}")
        response.raise_for_status()

        # 修正：优酷API现在直接返回JSON，而不是JSONP。
        try:
            rpc_result = YoukuRpcResult.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError) as e:
            self.logger.error(f"Youku: 解析外层弹幕响应失败: {e} - 响应: {response.text[:200]}")
            return None

        # 新增：检查API返回的错误信息
        if "SUCCESS" not in rpc_result.ret[0]:
            error_msg = rpc_result.ret[0]
            self.logger.warning(f"Youku API 错误 (vid={vid}, mat={mat}): {error_msg}")
            if "TOKEN_EXOIRED" in error_msg: # 优酷API拼写错误
                raise self.TokenExpiredError()
            # 对于其他错误，例如 "ILLEGAL_ACCESS"，我们返回 None 表示此分段失败
            return None

        # 只有在成功时才解析内层JSON
        if rpc_result.data and rpc_result.data.result:
            try:
                comment_result = YoukuDanmakuResult.model_validate(json.loads(rpc_result.data.result))
                if comment_result.data and comment_result.data.result:
                    return comment_result.data.result
            except (json.JSONDecodeError, ValidationError) as e:
                self.logger.error(f"Youku: 解析内层弹幕结果字符串失败: {e}")
        return None

    def _format_comments(self, comments: List[YoukuComment]) -> List[dict]:
        if not comments:
            return []

        # 新增：按弹幕ID去重
        unique_comments = list({c.id: c for c in comments}.values())

        # 1. 按内容对弹幕进行分组
        grouped_by_content: Dict[str, List[YoukuComment]] = defaultdict(list)
        for c in unique_comments: # 使用去重后的列表
            grouped_by_content[c.content].append(c)

        # 2. 处理重复项
        processed_comments: List[YoukuComment] = []
        for content, group in grouped_by_content.items():
            if len(group) == 1:
                processed_comments.append(group[0])
            else:
                first_comment = min(group, key=lambda x: x.playat)
                first_comment.content = f"{first_comment.content} X{len(group)}"
                processed_comments.append(first_comment)

        formatted = []
        for c in processed_comments:
            mode = 1
            color = 16777215
            
            try:
                props = json.loads(c.propertis)
                prop_model = YoukuCommentProperty.model_validate(props)
                color = prop_model.color
                if prop_model.pos == 1: mode = 5
                elif prop_model.pos == 2: mode = 4
            except (json.JSONDecodeError, ValidationError):
                pass

            timestamp = c.playat / 1000.0
            # 修正：直接在此处添加字体大小 '25'，确保数据源的正确性
            p_string = f"{timestamp:.2f},{mode},25,{color},[{self.provider_name}]"
            formatted.append({"cid": str(c.id), "p": p_string, "m": c.content, "t": round(timestamp, 2)})
        return formatted

    async def get_id_from_url(self, url: str) -> Optional[str]:
        """从优酷视频URL中提取 vid。"""
        # 优酷的URL格式通常是 v.youku.com/v_show/id_XXXXXXXX.html
        # 修正：移除对 .html 后缀的强制要求，以兼容新版URL
        match = re.search(r'id_([a-zA-Z0-9=]+)', url)
        if match:
            vid = match.group(1)
            self.logger.info(f"Youku: 从URL {url} 解析到 vid: {vid}")
            return vid
        self.logger.warning(f"Youku: 无法从URL中解析出 vid: {url}")
        return None

    def format_episode_id_for_comments(self, provider_episode_id: Any) -> str:
        """For Youku, the episode ID is a simple string, so no formatting is needed."""
        return str(provider_episode_id)

    def _extract_media_type_from_response(self, common_data: YoukuSearchCommonData) -> str:
        """从API响应中提取节目类型"""
        # 优先使用 cats 字段
        if common_data.cats:
            cats = common_data.cats.lower()
            if '综艺' in cats or 'variety' in cats:
                return 'variety'
            elif '电影' in cats or 'movie' in cats:
                return 'movie'
            elif '动漫' in cats or 'anime' in cats:
                return 'anime'
            elif '电视剧' in cats or 'drama' in cats:
                return 'drama'
        
        # 备用：从 feature 字段提取
        feature = common_data.feature.lower()
        if '综艺' in feature:
            return 'variety'
        elif '电影' in feature:
            return 'movie'
        elif '动漫' in feature:
            return 'anime'
        elif '电视剧' in feature:
            return 'drama'
        
        # 默认返回综艺
        return 'variety'

    def _format_episode_title(self, ep: YoukuEpisodeInfo, episode_index: int, media_type: str, stage_to_episode: Dict[str, int]) -> str:
        """直接使用API返回的原始标题"""
        return (ep.clean_display_name or ep.title).strip()








