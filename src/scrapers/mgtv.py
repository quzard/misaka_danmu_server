import asyncio
import logging
import time
import re
from typing import Any, Callable, Dict, List, Optional

import aiomysql
import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config_manager import ConfigManager
from .. import models, crud
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


# --- 新增：用于V2详情API的模型 ---
class MgtvV2EpisodeCorner(BaseModel):
    text: Optional[str] = None

class MgtvV2Episode(BaseModel):
    url: str
    title: str
    desc: Optional[List[str]] = None
    right_bottom_corner: Optional[MgtvV2EpisodeCorner] = Field(None, alias="rightBottomCorner")
    right_top_corner: Optional[MgtvV2EpisodeCorner] = Field(None, alias="rightTopCorner")

class MgtvV2ContentItem(BaseModel):
    type: str
    data: List[MgtvV2Episode]

class MgtvV2DetailsData(BaseModel):
    contents: List[MgtvV2ContentItem]

class MgtvV2DetailsResult(BaseModel):
    data: MgtvV2DetailsData

# --- 旧版API模型 ---

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

    # English keywords that often appear as standalone acronyms or words
    _ENG_JUNK = r'NC|OP|ED|SP|OVA|OAD|CM|PV|MV|BDMenu|Menu|Bonus|Recap|Teaser|Trailer|Preview|CD|Disc|Scan|Sample|Logo|Info|EDPV|SongSpot|BDSpot'
    # Chinese keywords that are often embedded in titles.
    _CN_JUNK = r'特典|预告|广告|菜单|花絮|特辑|速看|资讯|彩蛋|直拍|直播回顾|片头|片尾|幕后|映像|番外篇|纪录片|访谈|番外|短片|加更|走心|解忧|纯享'

    _JUNK_TITLE_PATTERN = re.compile(
        r'(\[|\【|\b)(' + _ENG_JUNK + r')(\d{1,2})?(\s|_ALL)?(\]|\】|\b)|(' + _CN_JUNK + r')',
        re.IGNORECASE
    )


    def __init__(self, pool: aiomysql.Pool, config_manager: ConfigManager):
        super().__init__(pool, config_manager)
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.mgtv.com/",
                "Sec-Fetch-Site": "same-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            timeout=20.0,
            follow_redirects=True
        )
        self._api_lock = asyncio.Lock()
        self._last_request_time = 0
        # 根据用户反馈，0.5秒的请求间隔在某些网络环境下仍然过快，
        # 适当增加延迟以提高稳定性。
        self._min_interval = 0.8

    async def _request_with_rate_limit(self, method: str, url: str, **kwargs) -> httpx.Response:
        async with self._api_lock:
            now = time.time()
            time_since_last = now - self._last_request_time
            if time_since_last < self._min_interval:
                await asyncio.sleep(self._min_interval - time_since_last)
            response = await self.client.request(method, url, **kwargs)
            self._last_request_time = time.time()
            return response

    async def close(self):
        await self.client.aclose()

    async def search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        self.logger.info(f"MGTV: 正在搜索 '{keyword}'...")
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

                            # 新增：使用正则表达式过滤掉预告、花絮等非正片内容
                            if self._JUNK_TITLE_PATTERN.search(item.title):
                                self.logger.debug(f"MGTV: 过滤掉非正片内容: '{item.title}'")
                                continue

                            if not item.id:
                                continue
                            
                            media_type = "movie" if item.type_name == "电影" else "tv_series"
                            
                            provider_search_info = models.ProviderSearchInfo(
                                provider=self.provider_name,
                                mediaId=item.id,
                                title=item.title.replace(":", "："),
                                type=media_type,
                                season=get_season_from_title(item.title),
                                year=item.year,
                                imageUrl=item.img,
                                # 搜索结果中不包含总集数，设为None
                                episodeCount=None,
                                currentEpisodeIndex=episode_info.get("episode") if episode_info else None
                            )
                            results.append(provider_search_info)
                        except ValidationError:
                            # 安全地跳过不符合我们期望结构的项目（如广告、按钮等）
                            self.logger.debug(f"MGTV: 跳过一个不符合预期的搜索结果项: {item_dict}")
                            continue
            
            self.logger.info(f"MGTV: 搜索 '{keyword}' 完成，找到 {len(results)} 个结果。")
            if results:
                log_results = "\n".join([f"  - {r.title} (ID: {r.mediaId}, 类型: {r.type}, 年份: {r.year or 'N/A'})" for r in results])
                self.logger.info(f"MGTV: 搜索结果列表:\n{log_results}")
            return results
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            self.logger.warning(f"MGTV: 搜索 '{keyword}' 时连接超时或网络错误: {e}")
            return []
        except Exception as e:
            self.logger.error(f"MGTV: 搜索 '{keyword}' 失败: {e}", exc_info=True)
            return []

    async def get_episodes(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        """
        获取分集列表。
        优先使用新的移动端API (v2)，如果失败或未返回结果，则回退到旧的PC端API (v1)。
        """
        # 方案一：使用新的移动端API
        try:
            episodes_v2 = await self._get_episodes_v2(media_id)
            if episodes_v2:
                self.logger.info("MGTV: 已通过新版移动API成功获取分集。")
                
                # 应用通用过滤和目标集数选择
                blacklist_pattern = await self.get_episode_blacklist_pattern()
                if blacklist_pattern:
                    original_count = len(episodes_v2)
                    episodes_v2 = [ep for ep in episodes_v2 if not blacklist_pattern.search(ep.title)]
                    if original_count - len(episodes_v2) > 0:
                        self.logger.info(f"Mgtv: 根据自定义黑名单规则过滤掉了 {original_count - len(episodes_v2)} 个分集。")

                if target_episode_index:
                    return [ep for ep in episodes_v2 if ep.episodeIndex == target_episode_index]
                return episodes_v2
        except Exception as e:
            self.logger.warning(f"MGTV: 新版移动API获取分集失败，将尝试备用方案。错误: {e}", exc_info=True)

        # 方案二：回退到旧的PC端API
        self.logger.warning("MGTV: 新版API失败，正在回退到旧版PC API获取分集...")
        return await self._get_episodes_v1(media_id, target_episode_index, db_media_type)

    async def _get_episodes_v2(self, collection_id: str) -> List[models.ProviderEpisodeInfo]:
        """
        新的分集获取逻辑，基于移动端API，能更好地处理综艺节目。
        """
        # 修正：uuid 和 cid 都可以使用 collection_id。无需从页面解析。
        uuid = collection_id
        cid = collection_id

        # 请求详情API
        callback_name = f"jsonp_{int(time.time() * 1000)}"
        params = {
            "listItems": 0, "uuid": uuid, "cid": collection_id, "ic": 1, "abroad": 0,
            "_support": '10000000000000000', "isHttps": 1, "callback": callback_name
        }
        details_url = "https://mobileso.bz.mgtv.com/msite/videos/v2"
        details_resp = await self._request_with_rate_limit("GET", details_url, params=params)
        details_resp.raise_for_status()

        # 3. 解析JSONP响应
        jsonp_text = details_resp.text
        prefix = f"{callback_name}("
        if not jsonp_text.startswith(prefix):
            raise ValueError("无效的JSONP响应格式。")
        json_str = jsonp_text[len(prefix):-1]
        details_data = MgtvV2DetailsResult.model_validate(json.loads(json_str))

        if not details_data.data or not details_data.data.contents:
            return []

        # 4. 解析分集
        raw_episodes = []
        for content in details_data.data.contents:
            if content.type == 'jcross' and content.data: # 电视剧
                for ep_data in content.data:
                    if ep_data.url and ep_data.title and not (ep_data.right_top_corner and ep_data.right_top_corner.text == '预'):
                        ep_num = self._parse_episode_number_from_title(ep_data.title)
                        if ep_num > 0:
                            raw_episodes.append({"episode": ep_num, "title": f"第{ep_num}集", "url": f"https://www.mgtv.com{ep_data.url}"})
            elif content.type == 'dvideo' and content.data: # 综艺
                for ep_data in content.data:
                    if ep_data.url and ep_data.title and not self._JUNK_TITLE_PATTERN.search(ep_data.title):
                        variety_info = self._parse_variety_info(ep_data)
                        if variety_info:
                            raw_episodes.append(variety_info)
        
        # 5. 排序和格式化
        return self._process_and_format_episodes(raw_episodes)

    def _parse_episode_number_from_title(self, title: str) -> int:
        if not title: return 0
        match = re.search(r'第(\d+)集', title) or re.match(r'^(\d+)$', title)
        return int(match.group(1)) if match else 0

    def _parse_variety_info(self, ep_data: MgtvV2Episode) -> Optional[Dict]:
        desc = (ep_data.desc[0] if ep_data.desc else "") or ep_data.title
        publish_date = ep_data.right_bottom_corner.text if ep_data.right_bottom_corner else ""
        
        # 优先匹配 "第N期上/下"
        match = re.search(r'第(\d+)期([上下])', desc)
        if match:
            return {"episode": float(f"{match.group(1)}.{'1' if match.group(2) == '上' else '2'}"), "title": f"第{match.group(1)}期{match.group(2)}", "publishDate": publish_date}
        
        # 匹配 "第N期"
        match = re.search(r'第(\d+)期', desc)
        if match:
            return {"episode": int(match.group(1)), "title": desc, "publishDate": publish_date}
        
        # 回退到使用发布日期排序
        return {"episode": 9999, "title": desc, "publishDate": publish_date}

    def _process_and_format_episodes(self, raw_episodes: List[Dict]) -> List[models.ProviderEpisodeInfo]:
        if not raw_episodes: return []

        # 检查是否为综艺（通过是否存在publishDate判断）
        is_variety = any('publishDate' in ep for ep in raw_episodes)

        if is_variety:
            # 综艺排序：按期数升序，期数相同则按上下部升序
            raw_episodes.sort(key=lambda x: (x['episode'], x.get('publishDate', '')))
        else:
            # 电视剧排序：按集数升序
            raw_episodes.sort(key=lambda x: x['episode'])

        # 去重并格式化
        final_episodes = []
        seen_indices = set()
        for i, ep in enumerate(raw_episodes):
            ep_index = i + 1
            if ep_index in seen_indices: continue
            
            final_episodes.append(models.ProviderEpisodeInfo(
                provider=self.provider_name,
                episodeId=ep['url'].split('/')[-1].replace('.html', ''), # 从URL提取vid
                title=ep['title'],
                episodeIndex=ep_index,
                url=ep['url']
            ))
            seen_indices.add(ep_index)
        
        return final_episodes

    async def _get_episodes_v1(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        """旧版分集获取逻辑，作为备用方案。"""
        self.logger.info(f"MGTV (v1): 正在为 media_id={media_id} 获取分集列表...")

        # 仅当请求完整列表时才使用缓存
        cache_key = f"episodes_v1_{media_id}"
        if target_episode_index is None:
            cached_episodes = await self._get_from_cache(cache_key)
            if cached_episodes is not None:
                return [models.ProviderEpisodeInfo.model_validate(e) for e in cached_episodes]

        all_episodes: List[MgtvEpisode] = []
        month = ""
        page_index = 0
        total_pages = 1

        try:
            while page_index < total_pages:
                url = f"https://pcweb.api.mgtv.com/variety/showlist?allowedRC=1&collection_id={media_id}&month={month}&page=1&_support=10000000"
                response = await self._request_with_rate_limit("GET", url)
                if await self._should_log_responses():
                    scraper_responses_logger.debug(f"MGTV Episodes Response (v1) (media_id={media_id}, month={month}): {response.text}")
                response.raise_for_status()
                result = MgtvEpisodeListResult.model_validate(response.json())

                if result.data and result.data.list:
                    all_episodes.extend([ep for ep in result.data.list if ep.source_clip_id == media_id])

                if page_index == 0:
                    total_pages = len(result.data.tabs) if result.data and result.data.tabs else 1
                
                page_index += 1
                if page_index < total_pages and result.data and result.data.tabs:
                    month = result.data.tabs[page_index].month
                else:
                    break

            filtered_episodes = []
            for ep in all_episodes:
                title_to_check = ep.title3 or ep.title
                if self._JUNK_TITLE_PATTERN.search(title_to_check):
                    self.logger.debug(f"MGTV (v1): 过滤掉非正片内容: '{title_to_check}'")
                    continue
                filtered_episodes.append(ep)

            def get_sort_keys(episode: MgtvEpisode) -> tuple:
                ep_num_match = re.search(r'第(\d+)集', episode.title2)
                ep_num = int(ep_num_match.group(1)) if ep_num_match else float('inf')
                timestamp = episode.timestamp or "9999-99-99 99:99:99.9"
                return (ep_num, timestamp)

            sorted_episodes = sorted(filtered_episodes, key=get_sort_keys)
            
            provider_episodes = [
                models.ProviderEpisodeInfo(
                    provider=self.provider_name,
                    episodeId=f"{media_id},{ep.video_id}",
                    title=f"{ep.title2} {ep.title}".strip(),
                    episodeIndex=i + 1,
                    url=f"https://www.mgtv.com/b/{media_id}/{ep.video_id}.html"
                ) for i, ep in enumerate(sorted_episodes)
            ]

            if target_episode_index is None:
                await self._set_to_cache(cache_key, [e.model_dump() for e in provider_episodes], 'episodes_ttl_seconds', 1800)

            if target_episode_index:
                return [ep for ep in provider_episodes if ep.episodeIndex == target_episode_index]
            
            return provider_episodes

        except Exception as e:
            self.logger.error(f"MGTV (v1): 获取分集列表失败 (media_id={media_id}): {e}", exc_info=True)
            return []

    async def get_episodes(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        self.logger.info(f"MGTV: 正在为 media_id={media_id} 获取分集列表...")
        
    async def get_comments(self, episode_id: str, progress_callback: Optional[Callable] = None) -> List[dict]:
        try:
            cid, vid = episode_id.split(',')
        except (ValueError, IndexError):
            self.logger.error(f"MGTV: 无效的 episode_id 格式: '{episode_id}'")
            return []

        self.logger.info(f"MGTV: 正在为 cid={cid}, vid={vid} 获取弹幕...")

        # Strategy 1: Use getctlbarrage
        try:
            ctl_url = f"https://galaxy.bz.mgtv.com/getctlbarrage?version=8.1.39&abroad=0&uuid=&os=10.15.7&platform=0&mac=&vid={vid}&pid=&cid={cid}&ticket="
            ctl_response = await self._request_with_rate_limit("GET", ctl_url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"MGTV Control Barrage Response (cid={cid}, vid={vid}): {ctl_response.text}")
            ctl_response.raise_for_status()
            ctl_result = MgtvControlBarrageResult.model_validate(ctl_response.json())

            if ctl_result.data and ctl_result.data.cdn_version:
                self.logger.info("MGTV: 使用主策略 (getctlbarrage) 获取弹幕。")
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
            self.logger.warning(f"MGTV: 主弹幕获取策略失败，将尝试备用策略。错误: {e}")

        # Strategy 2: Fallback to opbarrage
        self.logger.info("MGTV: 使用备用策略 (opbarrage) 获取弹幕。")
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

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            self.logger.warning(f"MGTV: 获取弹幕失败 (episode_id={episode_id})，连接超时或网络错误: {e}")
            return []
        except Exception as e:
            self.logger.error(f"MGTV: 备用弹幕获取策略失败 (episode_id={episode_id}): {e}", exc_info=True)
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
            p_string = f"{timestamp:.3f},{mode},{color},[{self.provider_name}]"
            
            formatted_comments.append({
                "cid": str(c.id),
                "p": p_string,
                "m": c.content,
                "t": round(timestamp, 2)
            })
        return formatted_comments

    async def get_ids_from_url(self, url: str) -> Optional[Dict[str, str]]:
        """从芒果TV URL中提取 collection_id 和 video_id。"""
        match = re.search(r'/b/(\d+)/(\d+)\.html', url)
        if match:
            cid, vid = match.groups()
            self.logger.info(f"MGTV: 从URL {url} 解析到 cid={cid}, vid={vid}")
            return {"cid": cid, "vid": vid}
        self.logger.warning(f"MGTV: 无法从URL中解析出 cid 和 vid: {url}")
        return None
