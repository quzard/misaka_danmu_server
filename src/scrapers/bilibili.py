import asyncio
import logging
import re
import time
import hashlib
import html
import json
from urllib.parse import urlencode
from typing import Any, Callable, Dict, List, Optional, Union
from datetime import datetime
from collections import defaultdict

import aiomysql
import httpx
from pydantic import BaseModel, Field, ValidationError

# --- Start of merged dm_dynamic.py content ---
# This block dynamically generates the Protobuf message classes required for Bilibili's danmaku API.
# It's placed here to encapsulate the logic within the only scraper that uses it,
# simplifying the project structure by removing the need for a separate dm_dynamic.py file.
from google.protobuf.descriptor_pb2 import FileDescriptorProto
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import MessageFactory

# 1. Create a FileDescriptorProto object, which is a protobuf message itself.
# This describes the .proto file in a structured way.
file_descriptor_proto = FileDescriptorProto()
file_descriptor_proto.name = 'dm.proto'
file_descriptor_proto.package = 'biliproto.community.service.dm.v1'
file_descriptor_proto.syntax = 'proto3'

# 2. Define the 'DanmakuElem' message
danmaku_elem_desc = file_descriptor_proto.message_type.add()
danmaku_elem_desc.name = 'DanmakuElem'
danmaku_elem_desc.field.add(name='id', number=1, type=3)  # TYPE_INT64
danmaku_elem_desc.field.add(name='progress', number=2, type=5)  # TYPE_INT32
danmaku_elem_desc.field.add(name='mode', number=3, type=5)  # TYPE_INT32
danmaku_elem_desc.field.add(name='fontsize', number=4, type=5)  # TYPE_INT32
danmaku_elem_desc.field.add(name='color', number=5, type=13)  # TYPE_UINT32
danmaku_elem_desc.field.add(name='midHash', number=6, type=9)  # TYPE_STRING
danmaku_elem_desc.field.add(name='content', number=7, type=9)  # TYPE_STRING
danmaku_elem_desc.field.add(name='ctime', number=8, type=3)  # TYPE_INT64
danmaku_elem_desc.field.add(name='weight', number=9, type=5)  # TYPE_INT32
danmaku_elem_desc.field.add(name='action', number=10, type=9)  # TYPE_STRING
danmaku_elem_desc.field.add(name='pool', number=11, type=5)  # TYPE_INT32
danmaku_elem_desc.field.add(name='idStr', number=12, type=9)  # TYPE_STRING
danmaku_elem_desc.field.add(name='attr', number=13, type=5)  # TYPE_INT32
danmaku_elem_desc.field.add(name='animation', number=14, type=9) # TYPE_STRING
danmaku_elem_desc.field.add(name='like_num', number=15, type=13) # TYPE_UINT32
danmaku_elem_desc.field.add(name='color_v2', number=16, type=9) # TYPE_STRING
danmaku_elem_desc.field.add(name='dm_type_v2', number=17, type=13) # TYPE_UINT32

# 3. Define the 'Flag' message
flag_desc = file_descriptor_proto.message_type.add()
flag_desc.name = 'Flag'
flag_desc.field.add(name='value', number=1, type=5)  # TYPE_INT32
flag_desc.field.add(name='description', number=2, type=9)  # TYPE_STRING

# 4. Define the 'DmSegMobileReply' message
dm_seg_reply_desc = file_descriptor_proto.message_type.add()
dm_seg_reply_desc.name = 'DmSegMobileReply'
elems_field = dm_seg_reply_desc.field.add(name='elems', number=1, type=11, type_name='.biliproto.community.service.dm.v1.DanmakuElem')
elems_field.label = 3  # LABEL_REPEATED
dm_seg_reply_desc.field.add(name='state', number=2, type=5)  # TYPE_INT32
ai_flag_field = dm_seg_reply_desc.field.add(name='ai_flag_for_summary', number=3, type=11, type_name='.biliproto.community.service.dm.v1.Flag')

# 5. Build the descriptors and create message classes
pool = DescriptorPool()
pool.Add(file_descriptor_proto)
factory = MessageFactory(pool)

# 6. Get the prototype message classes using the hashable descriptors
danmaku_elem_descriptor = pool.FindMessageTypeByName('biliproto.community.service.dm.v1.DanmakuElem')
flag_descriptor = pool.FindMessageTypeByName('biliproto.community.service.dm.v1.Flag')
dm_seg_reply_descriptor = pool.FindMessageTypeByName('biliproto.community.service.dm.v1.DmSegMobileReply')
DanmakuElem = factory.GetPrototype(danmaku_elem_descriptor)
Flag = factory.GetPrototype(flag_descriptor)
DmSegMobileReply = factory.GetPrototype(dm_seg_reply_descriptor)
# --- End of merged dm_dynamic.py content ---

from .. import models
from .base import BaseScraper, get_season_from_title

# --- Pydantic Models for Bilibili API ---

class BiliSearchMedia(BaseModel):
    media_id: Optional[int] = None
    season_id: Optional[int] = None
    title: str
    pubtime: Optional[int] = 0
    pubdate: Union[str, int, None] = None
    season_type_name: Optional[str] = Field(None, alias="season_type_name")
    ep_size: Optional[int] = None
    bvid: Optional[str] = None
    goto_url: Optional[str] = None
    cover: Optional[str] = None

# This model is now for the typed search result
class BiliSearchData(BaseModel):
    result: Optional[List[BiliSearchMedia]] = None

# This is the generic API result wrapper
class BiliApiResult(BaseModel):
    code: int
    message: str
    data: Optional[BiliSearchData] = None

class BiliEpisode(BaseModel):
    id: int  # ep_id
    aid: int
    cid: int
    bvid: str
    title: str
    long_title: str

class BiliSeasonData(BaseModel):
    episodes: List[BiliEpisode]

class BiliSeasonResult(BaseModel):
    code: int
    message: str
    result: Optional[BiliSeasonData] = None

class BiliVideoPart(BaseModel):
    cid: int
    page: int
    part: str

class BiliVideoViewData(BaseModel):
    bvid: str
    aid: int
    title: str
    pic: str
    pages: List[BiliVideoPart]

class BiliVideoViewResult(BaseModel):
    code: int
    message: str
    data: Optional[BiliVideoViewData] = None

class BuvidData(BaseModel):
    buvid: str

class BuvidResponse(BaseModel):
    code: int
    data: Optional[BuvidData] = None

# --- Main Scraper Class ---

class BilibiliScraper(BaseScraper):
    provider_name = "bilibili"

    # Regex to filter out non-main content like specials, trailers, etc.
    # Based on user-provided rules.
    _JUNK_TITLE_PATTERN = re.compile(
        r'(\[|\【|\b)(NC)?(OP|ED|SP|OVA|OAD|CM|PV|MV|BDMenu|Menu|Bonus|Recap|Teaser|Trailer|Preview|特典|预告|广告|菜单|花絮|特辑|速看|资讯|彩蛋|直拍|直播回顾|片头|片尾|映像|CD|Disc|Scan|Sample|Logo|Info|EDPV|SongSpot|BDSpot)(\d{1,2})?(\s|_ALL)?(\]|\】|\b)',
        re.IGNORECASE
    )

    # For WBI signing
    _WBI_MIXIN_KEY_CACHE: Dict[str, Any] = {
        "key": None,
        "timestamp": 0,
    }
    _WBI_MIXIN_KEY_CACHE_TTL = 3600  # Cache for 1 hour

    # From https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/misc/wbi.md
    _WBI_MIXIN_KEY_TABLE = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52
    ]

    def __init__(self, pool: aiomysql.Pool):
        super().__init__(pool)
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/",
            },
            timeout=20.0,
            follow_redirects=True,
        )
        # 为避免B站风控，增加速率限制
        self._api_lock = asyncio.Lock()
        self._last_request_time = 0
        # B站API请求之间的最小间隔（秒）
        self._min_interval = 0.5

    async def _request_with_rate_limit(self, method: str, url: str, **kwargs) -> httpx.Response:
        """封装了速率限制的请求方法。"""
        async with self._api_lock:
            now = time.time()
            time_since_last = now - self._last_request_time
            if time_since_last < self._min_interval:
                sleep_duration = self._min_interval - time_since_last
                self.logger.debug(f"Bilibili: 速率限制，等待 {sleep_duration:.2f} 秒...")
                await asyncio.sleep(sleep_duration)
            
            response = await self.client.request(method, url, **kwargs)
            self._last_request_time = time.time()
            return response

    async def close(self):
        await self.client.aclose()

    async def _ensure_session_cookie(self, force_refresh: bool = False):
        """
        确保客户端拥有有效的 buvid3 cookie，采用更健壮的两步获取策略。
        :param force_refresh: 如果为 True，则无论 cookie 是否存在都强制刷新。
        """
        if not force_refresh and "buvid3" in self.client.cookies:
            self.logger.debug("Bilibili: buvid3 cookie 已存在，跳过获取。")
            return

        if force_refresh:
            self.logger.info("Bilibili: 强制刷新会话Cookie (buvid3)...")
        else:
            self.logger.debug("Bilibili: buvid3 cookie未找到，开始获取...")

        # 步骤 1: 优先尝试访问首页，模拟真实浏览器行为以获取完整的会话cookie
        try:
            self.logger.debug("Bilibili: 正在尝试从首页 (www.bilibili.com) 获取 cookie...")
            # 模仿C#代码，为首页请求构造更真实的浏览器头，以模拟直接导航
            homepage_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Sec-CH-UA": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "Referer": "" # 覆盖客户端默认的Referer，因为直接访问首页时不应有Referer
            }
            await self._request_with_rate_limit("GET", "https://www.bilibili.com/", headers=homepage_headers)
            if "buvid3" in self.client.cookies:
                self.logger.debug("Bilibili: 已成功从首页获取 buvid3 cookie。")
                return
        except Exception as e:
            self.logger.warning(f"Bilibili: 从首页获取 cookie 失败，将使用 API 后备方案。错误: {e}")

        # 步骤 2: 如果首页获取失败，则使用 /getbuvid API 作为后备，手动解析并设置 buvid3
        try:
            self.logger.info("Bilibili: 首页方法失败，正在使用 API 后备方案 (/getbuvid)...")
            response = await self._request_with_rate_limit("GET", "https://api.bilibili.com/x/web-frontend/getbuvid")
            response.raise_for_status()
            
            buvid_data = BuvidResponse.model_validate(response.json())
            if buvid_data.code == 0 and buvid_data.data and buvid_data.data.buvid:
                buvid_value = buvid_data.data.buvid
                self.client.cookies.set("buvid3", buvid_value, domain=".bilibili.com")
                self.logger.info(f"Bilibili: 已成功通过 API 后备方案获取并设置 buvid3: {buvid_value[:10]}...")
            else:
                self.logger.warning(f"Bilibili: API /getbuvid 返回异常或数据缺失: Code={buvid_data.code}")
        except Exception as e:
            self.logger.error(f"Bilibili: API 后备方案获取 cookie 同样失败: {e}", exc_info=True)

    # --- WBI Signing Methods ---
    async def _get_wbi_mixin_key(self) -> str:
        now = int(time.time())
        if self._WBI_MIXIN_KEY_CACHE.get("key") and (now - self._WBI_MIXIN_KEY_CACHE.get("timestamp", 0) < self._WBI_MIXIN_KEY_CACHE_TTL):
            return self._WBI_MIXIN_KEY_CACHE["key"]

        self.logger.info("Bilibili: WBI mixin key expired or not found, fetching new one...")

        async def _fetch_key_data():
            nav_resp = await self._request_with_rate_limit("GET", "https://api.bilibili.com/x/web-interface/nav")
            nav_resp.raise_for_status()
            return nav_resp.json().get("data", {})

        try:
            nav_data = await _fetch_key_data()
        except Exception as e:
            self.logger.warning(f"Bilibili: 第一次获取WBI密钥失败，可能由于cookie无效。正在刷新cookie后重试。错误: {e}")
            await self._ensure_session_cookie(force_refresh=True)
            try:
                nav_data = await _fetch_key_data()
            except Exception as e2:
                self.logger.error(f"Bilibili: 刷新cookie后获取WBI密钥仍然失败: {e2}", exc_info=True)
                return "dba4a5925b345b4598b7452c75070bca" # Fallback

        try:
            img_url = nav_data.get("wbi_img", {}).get("img_url", "")
            sub_url = nav_data.get("wbi_img", {}).get("sub_url", "")
            
            img_key = img_url.split('/')[-1].split('.')[0]
            sub_key = sub_url.split('/')[-1].split('.')[0]
            
            mixin_key = "".join([(img_key + sub_key)[i] for i in self._WBI_MIXIN_KEY_TABLE])[:32]
            
            self._WBI_MIXIN_KEY_CACHE["key"] = mixin_key
            self._WBI_MIXIN_KEY_CACHE["timestamp"] = now
            self.logger.info("Bilibili: Successfully fetched new WBI mixin key.")
            return mixin_key
        except Exception as e:
            self.logger.error(f"Bilibili: Failed to get WBI mixin key: {e}", exc_info=True)
            # Fallback to a known old key if fetching fails, might work for a while
            return "dba4a5925b345b4598b7452c75070bca"

    def _get_wbi_signed_params(self, params: Dict[str, Any], mixin_key: str) -> Dict[str, Any]:
        # Add timestamp
        params['wts'] = int(time.time())
        
        # Sort params
        sorted_params = sorted(params.items())
        
        # Create query string
        query = urlencode(sorted_params, safe="!()*'")
        
        # Calculate signature
        signed_query = query + mixin_key
        w_rid = hashlib.md5(signed_query.encode('utf-8')).hexdigest()
        
        params['w_rid'] = w_rid
        return params

    async def search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        self.logger.info(f"Bilibili: 正在搜索 '{keyword}'...")
        # 修正：缓存键必须包含分集信息，以区分对同一标题的不同分集搜索
        cache_key_suffix = f"_s{episode_info['season']}e{episode_info['episode']}" if episode_info else ""
        cache_key = f"search_{self.provider_name}_{keyword}{cache_key_suffix}"
        cached_results = await self._get_from_cache(cache_key)
        if cached_results is not None:
            self.logger.info(f"Bilibili: 从缓存中命中搜索结果 '{keyword}{cache_key_suffix}'")
            return [models.ProviderSearchInfo.model_validate(r) for r in cached_results]

        self.logger.debug(f"Bilibili: 缓存未命中，正在从网络获取...")
        await self._ensure_session_cookie()

        # We will search for both 'media_bangumi' (番剧) and 'media_ft' (影视) types
        search_types = ["media_bangumi", "media_ft"]
        tasks = [self._search_by_type(keyword, search_type, episode_info) for search_type in search_types]
        
        # asyncio.gather will run the searches concurrently
        results_from_all_types = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for res in results_from_all_types:
            if isinstance(res, Exception):
                self.logger.error(f"Bilibili: A search sub-task failed: {res}", exc_info=True)
            elif res:
                all_results.extend(res)
        
        # Deduplicate results based on mediaId
        final_results = []
        seen_media_ids = set()
        for item in all_results:
            if item.mediaId not in seen_media_ids:
                final_results.append(item)
                seen_media_ids.add(item.mediaId)

        self.logger.info(f"Bilibili: 搜索 '{keyword}' 完成，找到 {len(final_results)} 个有效结果。")
        await self._set_to_cache(cache_key, [r.model_dump() for r in final_results], 'search_ttl_seconds', 300)
        return final_results

    async def _search_by_type(self, keyword: str, search_type: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """Helper function to search for a specific type on Bilibili."""
        self.logger.debug(f"Bilibili: Searching for type '{search_type}' with keyword '{keyword}'")
        
        search_params = {"keyword": keyword, "search_type": search_type}
        base_url = "https://api.bilibili.com/x/web-interface/wbi/search/type"
        mixin_key = await self._get_wbi_mixin_key()
        signed_params = self._get_wbi_signed_params(search_params, mixin_key)
        url = f"{base_url}?{urlencode(signed_params)}"
        
        results = []
        try:
            response = await self._request_with_rate_limit("GET", url)
            response.raise_for_status()
            
            response_json = response.json()
            api_result = BiliApiResult.model_validate(response_json)

            if api_result.code == 0 and api_result.data and api_result.data.result:
                self.logger.info(f"Bilibili: API call for type '{search_type}' successful, found {len(api_result.data.result)} items.")
                for item in api_result.data.result:
                    # Filter out junk results based on title
                    if self._JUNK_TITLE_PATTERN.search(item.title):
                        self.logger.debug(f"Bilibili: Filtering out junk title: '{item.title}'")
                        continue

                    media_id = ""
                    media_type = "tv_series"
                    
                    if item.season_id:
                        media_id = f"ss{item.season_id}"
                        if item.season_type_name == "电影":
                            media_type = "movie"
                    elif item.bvid:
                        media_id = f"bv{item.bvid}"
                    
                    if not media_id: continue

                    year = None
                    try:
                        if item.pubdate:
                            if isinstance(item.pubdate, int):
                                year = datetime.fromtimestamp(item.pubdate).year
                            elif isinstance(item.pubdate, str) and len(item.pubdate) >= 4:
                                year = int(item.pubdate[:4])
                        elif item.pubtime:
                            year = datetime.fromtimestamp(item.pubtime).year
                    except (ValueError, TypeError, OSError):
                        pass

                    # 修正：先进行HTML解码，以处理 &lt;em&gt; 这样的实体编码
                    unescaped_title = html.unescape(item.title)
                    cleaned_title = re.sub(r'<[^>]+>', '', unescaped_title).replace(":", "：")
                    
                    provider_search_info = models.ProviderSearchInfo(
                        provider=self.provider_name,
                        mediaId=media_id,
                        title=cleaned_title,
                        type=media_type,
                        season=get_season_from_title(cleaned_title),
                        year=year,
                        imageUrl=item.cover,
                        episodeCount=item.ep_size,
                        currentEpisodeIndex=episode_info.get("episode") if episode_info else None
                    )
                    self.logger.debug(f"Bilibili: 创建的 ProviderSearchInfo: {provider_search_info.model_dump_json(indent=2)}")
                    results.append(provider_search_info)
            else:
                # 修正：将日志级别从 WARNING 改为 INFO，因为这不是一个真正的错误，
                # 只是B站API表示“无结果”的一种方式。
                self.logger.info(f"Bilibili: API for type '{search_type}' returned no results. (Code: {api_result.code}, Message: '{api_result.message}')")
        except Exception as e:
            self.logger.error(f"Bilibili: Search for type '{search_type}' failed: {e}", exc_info=True)
        
        return results

    async def get_episodes(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        if media_id.startswith("ss"):
            return await self._get_pgc_episodes(media_id, target_episode_index)
        elif media_id.startswith("bv"):
            return await self._get_ugc_episodes(media_id, target_episode_index)
        return []

    async def _get_pgc_episodes(self, media_id: str, target_episode_index: Optional[int] = None) -> List[models.ProviderEpisodeInfo]:
        season_id = media_id[2:]
        url = f"https://api.bilibili.com/pgc/view/web/ep/list?season_id={season_id}"
        try:
            await self._ensure_session_cookie()
            response = await self._request_with_rate_limit("GET", url)
            response.raise_for_status()
            data = BiliSeasonResult.model_validate(response.json())
            if data.code == 0 and data.result and data.result.episodes:
                episodes = [
                    models.ProviderEpisodeInfo(
                        provider=self.provider_name,
                        episodeId=f"{ep.aid},{ep.cid}",
                        title=ep.long_title or ep.title,
                        episodeIndex=i + 1,
                        url=f"https://www.bilibili.com/bangumi/play/ep{ep.id}"
                    ) for i, ep in enumerate(data.result.episodes)
                ]
                if target_episode_index:
                    return [ep for ep in episodes if ep.episodeIndex == target_episode_index]
                return episodes
        except Exception as e:
            self.logger.error(f"Bilibili: 获取PGC分集列表失败 (media_id={media_id}): {e}", exc_info=True)
        return []

    async def _get_ugc_episodes(self, media_id: str, target_episode_index: Optional[int] = None) -> List[models.ProviderEpisodeInfo]:
        bvid = media_id[2:]
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        try:
            await self._ensure_session_cookie()
            response = await self._request_with_rate_limit("GET", url)
            response.raise_for_status()
            data = BiliVideoViewResult.model_validate(response.json())
            if data.code == 0 and data.data and data.data.pages:
                aid = data.data.aid
                episodes = [
                    models.ProviderEpisodeInfo(
                        provider=self.provider_name,
                        episodeId=f"{aid},{p.cid}",
                        title=p.part,
                        episodeIndex=p.page,
                        url=f"https://www.bilibili.com/video/{bvid}?p={p.page}"
                    ) for p in data.data.pages
                ]
                if target_episode_index:
                    return [ep for ep in episodes if ep.episodeIndex == target_episode_index]
                return episodes
        except Exception as e:
            self.logger.error(f"Bilibili: 获取UGC分集列表失败 (media_id={media_id}): {e}", exc_info=True)
        return []

    async def _get_danmaku_pools(self, aid: int, cid: int) -> List[int]:
        """获取一个视频的所有弹幕池ID (CID)，包括主弹幕和字幕弹幕。"""
        all_cids = [cid]  # Start with the main CID
        try:
            # The /x/player/v2 endpoint provides subtitle information
            url = f"https://api.bilibili.com/x/player/v2?aid={aid}&cid={cid}"
            response = await self._request_with_rate_limit("GET", url)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 0 and data.get("data"):
                subtitles = data.get("data", {}).get("subtitle", {}).get("list", [])
                for sub in subtitles:
                    if sub.get("id"):  # 'id' here is the CID for the subtitle track
                        all_cids.append(sub['id'])
                self.logger.info(f"Bilibili: 为 aid={aid}, cid={cid} 找到 {len(all_cids)} 个弹幕池 (包括字幕)。")
        except Exception as e:
            self.logger.warning(f"Bilibili: 获取额外弹幕池失败 (aid={aid}, cid={cid}): {e}", exc_info=False)

        return list(dict.fromkeys(all_cids))  # Return unique CIDs

    async def _fetch_comments_for_cid(self, aid: int, cid: int, progress_callback: Optional[Callable] = None) -> List[DanmakuElem]:
        """为单个CID获取所有弹幕分段。"""
        all_comments = []
        segment_index = 1
        while True:
            try:
                if progress_callback:
                    await progress_callback(min(95, segment_index * 10), f"获取弹幕池 {cid} 的分段 {segment_index}")

                url = f"https://api.bilibili.com/x/v2/dm/web/seg.so?type=1&oid={cid}&pid={aid}&segment_index={segment_index}"
                response = await self._request_with_rate_limit("GET", url)

                if response.status_code == 304:
                    break
                response.raise_for_status()
                if not response.content:
                    break

                danmu_reply = DmSegMobileReply()
                # 修正：使用 asyncio.to_thread 在单独的线程中运行可能阻塞的CPU密集型操作，
                # 避免 Protobuf 解析大数据时阻塞事件循环。
                # 这是解决任务卡在“运行中”状态的关键。
                await asyncio.to_thread(danmu_reply.ParseFromString, response.content)

                if not danmu_reply.elems:
                    break

                all_comments.extend(danmu_reply.elems)
                segment_index += 1

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    break
                self.logger.error(f"Bilibili: 获取弹幕分段失败 (cid={cid}, segment={segment_index}): {e}", exc_info=True)
                break
            except Exception as e:
                self.logger.error(f"Bilibili: 处理弹幕分段时出错 (cid={cid}, segment={segment_index}): {e}", exc_info=True)
                break
        return all_comments

    async def get_comments(self, episode_id: str, progress_callback: Optional[Callable] = None) -> List[dict]:
        try:
            aid_str, main_cid_str = episode_id.split(',')
            aid, main_cid = int(aid_str), int(main_cid_str)
        except (ValueError, IndexError):
            self.logger.error(f"Bilibili: 无效的 episode_id 格式: '{episode_id}'")
            return []

        await self._ensure_session_cookie()

        if progress_callback: await progress_callback(0, "正在获取弹幕池列表...")
        all_cids = await self._get_danmaku_pools(aid, main_cid)
        total_cids = len(all_cids)

        all_comments = []
        for i, cid in enumerate(all_cids):
            self.logger.info(f"Bilibili: 正在获取弹幕池 {i + 1}/{total_cids} (CID: {cid})...")

            async def sub_progress_callback(danmaku_progress: int, danmaku_description: str):
                if progress_callback:
                    base_progress = (i / total_cids) * 100
                    progress_range = (1 / total_cids) * 100
                    current_total_progress = base_progress + (danmaku_progress / 100) * progress_range
                    # 修正：使用位置参数调用，以匹配 generic_import_task 中回调的签名
                    await progress_callback(current_total_progress, f"池 {i + 1}/{total_cids}: {danmaku_description}")

            comments_for_cid = await self._fetch_comments_for_cid(aid, cid, sub_progress_callback)
            all_comments.extend(comments_for_cid)

        if progress_callback:
            await progress_callback(100, "弹幕整合完成")

        unique_comments = {c.id: c for c in all_comments}.values()
        self.logger.info(f"Bilibili: 为 episode_id='{episode_id}' 获取了 {len(unique_comments)} 条唯一弹幕。")
        return self._format_comments(list(unique_comments))

    def _format_comments(self, comments: List[DanmakuElem]) -> List[dict]:
        if not comments:
            return []

        # 1. 按内容对弹幕进行分组，以识别重复弹幕
        grouped_by_content: Dict[str, List[DanmakuElem]] = defaultdict(list)
        for c in comments:
            grouped_by_content[c.content].append(c)

        # 2. 处理重复项
        processed_comments: List[DanmakuElem] = []
        for content, group in grouped_by_content.items():
            if len(group) == 1:
                # 如果弹幕不重复，直接添加
                processed_comments.append(group[0])
            else:
                # 如果有重复，找到时间最早的那条
                first_comment = min(group, key=lambda x: x.progress)
                # 在其内容后附加重复次数
                first_comment.content = f"{first_comment.content} X{len(group)}"
                # 只将这条修改后的弹幕添加到最终列表
                processed_comments.append(first_comment)

        # 3. 格式化处理后的弹幕列表
        formatted = []
        for c in processed_comments:
            timestamp = c.progress / 1000.0
            p_string = f"{timestamp:.3f},{c.mode},{c.color},[{self.provider_name}]"
            formatted.append({
                "cid": str(c.id),
                "p": p_string,
                "m": c.content,
                "t": round(timestamp, 2)
            })
        return formatted
