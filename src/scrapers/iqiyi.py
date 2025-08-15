import asyncio
import logging
import aiomysql
import re
import json
from datetime import datetime
from typing import ClassVar
import zlib
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Callable, Union
from collections import defaultdict
import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator, ConfigDict, field_validator

from ..config_manager import ConfigManager
from .. import models
from .base import BaseScraper, get_season_from_title

scraper_responses_logger = logging.getLogger("scraper_responses")

# --- 新增：用于V3 Search API的模型 ---
class IqiyiV3Video(BaseModel):
    title: Optional[str] = None
    pageUrl: Optional[str] = None
    playUrl: Optional[str] = None
    number: Optional[int] = None

class IqiyiV3AlbumInfo(BaseModel):
    title: Optional[str] = None
    qipuId: Optional[str] = None
    playQipuId: Optional[str] = None
    pageUrl: Optional[str] = None
    playUrl: Optional[str] = None
    channel: Optional[str] = None
    img: Optional[str] = None
    imgH: Optional[str] = None
    releaseDate: Optional[str] = None
    btnText: Optional[str] = None
    videos: Optional[List[IqiyiV3Video]] = None
    year: Optional[Dict[str, Any]] = None
    actors: Optional[Dict[str, Any]] = None
    directors: Optional[Dict[str, Any]] = None
    metaTags: Optional[List[Dict[str, Any]]] = None
    people: Optional[List[Dict[str, Any]]] = None
    brief: Optional[Dict[str, Any]] = None

    @field_validator('qipuId', 'playQipuId', mode='before')
    @classmethod
    def _coerce_ids_to_str(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v)

class IqiyiV3Template(BaseModel):
    template: int
    albumInfo: Optional[IqiyiV3AlbumInfo] = None

class IqiyiV3Data(BaseModel):
    templates: List[IqiyiV3Template]

class IqiyiV3SearchResult(BaseModel):
    data: Optional[IqiyiV3Data] = None

# --- Pydantic Models for iQiyi API (部分模型现在仅用于旧缓存兼容或作为新API响应的子集) ---

class IqiyiVideoLibMeta(BaseModel):
    douban_id: Optional[int] = Field(None, alias="douban_id")

class IqiyiSearchVideoInfo(BaseModel):
    item_link: str = Field(alias="itemLink")

class IqiyiSearchAlbumInfo(BaseModel):
    album_id: Optional[int] = Field(None, alias="albumId")
    item_total_number: Optional[int] = Field(None, alias="itemTotalNumber")
    site_id: Optional[str] = Field(None, alias="siteId")
    album_link: Optional[str] = Field(None, alias="albumLink")
    video_doc_type: int = Field(alias="videoDocType")
    album_title: Optional[str] = Field(None, alias="albumTitle")
    channel: Optional[str] = None
    release_date: Optional[str] = Field(None, alias="releaseDate")
    album_img: Optional[str] = Field(None, alias="albumImg")
    video_lib_meta: Optional[IqiyiVideoLibMeta] = Field(None, alias="video_lib_meta")
    videoinfos: Optional[List[IqiyiSearchVideoInfo]] = None

    @property
    def link_id(self) -> Optional[str]:
        link_to_parse = self.album_link
        if self.videoinfos and self.videoinfos[0].item_link and self.album_link:
            link_to_parse = self.videoinfos[0].item_link

        match = re.search(r"v_(\w+?)\.html", link_to_parse)
        return match.group(1).strip() if match else None

    @property
    def year(self) -> Optional[int]:
        if self.release_date and len(self.release_date) >= 4:
            try:
                return int(self.release_date[:4])
            except ValueError:
                return None
        return None

class IqiyiAlbumDoc(BaseModel):
    score: float
    album_doc_info: IqiyiSearchAlbumInfo = Field(alias="albumDocInfo")

class IqiyiSearchDoc(BaseModel):
    docinfos: List[IqiyiAlbumDoc]

class IqiyiSearchResult(BaseModel):
    docinfos: List[IqiyiAlbumDoc]

class IqiyiHtmlAlbumInfo(BaseModel):
    video_count: Optional[int] = Field(None, alias="videoCount")

# 修正：此模型现在用于解析新的 baseinfo API 响应
class IqiyiHtmlVideoInfo(BaseModel):
    # 新增：允许模型通过字段名或别名进行填充，以兼容新旧缓存格式
    model_config = ConfigDict(populate_by_name=True)

    album_id: int = Field(alias="albumId")
    tv_id: Optional[int] = Field(None, alias="tvId")
    video_id: Optional[int] = Field(None, alias="videoId")
    # 修正：新API返回的字段名不同
    video_name: str = Field(alias="name")
    video_url: str = Field(alias="playUrl")
    channel_name: Optional[str] = Field(None, alias="channelName")
    duration: int = Field(alias="durationSec")
    # video_count 不再从此模型获取，但保留字段以兼容旧缓存
    video_count: int = 0 

    @model_validator(mode='after')
    def merge_ids(self) -> 'IqiyiHtmlVideoInfo':
        if self.tv_id is None and self.video_id is not None:
            self.tv_id = self.video_id
        return self

class IqiyiEpisodeInfo(BaseModel):
    tv_id: int = Field(alias="tvId")
    name: str
    order: int
    play_url: str = Field(alias="playUrl")

    @property
    def link_id(self) -> Optional[str]:
        match = re.search(r"v_(\w+?)\.html", self.play_url)
        return match.group(1).strip() if match else None

class IqiyiVideoData(BaseModel):
    epsodelist: List[IqiyiEpisodeInfo]

class IqiyiVideoResult(BaseModel):
    data: IqiyiVideoData

class IqiyiUserInfo(BaseModel):
    uid: str

class IqiyiComment(BaseModel):
    content_id: str = Field(alias="contentId")
    content: str
    show_time: int = Field(alias="showTime")
    color: str
    # user_info 字段在XML中可能不存在，设为可选
    user_info: Optional[IqiyiUserInfo] = Field(None, alias="userInfo")

# --- 新增：用于综艺节目分集获取的模型 ---
class IqiyiAlbumVideoInfo(BaseModel):
    publish_time: int = Field(alias="publishTime")

class IqiyiAlbumBaseInfoData(BaseModel):
    first_video: IqiyiAlbumVideoInfo = Field(alias="firstVideo")
    latest_video: IqiyiAlbumVideoInfo = Field(alias="latestVideo")

class IqiyiAlbumBaseInfoResult(BaseModel):
    data: IqiyiAlbumBaseInfoData

class IqiyiMobileVideo(BaseModel):
    id: int
    vid: str
    short_title: str = Field(alias="shortTitle")
    page_url: str = Field(alias="pageUrl")
    publish_time: int = Field(alias="publishTime")
    duration: str

    @property
    def link_id(self) -> Optional[str]:
        match = re.search(r"v_(\w+?)\.html", self.page_url)
        return match.group(1).strip() if match else None

class IqiyiMobileVideoListData(BaseModel):
    videos: List[IqiyiMobileVideo]

class IqiyiMobileVideoListResult(BaseModel):
    data: IqiyiMobileVideoListData

# --- Main Scraper Class ---

class IqiyiScraper(BaseScraper):
    provider_name = "iqiyi"
    _EPISODE_BLACKLIST_PATTERN = re.compile(r"加更|走心|解忧|纯享", re.IGNORECASE)
    # 新增：用于过滤搜索结果中非正片内容的正则表达式
    _SEARCH_JUNK_TITLE_PATTERN = re.compile(
        r'纪录片|预告|花絮|专访|MV|特辑|演唱会|音乐会|独家|解读|揭秘|赏析|速看|资讯|彩蛋|访谈|番外|短片',
        re.IGNORECASE
    )
    _SEARCH_JUNK_TITLE_PATTERN_V3: ClassVar[re.Pattern] = re.compile(
        r"拍摄花絮|制作花絮|幕后花絮|未播花絮|独家花絮|花絮特辑|"
        r"预告片|先导预告|终极预告|正式预告|官方预告|"
        r"彩蛋片段|删减片段|未播片段|番外彩蛋|"
        r"精彩片段|精彩看点|精彩回顾|精彩集锦|看点解析|看点预告|"
        r"NG镜头|NG花絮|番外篇|番外特辑|制作特辑|拍摄特辑|幕后特辑|导演特辑|演员特辑|片尾曲|插曲|主题曲|背景音乐|OST|音乐MV|歌曲MV|前季回顾|剧情回顾|往期回顾|内容总结|剧情盘点|精选合集|剪辑合集|混剪视频|独家专访|演员访谈|导演访谈|主创访谈|媒体采访|发布会采访|抢先看|抢先版|试看版|即将上线",
        re.IGNORECASE
    )

    def __init__(self, pool: aiomysql.Pool, config_manager: ConfigManager):
        super().__init__(pool, config_manager)
        self.mobile_user_agent = "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Mobile Safari/537.36 Edg/136.0.0.0"
        self.reg_video_info = re.compile(r'"videoInfo":(\{.+?\}),')

        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": self.mobile_user_agent,
                "Referer": "https://www.iqiyi.com/",
            },
            timeout=20.0, follow_redirects=True
        )

    async def close(self):
        await self.client.aclose()

    async def search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        cache_key_suffix = f"_s{episode_info['season']}e{episode_info['episode']}" if episode_info else ""
        cache_key = f"search_{self.provider_name}_{keyword}{cache_key_suffix}"
        cached_results = await self._get_from_cache(cache_key)
        if cached_results is not None:
            self.logger.info(f"爱奇艺: 从缓存中命中搜索结果 '{keyword}{cache_key_suffix}'")
            return [models.ProviderSearchInfo.model_validate(r) for r in cached_results]

        # 方案3 (主): 使用新的 mesh API
        try:
            results_v3 = await self._search_v3(keyword, episode_info)
            if results_v3:
                self.logger.info("爱奇艺: 已通过新版 mesh API 成功获取搜索结果。")
                await self._set_to_cache(cache_key, [r.model_dump() for r in results_v3], 'search_ttl_seconds', 300)
                return results_v3
        except Exception as e:
            self.logger.warning(f"爱奇艺: 新版 mesh API 搜索失败，将尝试备用方案。错误: {e}", exc_info=True)

        # 方案2 (备): 回退到旧的 o API
        self.logger.warning("爱奇艺: 新版 API 失败，正在回退到旧版 o API 进行搜索...")
        results_v2 = await self._search_v2(keyword, episode_info)
        if results_v2:
            await self._set_to_cache(cache_key, [r.model_dump() for r in results_v2], 'search_ttl_seconds', 300)
        return results_v2

    def _determine_content_type_v3(self, channel: Optional[str]) -> str:
        if not channel: return "未知"
        if '电影' in channel: return '电影'
        if '电视剧' in channel: return '电视剧'
        if '综艺' in channel: return '综艺'
        if '动漫' in channel: return '动漫'
        return "未知"

    def _extract_year_v3(self, album_info: IqiyiV3AlbumInfo) -> Optional[int]:
        if album_info.year and album_info.year.get("value"):
            match = re.search(r'(\d{4})', str(album_info.year["value"]))
            if match: return int(match.group(1))
        if album_info.releaseDate:
            match = re.search(r'(\d{4})', album_info.releaseDate)
            if match: return int(match.group(1))
        return None

    def _process_variety_episodes_v3(self, episodes: List[Dict]) -> List[Dict]:
        # 翻译自 JS 中的 processIqiyiVarietyEpisodes
        has_qi_format = any(re.search(r'第\d+期', ep['title']) for ep in episodes)
        if not has_qi_format:
            return episodes

        episode_infos = []
        for ep in episodes:
            title = ep['title']
            qi_up_down_match = re.search(r'第(\d+)期([上下])', title)
            qi_match = re.search(r'第(\d+)期', title) and not qi_up_down_match

            if qi_up_down_match:
                qi_num_str, up_down = qi_up_down_match.groups()
                after_text = title.split(f"第{qi_num_str}期{up_down}", 1)[-1]
                if not re.match(r'^(加更|会员版|纯享版|特别版|独家版|Plus|\+|花絮|预告|彩蛋|抢先|精选|未播|回顾|特辑|幕后)', after_text):
                    episode_infos.append(ep)
            elif qi_match:
                if not re.search(r'(会员版|纯享版|特别版|独家版|加更版|Plus|\+|拍摄花絮|制作花絮|幕后花絮|预告片|先导预告|彩蛋片段|抢先看|抢先版|精选合集|未播花絮|剧情回顾|制作特辑|拍摄特辑|幕后特辑|独家专访|演员访谈|导演访谈|剪辑合集|混剪视频|内容总结|剧情盘点|删减片段|未播片段|NG镜头|NG花絮|番外篇|番外特辑|精彩片段|精彩看点|精彩回顾|看点解析|看点预告|主创访谈|媒体采访|片尾曲|插曲|主题曲|背景音乐|OST|音乐MV|歌曲MV)', title):
                    episode_infos.append(ep)

        def sort_key(ep):
            title = ep['title']
            qi_match = re.search(r'第(\d+)期', title)
            qi_num = int(qi_match.group(1)) if qi_match else 9999
            
            up_down_match = re.search(r'第\d+期([上下])', title)
            part_order = {'上': 1, '下': 2}.get(up_down_match.group(1) if up_down_match else '', 0)
            
            return (qi_num, part_order)

        episode_infos.sort(key=sort_key)
        return episode_infos

    async def _search_v3(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        self.logger.info(f"爱奇艺 (v3): 正在搜索 '{keyword}'...")
        params = {
            'key': keyword, 'current_page': '1', 'mode': '11', 'source': 'input',
            'suggest': '', 'pcv': '13.074.22699', 'version': '13.074.22699',
            'pageNum': '1', 'pageSize': '25', 'u': 'f6440fc5d919dca1aea12b6aff56e1c7',
            'scale': '200', 'vipType': '-1', 'osShortName': 'win10',
            'ad': json.dumps({"lm":3,"azd":1000000000951,"azt":733,"position":"feed"}),
            'adExt': json.dumps({"r":"2.1.5-ares6-pure"})
        }
        headers = {
            'Referer': 'https://www.iqiyi.com/',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 13; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36'
        }
        url = "https://mesh.if.iqiyi.com/portal/lw/search/homePageV3"
        response = await self.client.get(url, params=params, headers=headers)
        response.raise_for_status()
        
        try:
            search_result = IqiyiV3SearchResult.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError) as e:
            self.logger.error(f"爱奇艺 (v3): 解析搜索结果失败: {e} - 响应: {response.text[:200]}")
            return []

        if not search_result.data or not search_result.data.templates:
            return []

        results = []
        for template in search_result.data.templates:
            if template.template not in [101, 102, 103] or not template.albumInfo:
                continue
            
            album = template.albumInfo
            title = re.sub(r'<[^>]+>', '', album.title or '')
            if self._SEARCH_JUNK_TITLE_PATTERN_V3.search(title):
                continue

            content_type_str = self._determine_content_type_v3(album.channel)
            if content_type_str not in ['电影', '电视剧', '综艺']:
                continue

            link_id = None
            if album.pageUrl:
                match = re.search(r"v_(\w+?)\.html", album.pageUrl)
                if match: link_id = match.group(1).strip()
            
            if not link_id: continue

            media_type = "movie" if content_type_str == "电影" else "tv_series"
            
            # --- Pre-fetch and cache episodes ---
            episodes_to_cache = []
            if album.videos:
                parsed_episodes = [{"title": ep.title, "url": ep.pageUrl} for ep in album.videos if ep.title and ep.pageUrl]
                if content_type_str == '综艺':
                    parsed_episodes = self._process_variety_episodes_v3(parsed_episodes)

                for i, ep_data in enumerate(parsed_episodes):
                    ep_link_id_match = re.search(r"v_(\w+?)\.html", ep_data['url'])
                    if ep_link_id_match:
                        ep_link_id = ep_link_id_match.group(1)
                        # We need tvid for get_comments, so we fetch it here
                        tvid = await self._get_tvid_from_link_id(ep_link_id)
                        if tvid:
                            episodes_to_cache.append(models.ProviderEpisodeInfo(
                                provider=self.provider_name,
                                episodeId=tvid,
                                title=ep_data['title'],
                                episodeIndex=i + 1,
                                url=ep_data['url']
                            ))
            
            if episodes_to_cache:
                cache_key = f"episodes_{link_id}"
                await self._set_to_cache(cache_key, [e.model_dump() for e in episodes_to_cache], 'episodes_ttl_seconds', 1800)
            # --- End of episode caching ---

            provider_search_info = models.ProviderSearchInfo(
                provider=self.provider_name,
                mediaId=link_id,
                title=title.replace(":", "："),
                type=media_type,
                season=get_season_from_title(title),
                year=self._extract_year_v3(album),
                imageUrl=album.img or album.imgH,
                episodeCount=len(episodes_to_cache) if episodes_to_cache else None,
                currentEpisodeIndex=episode_info.get("episode") if episode_info else None
            )
            results.append(provider_search_info)

        return results

    async def _search_v2(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """旧版搜索逻辑，作为备用方案。"""
        self.logger.info(f"爱奇艺 (v2): 正在搜索 '{keyword}'...")

        callback_name = f"__jp{int(time.time() * 1000)}"
        params = {
            'if': 'html5', 'key': keyword, 'pageNum': '1', 'pageSize': '20',
            'channel_name': '', 'u': 'c6bb19d4d627271c435442a8da168424', 'pu': '0',
            'video_allow_3rd': '1', 'intent_result_number': '10', 'intent_category_type': '1',
            'vfrm': '2-3-0-1', 'callback': callback_name
        }
        url = f"https://search.video.iqiyi.com/o"
        results = []
        try:
            response = await self.client.get(url, params=params)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"iQiyi Search Response (v2) (keyword='{keyword}'): {response.text}")
            response.raise_for_status()
            
            # --- Correctly handle JSONP response ---
            jsonp_text = response.text
            prefix = f"try{{{callback_name}("
            suffix = ")}}catch(e){}"
            if jsonp_text.startswith(prefix) and jsonp_text.endswith(suffix):
                json_str = jsonp_text[len(prefix):-len(suffix)]
                data = IqiyiSearchResult.model_validate(json.loads(json_str))
            else:
                raise ValueError("响应不是预期的JSONP格式。")
            # --- End of JSONP handling ---

            if not data or not data.docinfos:
                return []

            for doc in data.docinfos:
                if doc.score < 0.7: continue
                
                album = doc.album_doc_info
                if not (album.album_link and "iqiyi.com" in album.album_link and album.site_id == "iqiyi" and album.video_doc_type == 1):
                    continue
                if album.channel and ("原创" in album.channel or "教育" in album.channel or "纪录片" in album.channel):
                    self.logger.debug(f"爱奇艺 (v2): 根据频道 '{album.channel}' 过滤掉 '{album.album_title}'")
                    continue

                if album.album_title and self._SEARCH_JUNK_TITLE_PATTERN.search(album.album_title):
                    self.logger.debug(f"爱奇艺 (v2): 根据标题黑名单过滤掉 '{album.album_title}'")
                    continue

                douban_id = str(album.video_lib_meta.douban_id) if album.video_lib_meta and album.video_lib_meta.douban_id else None
                link_id = album.link_id
                if not link_id: continue

                channel_name = album.channel.split(',')[0] if album.channel else ""
                media_type = "movie" if channel_name == "电影" else "tv_series"

                current_episode = episode_info.get("episode") if episode_info else None
                cleaned_title = re.sub(r'<[^>]+>', '', album.album_title).replace(":", "：") if album.album_title else "未知标题"
                provider_search_info = models.ProviderSearchInfo(
                    provider=self.provider_name, mediaId=link_id, title=cleaned_title,
                    type=media_type, season=get_season_from_title(cleaned_title),
                    year=album.year, imageUrl=album.album_img, douban_id=douban_id,
                    episodeCount=album.item_total_number, currentEpisodeIndex=current_episode,
                )
                results.append(provider_search_info)

        except Exception as e:
            self.logger.error(f"爱奇艺 (v2): 搜索 '{keyword}' 失败: {e}", exc_info=True)

        return results

    async def _get_tvid_from_link_id(self, link_id: str) -> Optional[str]:
        """
        新增：使用官方API将视频链接ID解码为tvid。
        这比解析HTML更可靠。
        """
        api_url = f"https://pcw-api.iq.com/api/decode/{link_id}?platformId=3&modeCode=intl&langCode=sg"
        try:
            response = await self.client.get(api_url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"iQiyi Decode API Response (link_id={link_id}): {response.text}")
            response.raise_for_status()
            data = response.json()
            if data.get("code") in ["A00000", "0"] and data.get("data"):
                return str(data["data"])
            else:
                self.logger.warning(f"爱奇艺: decode API 未成功返回 tvid (link_id: {link_id})。响应: {data}")
                return None
        except Exception as e:
            self.logger.error(f"爱奇艺: 调用 decode API 失败 (link_id: {link_id}): {e}", exc_info=True)
            return None

    async def _get_video_base_info(self, link_id: str) -> Optional[IqiyiHtmlVideoInfo]:
        # 修正：缓存键必须包含分集信息，以区分对同一标题的不同分集搜索
        cache_key = f"base_info_{link_id}"
        cached_info = await self._get_from_cache(cache_key)
        if cached_info is not None:
            self.logger.info(f"爱奇艺: 从缓存中命中基础信息 (link_id={link_id})")
            try:
                return IqiyiHtmlVideoInfo.model_validate(cached_info)
            except ValidationError as e:
                self.logger.error(f"爱奇艺: 缓存的基础信息 (link_id={link_id}) 验证失败。这可能是一个陈旧或损坏的缓存。")
                self.logger.error(f"导致验证失败的数据: {cached_info}")
                self.logger.error(f"Pydantic 验证错误: {e}")
                return None

        # 主方案：使用API获取信息
        tvid = await self._get_tvid_from_link_id(link_id)
        if not tvid:
            return None

        url = f"https://pcw-api.iqiyi.com/video/video/baseinfo/{tvid}"
        try:
            response = await self.client.get(url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"iQiyi BaseInfo Response (tvid={tvid}): {response.text}")
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "A00000" or not data.get("data"):
                self.logger.warning(f"爱奇艺: baseinfo API 未成功返回数据 (tvid: {tvid})。响应: {data}")
                return None
            
            video_info = IqiyiHtmlVideoInfo.model_validate(data["data"])

            info_to_cache = video_info.model_dump()
            await self._set_to_cache(cache_key, info_to_cache, 'base_info_ttl_seconds', 1800)
            return video_info
        except Exception as e:
            self.logger.error(f"爱奇艺: 获取或解析 baseinfo 失败 (tvid: {tvid}): {e}", exc_info=True)
            
        # 备用方案：如果API失败，则尝试解析HTML页面
        self.logger.warning(f"爱奇艺: API获取基础信息失败，正在尝试备用方案 (解析HTML)...")
        try:
            url = f"https://m.iqiyi.com/v_{link_id}.html"
            response = await self.client.get(url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"iQiyi HTML Fallback Response (link_id={link_id}): {response.text}")
            response.raise_for_status()
            html_content = response.text
            match = self.reg_video_info.search(html_content)
            if match:
                video_json_str = match.group(1)
                video_info = IqiyiHtmlVideoInfo.model_validate(json.loads(video_json_str))
                self.logger.info(f"爱奇艺: 备用方案成功解析到视频信息 (link_id={link_id})")
                info_to_cache = video_info.model_dump()
                await self._set_to_cache(cache_key, info_to_cache, 'base_info_ttl_seconds', 1800)
                return video_info
        except Exception as fallback_e:
            self.logger.error(f"爱奇艺: 备用方案 (解析HTML) 也失败了: {fallback_e}", exc_info=True)
            return None

    async def _get_tv_episodes(self, album_id: int, size: int = 500) -> List[IqiyiEpisodeInfo]:
        """
        获取剧集列表，实现主/备API端点回退机制以提高成功率。
        优先尝试国际版API，失败则回退到国内版API。
        """
        endpoints = [
            f"https://pcw-api.iq.com/api/album/album/avlistinfo?aid={album_id}&page=1&size={size}",  # 国际版 (主)
            f"https://pcw-api.iqiyi.com/albums/album/avlistinfo?aid={album_id}&page=1&size={size}"  # 国内版 (备)
        ]

        for i, url in enumerate(endpoints):
            try:
                self.logger.info(f"爱奇艺: 正在尝试从端点 #{i+1} 获取剧集列表 (album_id: {album_id})")
                response = await self.client.get(url)
                if await self._should_log_responses():
                    scraper_responses_logger.debug(f"iQiyi Album List Response (album_id={album_id}, endpoint=#{i+1}): {response.text}")
                response.raise_for_status()
                data = IqiyiVideoResult.model_validate(response.json())
                
                if data.data and data.data.epsodelist:
                    self.logger.info(f"爱奇艺: 从端点 #{i+1} 成功获取 {len(data.data.epsodelist)} 个分集。")
                    return data.data.epsodelist
                
                self.logger.warning(f"爱奇艺: 端点 #{i+1} 未返回分集数据。")
            except Exception as e:
                self.logger.error(f"爱奇艺: 尝试端点 #{i+1} 时发生错误 (album_id: {album_id}): {e}")
        
        self.logger.error(f"爱奇艺: 所有端点均未能获取到剧集列表 (album_id: {album_id})。")
        return []

    async def _get_zongyi_episodes(self, album_id: int) -> List[IqiyiEpisodeInfo]:
        """新增：专门为综艺节目获取分集列表。"""
        self.logger.info(f"爱奇艺: 检测到综艺节目 (album_id={album_id})，使用按月获取策略。")
        try:
            # 1. 获取节目的开播和最新日期
            url = f"https://pcw-api.iqiyi.com/album/album/baseinfo/{album_id}"
            response = await self.client.get(url)
            response.raise_for_status()
            album_base_info = IqiyiAlbumBaseInfoResult.model_validate(response.json()).data
            start_date = datetime.fromtimestamp(album_base_info.first_video.publish_time / 1000)
            end_date = datetime.fromtimestamp(album_base_info.latest_video.publish_time / 1000)

            # 2. 逐月获取分集
            all_videos: List[IqiyiMobileVideo] = []
            # 标准化 current_date 为当月第一天，以进行安全的月份迭代
            current_date = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            while (current_date.year, current_date.month) <= (end_date.year, end_date.month):
                year = current_date.year
                month = f"{current_date.month:02d}"
                month_url = f"https://pub.m.iqiyi.com/h5/main/videoList/source/month/?sourceId={album_id}&year={year}&month={month}"
                
                self.logger.debug(f"爱奇艺 (综艺): 正在获取 {year}-{month} 的分集...")
                month_response = await self.client.get(month_url)
                # 如果某个月份没有数据，API可能返回404或空列表，这都是正常情况
                if month_response.status_code == 200:
                    try:
                        # 响应是 JSONP 格式，需要清理
                        jsonp_text = month_response.text
                        json_text = re.sub(r'^[^{]*\(|\)[^}]*$', '', jsonp_text)
                        month_data = IqiyiMobileVideoListResult.model_validate(json.loads(json_text))
                        if month_data.data and month_data.data.videos:
                            all_videos.extend(month_data.data.videos)
                    except (json.JSONDecodeError, ValidationError) as e:
                        self.logger.warning(f"爱奇艺 (综艺): 解析 {year}-{month} 的分集失败: {e}")
                
                # 移至下一个月
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
                await asyncio.sleep(0.3) # 礼貌性等待

            # 3. 过滤、排序并转换为标准格式
            filtered_videos = [v for v in all_videos if "精编版" not in v.short_title and "会员版" not in v.short_title]
            filtered_videos.sort(key=lambda v: v.publish_time)

            # 4. 异步获取所有分集的 tvid
            tvid_tasks = [self._get_tvid_from_link_id(v.link_id) for v in filtered_videos if v.link_id]
            tvids = await asyncio.gather(*tvid_tasks)
            
            # 5. 构建最终结果
            final_episodes = []
            for i, video in enumerate(filtered_videos):
                tvid = tvids[i]
                if tvid:
                    final_episodes.append(IqiyiEpisodeInfo(tvId=int(tvid), name=video.short_title, order=i + 1, playUrl=video.page_url))
            
            return final_episodes

        except Exception as e:
            self.logger.error(f"爱奇艺: 获取综艺分集列表失败 (album_id={album_id}): {e}", exc_info=True)
            return []

    async def get_episodes(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        cache_key = f"episodes_{media_id}"
        # 仅当不是强制模式（即初次导入）且请求完整列表时才使用缓存
        if target_episode_index is None and db_media_type is None:
            cached_episodes = await self._get_from_cache(cache_key)
            if cached_episodes is not None:
                self.logger.info(f"爱奇艺: 从缓存中命中分集列表 (media_id={media_id})")
                return [models.ProviderEpisodeInfo.model_validate(e) for e in cached_episodes]

        base_info = await self._get_video_base_info(media_id)
        if base_info is None:
            return []

        # 修正：更灵活地决定处理模式
        channel = base_info.channel_name or ""
        is_movie_mode = db_media_type == "movie" or (db_media_type is None and channel == "电影")
        is_zongyi_mode = db_media_type == "tv_series" and channel == "综艺"

        if is_movie_mode:
            # 单集（电影）处理逻辑
            episode_data = {
                "tvId": base_info.tv_id or 0,
                "name": base_info.video_name,
                "order": 1,
                "playUrl": base_info.video_url
            }
            episodes: List[IqiyiEpisodeInfo] = [IqiyiEpisodeInfo.model_validate(episode_data)]
        else:
            # 对于电视剧和综艺节目，优先尝试标准剧集接口
            episodes = await self._get_tv_episodes(base_info.album_id)

            # 如果标准接口未返回任何分集，则尝试使用综艺接口作为备用方案
            if not episodes:
                self.logger.info(f"爱奇艺: 标准剧集接口未返回分集，尝试使用综艺节目接口作为备用方案 (album_id={base_info.album_id})。")
                episodes = await self._get_zongyi_episodes(base_info.album_id)

            if target_episode_index:
                target_episode_from_list = next((ep for ep in episodes if ep.order == target_episode_index), None)
                if target_episode_from_list:
                    episodes = [target_episode_from_list]
                else:
                    self.logger.warning(f"爱奇艺: 目标分集 {target_episode_index} 在获取的列表中未找到 (album_id={base_info.album_id})")
                    return []

            self.logger.debug(f"爱奇艺: 正在为 {len(episodes)} 个分集并发获取真实标题...")
            tasks = [self._get_video_base_info(ep.link_id) for ep in episodes if ep.link_id]
            detailed_infos = await asyncio.gather(*tasks, return_exceptions=True)

            specific_title_map = {}
            for info in detailed_infos:
                if isinstance(info, IqiyiHtmlVideoInfo) and info.tv_id:
                    specific_title_map[info.tv_id] = info.video_name

            for ep in episodes:
                specific_title = specific_title_map.get(ep.tv_id)
                if specific_title and specific_title != ep.name:
                    self.logger.debug(f"爱奇艺: 标题替换: '{ep.name}' -> '{specific_title}'")
                    ep.name = specific_title

        provider_episodes = [
            models.ProviderEpisodeInfo(
                provider=self.provider_name,
                episodeId=str(ep.tv_id), # Use tv_id for danmaku
                title=ep.name,
                episodeIndex=ep.order,
                url=ep.play_url
            ) for ep in episodes if ep.link_id
        ]

        # 应用自定义黑名单和内置黑名单
        blacklist_pattern = await self.get_episode_blacklist_pattern()
        if blacklist_pattern:
            original_count = len(provider_episodes)
            provider_episodes = [ep for ep in provider_episodes if not blacklist_pattern.search(ep.title)]
            filtered_count = original_count - len(provider_episodes)
            if filtered_count > 0:
                self.logger.info(f"Iqiyi: 根据自定义黑名单规则过滤掉了 {filtered_count} 个分集。")
        
        # 根据黑名单过滤分集
        if self._EPISODE_BLACKLIST_PATTERN:
            original_count = len(provider_episodes)
            provider_episodes = [ep for ep in provider_episodes if not self._EPISODE_BLACKLIST_PATTERN.search(ep.title)]
            filtered_count = original_count - len(provider_episodes)
            if filtered_count > 0:
                self.logger.info(f"Iqiyi: 根据黑名单规则过滤掉了 {filtered_count} 个分集。")

        # 仅当不是强制模式且获取完整列表时才进行缓存
        if target_episode_index is None and db_media_type is None and provider_episodes:
            episodes_to_cache = [e.model_dump() for e in provider_episodes]
            await self._set_to_cache(cache_key, episodes_to_cache, 'episodes_ttl_seconds', 1800)
        return provider_episodes

    async def _get_duration_for_tvid(self, tvid: str) -> Optional[int]:
        """新增：为指定的tvid获取视频时长。"""
        url = f"https://pcw-api.iqiyi.com/video/video/baseinfo/{tvid}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "A00000" and data.get("data"):
                return data["data"].get("durationSec")
        except Exception as e:
            self.logger.warning(f"爱奇艺: 获取视频时长失败 (tvid={tvid}): {e}")
        return None

    async def _get_danmu_content_by_mat(self, tv_id: str, mat: int) -> List[IqiyiComment]:
        if len(tv_id) < 4: return []
        
        s1 = tv_id[-4:-2]
        s2 = tv_id[-2:]
        url = f"http://cmts.iqiyi.com/bullet/{s1}/{s2}/{tv_id}_300_{mat}.z"
        
        try:
            response = await self.client.get(url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"iQiyi Danmaku Segment Response (tvId={tv_id}, mat={mat}): status={response.status_code}")
            if response.status_code == 404:
                self.logger.info(f"爱奇艺: 找不到 tvId {tv_id} 的弹幕分段 {mat}，停止获取。")
                return [] # 404 means no more segments
            response.raise_for_status()

            # 根据用户的反馈，恢复为标准的 zlib 解压方式。
            decompressed_data = zlib.decompress(response.content)

            # 增加显式的UTF-8解析器以提高健壮性
            parser = ET.XMLParser(encoding="utf-8")
            root = ET.fromstring(decompressed_data, parser=parser)
            
            comments = []
            # 关键修复：根据日志，弹幕信息在 <bulletInfo> 标签内
            for item in root.findall('.//bulletInfo'):
                content_node = item.find('content')
                show_time_node = item.find('showTime')

                # 核心字段必须存在
                if not (content_node is not None and content_node.text and show_time_node is not None and show_time_node.text):
                    continue
                
                # 安全地获取可选字段
                content_id_node = item.find('contentId')
                color_node = item.find('color')
                user_info_node = item.find('userInfo')
                uid_node = user_info_node.find('uid') if user_info_node is not None else None

                comments.append(IqiyiComment(
                    contentId=content_id_node.text if content_id_node is not None and content_id_node.text else "0",
                    content=content_node.text,
                    showTime=int(show_time_node.text),
                    color=color_node.text if color_node is not None and color_node.text else "ffffff",
                    userInfo=IqiyiUserInfo(uid=uid_node.text) if uid_node is not None and uid_node.text else None
                ))
            return comments
        except zlib.error:
            self.logger.warning(f"爱奇艺: 解压 tvId {tv_id} 的弹幕分段 {mat} 失败，文件可能为空或已损坏。")
        except ET.ParseError:
            self.logger.warning(f"爱奇艺: 解析 tvId {tv_id} 的弹幕分段 {mat} 的XML失败。")
        except Exception as e:
            self.logger.error(f"爱奇艺: 获取 tvId {tv_id} 的弹幕分段 {mat} 时出错: {e}", exc_info=True)
        
        return []

    async def get_comments(self, episode_id: str, progress_callback: Optional[Callable] = None) -> List[dict]:
        tv_id = episode_id # For iqiyi, episodeId is tvId
        all_comments = []
        
        # 优化：先获取视频总时长，以确定需要请求多少个分段
        duration = await self._get_duration_for_tvid(tv_id)
        if duration and duration > 0:
            total_mats = (duration // 300) + 1
            self.logger.info(f"爱奇艺: 视频时长 {duration}s, 预计弹幕分段数: {total_mats}")
        else:
            total_mats = 100 # 如果获取时长失败，回退到旧的固定循环次数
            self.logger.warning(f"爱奇艺: 未能获取视频时长，将使用默认循环次数 ({total_mats})。")

        for mat in range(1, total_mats + 1):
            if progress_callback:
                progress = int((mat / total_mats) * 100) if total_mats > 0 else 100
                await progress_callback(progress, f"正在获取第 {mat}/{total_mats} 分段")

            comments_in_mat = await self._get_danmu_content_by_mat(tv_id, mat)
            if not comments_in_mat:
                break
            all_comments.extend(comments_in_mat)
            await asyncio.sleep(0.2) # Be nice to the server

        if progress_callback:
            await progress_callback(100, "弹幕整合完成")

        return self._format_comments(all_comments)

    def _format_comments(self, comments: List[IqiyiComment]) -> List[dict]:
        if not comments:
            return []

        # 新增：按 content_id 去重
        unique_comments_map: Dict[str, IqiyiComment] = {}
        for c in comments:
            # 保留第一次出现的弹幕
            if c.content_id not in unique_comments_map:
                unique_comments_map[c.content_id] = c
        
        unique_comments = list(unique_comments_map.values())

        # 1. 按内容对弹幕进行分组
        grouped_by_content: Dict[str, List[IqiyiComment]] = defaultdict(list)
        for c in unique_comments: # 使用去重后的列表
            grouped_by_content[c.content].append(c)

        # 2. 处理重复项
        processed_comments: List[IqiyiComment] = []
        for content, group in grouped_by_content.items():
            if len(group) == 1:
                processed_comments.append(group[0])
            else:
                first_comment = min(group, key=lambda x: x.show_time)
                first_comment.content = f"{first_comment.content} X{len(group)}"
                processed_comments.append(first_comment)

        # 3. 格式化处理后的弹幕列表
        formatted = []
        for c in processed_comments:
            mode = 1 # Default scroll
            try:
                color = int(c.color, 16)
            except (ValueError, TypeError):
                color = 16777215 # Default white

            timestamp = float(c.show_time)
            p_string = f"{timestamp:.2f},{mode},{color},[{self.provider_name}]"
            formatted.append({
                "cid": c.content_id,
                "p": p_string,
                "m": c.content,
                "t": timestamp
            })
        return formatted

    async def get_tvid_from_url(self, url: str) -> Optional[str]:
        """
        从爱奇艺视频URL中提取 tvid。
        """
        link_id_match = re.search(r"v_(\w+?)\.html", url)
        if not link_id_match:
            self.logger.warning(f"爱奇艺: 无法从URL中解析出 link_id: {url}")
            return None
        
        link_id = link_id_match.group(1)
        base_info = await self._get_video_base_info(link_id)
        if base_info and base_info.tv_id:
            self.logger.info(f"爱奇艺: 从URL {url} 解析到 tvid: {base_info.tv_id}")
            return str(base_info.tv_id)
        
        self.logger.warning(f"爱奇艺: 未能从 link_id '{link_id}' 获取到 tvid。")
        return None
