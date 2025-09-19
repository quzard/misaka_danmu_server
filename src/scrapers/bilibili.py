import asyncio
import logging
import re
import time
import hashlib
import html
import json
from urllib.parse import urlencode
from typing import Any, Callable, Dict, List, Optional, Union
from datetime import datetime, timezone
from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ..utils import parse_search_keyword
from .. import crud
import httpx
from pydantic import BaseModel, Field, ValidationError

# --- Start of merged dm_dynamic.py content ---
# This block dynamically generates the Protobuf message classes required for Bilibili's danmaku API.
# It's placed here to encapsulate the logic within the only scraper that uses it,
# simplifying the project structure by removing the need for a separate dm_dynamic.py file.

scraper_responses_logger = logging.getLogger("scraper_responses")
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
from ..config_manager import ConfigManager

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
    show_title: Optional[str] = None
    badges: Optional[List[Dict[str, Any]]] = None

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
    handled_domains = ["www.bilibili.com", "b23.tv"]
    referer = "https://www.bilibili.com/"
    test_url = "https://api.bilibili.com"
    _PROVIDER_SPECIFIC_BLACKLIST_DEFAULT = r"^(.*?)(抢先(看|版)?|加更|花絮|预告|特辑|彩蛋|专访|幕后|直播|纯享|未播|衍生|番外|会员(专享)?|片花|精华|看点|速看|解读|reaction|影评|解说|吐槽|盘点)(.*?)$"

    # For WBI signing
    _WBI_MIXIN_KEY_CACHE: Dict[str, Any] = {"key": None, "timestamp": 0}
    _WBI_MIXIN_KEY_CACHE_TTL = 3600  # Cache for 1 hour
    _WBI_MIXIN_KEY_TABLE = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52
    ]
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager):
        super().__init__(session_factory, config_manager)
        self._api_lock = asyncio.Lock()
        self._last_request_time = 0
        self._min_interval = 0.5
        self.client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """
        Ensures a configured client is available for short-lived requests like WBI key fetching.
        This method is primarily for compatibility with functions that expect it.
        """
        # 修正：此方法现在正确地调用 _ensure_config_and_cookie 来返回一个可用的客户端实例。
        # 检查代理配置是否发生变化
        new_proxy_config = await self._get_proxy_for_provider()
        if self.client and new_proxy_config != self._current_proxy_config:
            self.logger.info("Bilibili: 代理配置已更改，正在重建HTTP客户端...")
            await self.client.aclose()
            self.client = None

        if self.client is None:
            self.client = await self._create_configured_client()
        return self.client
    async def _request_with_rate_limit(self, method: str, url: str, **kwargs) -> httpx.Response:
        """封装了速率限制的请求方法。"""
        async with self._api_lock:
            now = time.time()
            time_since_last = now - self._last_request_time
            if time_since_last < self._min_interval:
                sleep_duration = self._min_interval - time_since_last
                self.logger.debug(f"Bilibili: 速率限制，等待 {sleep_duration:.2f} 秒...")
                await asyncio.sleep(sleep_duration)

            client = await self._ensure_client()
            response = await client.request(method, url, **kwargs)
            self._last_request_time = time.time()
            return response

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _create_configured_client(self) -> httpx.AsyncClient:
        """
        实时从数据库加载并应用Cookie，确保配置实时生效。
        此方法在每次请求前调用。它支持两种模式：
        - 使用数据库中配置的完整Cookie进行认证请求。
        - 在未配置时自动获取临时的buvid3进行公共API请求。
        """
        self.logger.debug("Bilibili: 正在从数据库加载Cookie...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        client = await self._create_client(headers=headers)

        cookie_str = await self.config_manager.get("bilibiliCookie", "")
        if cookie_str:
            cookie_parts = [c.strip().split('=', 1) for c in cookie_str.split(';')]
            for parts in cookie_parts:
                if len(parts) == 2:
                    client.cookies.set(parts[0], parts[1], domain=".bilibili.com")
            self.logger.debug("Bilibili: 已成功从数据库加载Cookie。")
        else:
            self.logger.debug("Bilibili: 数据库中未找到Cookie。")

        if "buvid3" not in client.cookies:
            await self._get_temp_buvid3(client)
        
        return client

    async def _get_temp_buvid3(self, client: httpx.AsyncClient):
        """
        为未登录的操作获取一个临时的buvid3。
        这是保留原有非登录模式功能的关键。
        """
        if "buvid3" in client.cookies:
            return
        try:
            self.logger.debug("Bilibili: 正在尝试获取一个临时的buvid3...")
            await client.get("https://www.bilibili.com/")
            if "buvid3" in client.cookies:
                self.logger.debug("Bilibili: 已成功获取临时的buvid3。")
        except Exception as e:
            self.logger.warning(f"Bilibili: 获取临时的buvid3失败: {e}")

    async def get_login_info(self) -> Dict[str, Any]:
        """获取当前登录状态。"""
        client = await self._ensure_client()
        nav_resp = await client.get("https://api.bilibili.com/x/web-interface/nav")
        nav_resp.raise_for_status()
        data = nav_resp.json().get("data", {})
        if data.get("isLogin"):
            vip_info = data.get("vip", {})
            return {
                "isLogin": True,
                "uname": data.get("uname"),
                "face": data.get("face"),
                "level": data.get("level_info", {}).get("current_level"),
                "vipStatus": vip_info.get("status"), # 0: 非会员, 1: 会员
                "vipType": vip_info.get("type"), # 0:无, 1:月度, 2:年度
                "vipDueDate": vip_info.get("due_date") # 毫秒时间戳
            }
        return {"isLogin": False}

    async def generate_login_qrcode(self) -> Dict[str, str]:
        """生成用于扫码登录的二维码信息。"""
        # 新增：为二维码生成请求添加WBI签名
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
        mixin_key = await self._get_wbi_mixin_key()
        # The generate endpoint has no parameters, so we sign an empty dict
        signed_params = self._get_wbi_signed_params({}, mixin_key)
        client = await self._ensure_client()
        response = await client.get(url, params=signed_params)
        response.raise_for_status()
        data = response.json().get("data", {})
        if not data.get("qrcode_key") or not data.get("url"):
            raise ValueError("未能从B站API获取有效的二维码信息。")
        return {"qrcodeKey": data["qrcode_key"], "url": data["url"]}

    async def poll_login_status(self, qrcodeKey: str) -> Dict[str, Any]:
        """轮询扫码登录状态。"""
        # 新增：为轮询请求添加WBI签名
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
        params = {"qrcode_key": qrcodeKey}
        mixin_key = await self._get_wbi_mixin_key()
        signed_params = self._get_wbi_signed_params(params, mixin_key)
        client = await self._ensure_client()
        response = await client.get(url, params=signed_params)
        response.raise_for_status()
        poll_data = response.json().get("data", {})

        if poll_data.get("code") == 0:
            self.logger.info("Bilibili: 扫码登录成功！")
            required_cookies = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"]
            all_cookies = []
            for name, value in client.cookies.items(): # 修正：现在 client 是 self.client，在作用域内
                if name in required_cookies or name.startswith("buvid"):
                    all_cookies.append(f"{name}={value}")
            
            # 修正：检查从客户端收集的cookie，而不是 self.client
            if any("SESSDATA" in c for c in all_cookies):
                cookie_string = "; ".join(all_cookies)
                await self.config_manager.setValue("bilibiliCookie", cookie_string)
                self.logger.info("Bilibili: 新的登录Cookie已保存到数据库。")
            else:
                self.logger.error("Bilibili: 登录轮询成功，但响应中未找到SESSDATA。")

        return poll_data

    async def execute_action(self, action_name: str, payload: Dict[str, Any]) -> Any:
        """
        执行Bilibili源的特定操作，如登录流程。
        """
        if action_name == "get_login_info":
            return await self.get_login_info()
        elif action_name == "generate_qrcode":
            return await self.generate_login_qrcode()
        elif action_name == "poll_login":
            qrcodeKey = payload.get("qrcodeKey")
            if not qrcodeKey:
                raise ValueError("轮询登录状态需要 'qrcodeKey'。")
            return await self.poll_login_status(qrcodeKey)
        elif action_name == "logout":
            await self.config_manager.setValue("bilibiliCookie", "")
            return {"message": "注销成功"}
        else:
            return await super().execute_action(action_name, payload)

    async def get_id_from_url(self, url: str) -> Optional[Dict[str, int]]:
        """
        从一个Bilibili视频URL中获取aid和cid。
        """
        self.logger.info(f"Bilibili: 正在从URL解析ID: {url!r}")
        try:
            client = await self._ensure_client()
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

            # 步骤 1: 优先尝试从 __INITIAL_STATE__ JSON块中查找
            match = re.search(r'__INITIAL_STATE__=({.*?});', html)
            if match:
                initial_state = json.loads(match.group(1))
                video_data = initial_state.get('videoData', {})
                aid = video_data.get('aid')
                
                # 步骤 2: 智能确定目标 cid
                target_cid = None
                # 2a: 检查番剧的 ep_id
                ep_match = re.search(r'/play/ep(\d+)', url)
                if ep_match and 'epList' in initial_state:
                    target_ep_id = int(ep_match.group(1))
                    for ep in initial_state['epList']:
                        if ep.get('id') == target_ep_id:
                            target_cid = ep.get('cid')
                            self.logger.info(f"Bilibili: 通过 ep_id ({target_ep_id}) 精确匹配到 cid: {target_cid}")
                            break
                
                # 2b: 检查普通视频的 p 参数
                p_match = re.search(r'[?&]p=(\d+)', url)
                if not target_cid and p_match and 'pages' in video_data:
                    target_p_num = int(p_match.group(1))
                    for page in video_data['pages']:
                        if page.get('page') == target_p_num:
                            target_cid = page.get('cid')
                            self.logger.info(f"Bilibili: 通过 p={target_p_num} 精确匹配到 cid: {target_cid}")
                            break
                
                # 2c: 如果没有特定分集，则使用默认的 cid
                if not target_cid:
                    target_cid = video_data.get('cid')

                if aid and target_cid:
                    self.logger.info(f"Bilibili: 从INITIAL_STATE解析成功: aid={aid}, cid={target_cid}")
                    return {"aid": aid, "cid": target_cid}

            # 步骤 3: 如果找不到，则回退到正则表达式
            aid_match = re.search(r'"aid"\s*:\s*(\d+)', html)
            cid_match = re.search(r'"cid"\s*:\s*(\d+)', html)
            if aid_match and cid_match:
                aid, cid = int(aid_match.group(1)), int(cid_match.group(1))
                self.logger.info(f"Bilibili: 通过正则表达式解析成功: aid={aid}, cid={cid}")
                return {"aid": aid, "cid": cid}

            self.logger.warning(f"Bilibili: 无法从URL中解析aid和cid: {url}")
            return None
        except Exception as e:
            self.logger.error(f"Bilibili: 从URL {url} 获取或解析页面ID失败: {e}", exc_info=True)
            return None

    def format_episode_id_for_comments(self, provider_episode_id: Any) -> str:
        if isinstance(provider_episode_id, dict):
            return f"{provider_episode_id.get('aid')},{provider_episode_id.get('cid')}"
        return str(provider_episode_id)

    async def _get_wbi_mixin_key(self) -> str:
        """获取用于WBI签名的mixinKey，带缓存。"""
        now = int(time.time())
        if self._WBI_MIXIN_KEY_CACHE.get("key") and (now - self._WBI_MIXIN_KEY_CACHE.get("timestamp", 0) < self._WBI_MIXIN_KEY_CACHE_TTL):
            return self._WBI_MIXIN_KEY_CACHE["key"]

        self.logger.info("Bilibili: WBI mixin key expired or not found, fetching new one...")
        
        client = await self._ensure_client()
        async def _fetch_key_data():
            nav_resp = await client.get("https://api.bilibili.com/x/web-interface/nav")
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"Bilibili WBI Key Response: {nav_resp.text}")
            nav_resp.raise_for_status()
            return nav_resp.json().get("data", {})

        try:
            nav_data = await _fetch_key_data()
        except Exception as e:
            self.logger.error(f"Bilibili: 获取WBI密钥失败: {e}", exc_info=True)
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
            return "dba4a5925b345b4598b7452c75070bca"

    def _get_wbi_signed_params(self, params: Dict[str, Any], mixin_key: str) -> Dict[str, Any]:
        """对参数进行WBI签名。"""
        params['wts'] = int(time.time())
        sorted_params = sorted(params.items())
        query = urlencode(sorted_params, safe="!()*'")
        signed_query = query + mixin_key
        w_rid = hashlib.md5(signed_query.encode('utf-8')).hexdigest()
        params['w_rid'] = w_rid
        return params

    async def search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """
        Performs a cached search for Bilibili content.
        It caches the base results for a title and then filters them based on season.
        """
        parsed = parse_search_keyword(keyword)
        search_title = parsed['title']
        search_season = parsed['season']

        cache_key = f"search_base_{self.provider_name}_{search_title}"
        cached_results = await self._get_from_cache(cache_key)

        if cached_results:
            self.logger.info(f"Bilibili: 从缓存中命中基础搜索结果 (title='{search_title}')")
            all_results = [models.ProviderSearchInfo.model_validate(r) for r in cached_results]
            # 修复：为缓存结果设置正确的currentEpisodeIndex
            for item in all_results:
                item.currentEpisodeIndex = episode_info.get("episode") if episode_info else None
        else:
            self.logger.info(f"Bilibili: 缓存未命中，正在为标题 '{search_title}' 执行网络搜索...")
            all_results = await self._perform_network_search(search_title, episode_info)
            if all_results:
                await self._set_to_cache(cache_key, [r.model_dump() for r in all_results], 'search_ttl_seconds', 3600)

        if search_season is None:
            return all_results

        # Filter results by season
        final_results = [item for item in all_results if item.season == search_season]
        self.logger.info(f"Bilibili: 为 S{search_season} 过滤后，剩下 {len(final_results)} 个结果。")
        return final_results

    async def _perform_network_search(self, keyword: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """Performs the actual network search for Bilibili."""
        mixin_key = await self._get_wbi_mixin_key()
        search_types = ["media_bangumi", "media_ft"]
        tasks = [self._search_by_type(keyword, search_type, mixin_key, episode_info) for search_type in search_types]
        results_from_all_types = await asyncio.gather(*tasks, return_exceptions=True)
        all_results = []
        for res in results_from_all_types:
            if isinstance(res, Exception):
                self.logger.error(f"Bilibili: A search sub-task failed: {res}", exc_info=True)
            elif res:
                all_results.extend(res)
        
        final_results = list({item.mediaId: item for item in all_results}.values())

        self.logger.info(f"Bilibili: 网络搜索 '{keyword}' 完成，找到 {len(final_results)} 个有效结果。")
        if final_results:
            log_results = "\n".join([f"  - {r.title} (ID: {r.mediaId}, 类型: {r.type}, 年份: {r.year or 'N/A'})" for r in final_results])
            self.logger.info(f"Bilibili: 搜索结果列表:\n{log_results}")
        return final_results

    async def _search_by_type(self, keyword: str, search_type: str, mixin_key: str, episode_info: Optional[Dict[str, Any]] = None) -> List[models.ProviderSearchInfo]:
        """Helper function to search for a specific type on Bilibili."""
        self.logger.debug(f"Bilibili: Searching for type '{search_type}' with keyword '{keyword}'")
        
        search_params = {"keyword": keyword, "search_type": search_type}
        base_url = "https://api.bilibili.com/x/web-interface/wbi/search/type"
        signed_params = self._get_wbi_signed_params(search_params, mixin_key)
        url = f"{base_url}?{urlencode(signed_params)}"
        
        results = []
        try:
            client = await self._ensure_client()
            response = await client.get(url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"Bilibili Search Response (type='{search_type}', keyword='{keyword}'): {response.text}")
            response.raise_for_status()
            api_result = BiliApiResult.model_validate(response.json())

            if api_result.code == 0 and api_result.data and api_result.data.result:
                self.logger.info(f"Bilibili: API call for type '{search_type}' successful, found {len(api_result.data.result)} items.")
                for item in api_result.data.result:
                    media_id = f"ss{item.season_id}" if item.season_id else f"bv{item.bvid}" if item.bvid else ""
                    if not media_id: continue

                    media_type = "movie" if item.season_type_name == "电影" else "tv_series"
                    
                    # 修正：对于电影类型，即使API返回的ep_size为0或null，也应将总集数视为1。
                    # 这可以改善前端UI的显示，使其更符合用户对电影的直观理解。
                    episode_count = 1 if media_type == "movie" else item.ep_size
                    
                    year = None
                    try:
                        if item.pubdate:
                            if isinstance(item.pubdate, int): year = datetime.fromtimestamp(item.pubdate).year
                            elif isinstance(item.pubdate, str) and len(item.pubdate) >= 4: year = int(item.pubdate[:4])
                        elif item.pubtime: year = datetime.fromtimestamp(item.pubtime).year
                    except (ValueError, TypeError, OSError): pass

                    unescaped_title = html.unescape(item.title)
                    cleaned_title = re.sub(r'<[^>]+>', '', unescaped_title).replace(":", "：")
                    
                    results.append(models.ProviderSearchInfo(
                        provider=self.provider_name, mediaId=media_id, title=cleaned_title,
                        type=media_type, season=get_season_from_title(cleaned_title),
                        year=year, imageUrl=item.cover, episodeCount=episode_count,
                        currentEpisodeIndex=episode_info.get("episode") if episode_info else None
                    ))
            else:
                self.logger.info(f"Bilibili: API for type '{search_type}' returned no results. (Code: {api_result.code}, Message: '{api_result.message}')")
        except Exception as e:
            self.logger.error(f"Bilibili: Search for type '{search_type}' failed: {e}", exc_info=True)
        
        return results

    def _bili_media_to_provider_info(self, item: BiliSearchMedia) -> Optional[models.ProviderSearchInfo]:
        """
        一个辅助函数，用于将Bilibili的媒体对象转换为通用的 ProviderSearchInfo 模型。
        """
        if not item:
            return None

        media_id = f"ss{item.season_id}" if item.season_id else f"bv{item.bvid}" if item.bvid else ""
        if not media_id:
            return None

        media_type = "movie" if item.season_type_name == "电影" else "tv_series"
        
        year = None
        try:
            if item.pubdate:
                if isinstance(item.pubdate, int): year = datetime.fromtimestamp(item.pubdate).year
                elif isinstance(item.pubdate, str) and len(item.pubdate) >= 4: year = int(item.pubdate[:4])
            elif item.pubtime: year = datetime.fromtimestamp(item.pubtime).year
        except (ValueError, TypeError, OSError):
            pass

        unescaped_title = html.unescape(item.title)
        cleaned_title = re.sub(r'<[^>]+>', '', unescaped_title).replace(":", "：")
        
        return models.ProviderSearchInfo(
            provider=self.provider_name,
            mediaId=media_id,
            title=cleaned_title,
            type=media_type,
            season=get_season_from_title(cleaned_title),
            year=year,
            imageUrl=item.cover,
            episodeCount=item.ep_size,
            currentEpisodeIndex=None # This is not available in this context
        )

    async def get_info_from_url(self, url: str) -> Optional[models.ProviderSearchInfo]:
        """从B站URL中提取作品信息。"""
        self.logger.info(f"Bilibili: 正在从URL提取信息: {url}")
        await self._ensure_config_and_cookie()

        # 尝试从URL中解析 season_id 或 bvid
        ss_match = re.search(r'season/ss(\d+)', url)
        ep_match = re.search(r'play/ep(\d+)', url)
        bv_match = re.search(r'video/(BV[a-zA-Z0-9]+)', url)

        media_info = None

        if ss_match or ep_match:
            # 处理番剧 (PGC)
            season_id = None
            if ss_match:
                season_id = ss_match.group(1)
            elif ep_match:
                # 如果是分集链接，需要访问页面获取 season_id
                try:
                    page_res = await self._request_with_rate_limit("GET", url)
                    page_res.raise_for_status()
                    season_match_from_page = re.search(r'"season_id":(\d+)', page_res.text)
                    if season_match_from_page:
                        season_id = season_match_from_page.group(1)
                except Exception as e:
                    self.logger.error(f"Bilibili: 从ep链接获取season_id失败: {e}")
            
            if season_id:
                api_url = f"https://api.bilibili.com/pgc/view/web/season?season_id={season_id}"
                response = await self._request_with_rate_limit("GET", api_url)
                response.raise_for_status()
                data = response.json().get("result", {})
                media_info = BiliSearchMedia.model_validate(data)

        elif bv_match:
            # 处理普通视频 (UGC)
            bvid = bv_match.group(1)
            api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            response = await self._request_with_rate_limit("GET", api_url)
            response.raise_for_status()
            data = response.json().get("data", {})
            media_info = BiliSearchMedia(title=data.get("title"), bvid=bvid, cover=data.get("pic"))

        if not media_info:
            return None
        return self._bili_media_to_provider_info(media_info)

    async def _filter_and_renumber_episodes(
        self,
        episodes: List[models.ProviderEpisodeInfo],
        content_type: str  # "PGC" or "UGC"
    ) -> List[models.ProviderEpisodeInfo]:
        """Applies blacklist filtering to a list of episodes and renumbers their indices."""
        # 修正：Bilibili源只应使用其专属的黑名单，以避免全局规则误杀。
        provider_pattern_str = await self.config_manager.get(f"{self.provider_name}_episode_blacklist_regex", self._PROVIDER_SPECIFIC_BLACKLIST_DEFAULT)

        blacklist_rules = [provider_pattern_str] if provider_pattern_str else []
        
        if not blacklist_rules:
            # 如果没有黑名单，直接重编号并返回
            for i, ep in enumerate(episodes):
                ep.episodeIndex = i + 1
            return episodes

        episodes_to_keep = []
        filtered_out_log: Dict[str, List[str]] = defaultdict(list)

        for episode in episodes:
            is_filtered = False
            for rule in blacklist_rules:
                if not rule: continue
                if re.search(rule, episode.title, re.IGNORECASE):
                    filtered_out_log[rule].append(episode.title)
                    is_filtered = True
                    break  # 匹配到任何一条规则即被过滤，跳出内层循环
            if not is_filtered:
                episodes_to_keep.append(episode)

        # 修正：打印详细的过滤日志
        for rule, titles in filtered_out_log.items():
            self.logger.info(f"Bilibili: 根据黑名单规则 '{rule}' 过滤掉了 {len(titles)} 个{content_type}分集: {', '.join(titles)}")

        # Renumber the final list of episodes
        for i, ep in enumerate(episodes_to_keep):
            ep.episodeIndex = i + 1
            
        return episodes_to_keep

    async def get_episodes(self, media_id: str, target_episode_index: Optional[int] = None, db_media_type: Optional[str] = None) -> List[models.ProviderEpisodeInfo]:
        if media_id.startswith("ss"):
            return await self._get_pgc_episodes(media_id, target_episode_index)
        elif media_id.startswith("bv"):
            return await self._get_ugc_episodes(media_id, target_episode_index)
        return []

    async def _get_pgc_episodes(self, media_id: str, target_episode_index: Optional[int] = None) -> List[models.ProviderEpisodeInfo]:
        season_id = media_id[2:]
        # 修正：使用更可靠的 /season 接口，并优先处理 main_section
        url = f"https://api.bilibili.com/pgc/view/web/season?season_id={season_id}"
        try:
            client = await self._ensure_client()
            response = await client.get(url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"Bilibili PGC Episodes Response (media_id={media_id}): {response.text}")
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 0 and (result_data := data.get("result")):
                # 优先从 'main_section' 获取分集，以过滤掉PV、OP/ED等
                raw_episodes = result_data.get("main_section", {}).get("episodes", [])
                if not raw_episodes:
                    raw_episodes = result_data.get("episodes", [])

                if not raw_episodes:
                    self.logger.warning(f"Bilibili: PGC media_id={media_id} 未找到任何分集数据。")
                    return []

                validated_episodes = []
                for ep_data in raw_episodes:
                    try:
                        validated_episodes.append(BiliEpisode.model_validate(ep_data))
                    except ValidationError as e:
                        self.logger.warning(f"Bilibili: 跳过一个无效的PGC分集数据: {ep_data}, 错误: {e}")

                # 修正：使用通用的黑名单规则来过滤标签，而不仅仅是硬编码的“预告”
                episodes_after_badge_filter = []
                blacklist_pattern = await self.get_episode_blacklist_pattern()
                
                if not blacklist_pattern:
                    # 如果没有黑名单，则不进行标签过滤
                    episodes_after_badge_filter = validated_episodes
                else:
                    for ep in validated_episodes:
                        is_filtered_by_badge = False
                        if ep.badges:
                            for badge in ep.badges:
                                badge_text = badge.get("text")
                                if badge_text and blacklist_pattern.search(badge_text):
                                    self.logger.info(f"Bilibili: 根据标签 '{badge_text}' 过滤掉分集: '{(ep.show_title or ep.long_title or ep.title)}'")
                                    is_filtered_by_badge = True
                                    break  # 一个标签匹配就足够了
                        
                        if not is_filtered_by_badge:
                            episodes_after_badge_filter.append(ep)

                # 修正：优先使用 show_title，因为它包含最完整的信息（如“预告”），
                # 其次是 long_title，最后是 title。这确保了后续的黑名单过滤能正确生效。
                initial_episodes = [
                    models.ProviderEpisodeInfo(
                        provider=self.provider_name,
                        episodeId=f"{ep.aid},{ep.cid}",
                        title=(ep.show_title or ep.long_title or ep.title).strip(),
                        episodeIndex=0,  # Will be renumbered by the helper
                        url=f"https://www.bilibili.com/bangumi/play/ep{ep.id}"
                    ) for ep in episodes_after_badge_filter
                ]

                final_episodes = await self._filter_and_renumber_episodes(initial_episodes, "PGC")

                return [ep for ep in final_episodes if ep.episodeIndex == target_episode_index] if target_episode_index else final_episodes
        except Exception as e:
            self.logger.error(f"Bilibili: 获取PGC分集列表失败 (media_id={media_id}): {e}", exc_info=True)
        return []

    async def _get_ugc_episodes(self, media_id: str, target_episode_index: Optional[int] = None) -> List[models.ProviderEpisodeInfo]:
        bvid = media_id[2:]
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        try:
            client = await self._ensure_client()
            response = await client.get(url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"Bilibili UGC Episodes Response (media_id={media_id}): {response.text}")
            response.raise_for_status()
            data = BiliVideoViewResult.model_validate(response.json())
            if data.code == 0 and data.data and data.data.pages:
                # 对于UGC内容，标题就是 'part' 字段，这里确保它被正确地清理空格。
                initial_episodes = [
                    models.ProviderEpisodeInfo(
                        provider=self.provider_name,
                        episodeId=f"{data.data.aid},{p.cid}",
                        title=p.part.strip(),
                        episodeIndex=0,  # Will be renumbered by the helper
                        url=f"https://www.bilibili.com/video/{bvid}?p={p.page}"
                    ) for p in data.data.pages
                ]

                final_episodes = await self._filter_and_renumber_episodes(initial_episodes, "UGC")

                return [ep for ep in final_episodes if ep.episodeIndex == target_episode_index] if target_episode_index else final_episodes
        except Exception as e:
            self.logger.error(f"Bilibili: 获取UGC分集列表失败 (media_id={media_id}): {e}", exc_info=True)
        return []

    async def _get_danmaku_pools(self, aid: int, cid: int) -> List[int]:
        """获取一个视频的所有弹幕池ID (CID)，包括主弹幕和字幕弹幕。"""
        all_cids = {cid}
        try:
            url = f"https://api.bilibili.com/x/player/v2?aid={aid}&cid={cid}"
            client = await self._ensure_client()
            response = await client.get(url)
            if await self._should_log_responses():
                scraper_responses_logger.debug(f"Bilibili Danmaku Pools Response (aid={aid}, cid={cid}): {response.text}")
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 0 and data.get("data"):
                for sub in data.get("data", {}).get("subtitle", {}).get("list", []):
                    if sub.get("id"): all_cids.add(sub['id'])
            self.logger.info(f"Bilibili: 为 aid={aid}, cid={cid} 找到 {len(all_cids)} 个弹幕池 (包括字幕)。")
        except Exception as e:
            self.logger.warning(f"Bilibili: 获取额外弹幕池失败 (aid={aid}, cid={cid}): {e}", exc_info=False)
        return list(all_cids)

    async def _fetch_comments_for_cid(self, aid: int, cid: int, progress_callback: Optional[Callable] = None) -> List[DanmakuElem]:
        """为单个CID获取所有弹幕分段。"""
        all_comments = []
        for segment_index in range(1, 100): # Limit to 100 segments to prevent infinite loops
            try:
                if progress_callback:
                    await progress_callback(min(95, segment_index * 10), f"获取弹幕池 {cid} 的分段 {segment_index}")

                url = f"https://api.bilibili.com/x/v2/dm/web/seg.so?type=1&oid={cid}&pid={aid}&segment_index={segment_index}"
                client = await self._ensure_client()
                response = await client.get(url)
                if response.status_code == 304 or not response.content: break
                response.raise_for_status()
                danmu_reply = DmSegMobileReply()
                await asyncio.to_thread(danmu_reply.ParseFromString, response.content)
                if not danmu_reply.elems: break
                all_comments.extend(danmu_reply.elems)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404: break
                self.logger.error(f"Bilibili: 获取弹幕分段失败 (cid={cid}, segment={segment_index}): {e}", exc_info=True)
                break
            except Exception as e:
                self.logger.error(f"Bilibili: 处理弹幕分段时出错 (cid={cid}, segment={segment_index}): {e}", exc_info=True)
                break
        return all_comments

    async def get_comments(self, episode_id: str, progress_callback: Optional[Callable] = None) -> Optional[List[dict]]:
        try:
            aid_str, main_cid_str = episode_id.split(',')
            aid, main_cid = int(aid_str), int(main_cid_str)
        except (ValueError, IndexError):
            self.logger.error(f"Bilibili: 无效的 episode_id 格式: '{episode_id}'")
            return None

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
                    await progress_callback(current_total_progress, f"池 {i + 1}/{total_cids}: {danmaku_description}")

            comments_for_cid = await self._fetch_comments_for_cid(aid, cid, sub_progress_callback)
            all_comments.extend(comments_for_cid)

        if progress_callback: await progress_callback(100, "弹幕整合完成")

        unique_comments = list({c.id: c for c in all_comments}.values())
        self.logger.info(f"Bilibili: 为 episode_id='{episode_id}' 获取了 {len(unique_comments)} 条唯一弹幕。")
        return self._format_comments(unique_comments)

    def _format_comments(self, comments: List[DanmakuElem]) -> List[dict]:
        """格式化弹幕，并处理重复内容。"""
        if not comments: return []

        grouped_by_content: Dict[str, List[DanmakuElem]] = defaultdict(list)
        for c in comments:
            grouped_by_content[c.content].append(c)

        processed_comments: List[DanmakuElem] = []
        for content, group in grouped_by_content.items():
            if len(group) == 1:
                processed_comments.append(group[0])
            else:
                # 修正：创建一个新的弹幕对象来处理重复项，而不是修改原始对象，以避免副作用。
                first_comment = min(group, key=lambda x: x.progress)
                new_comment = DanmakuElem()
                new_comment.CopyFrom(first_comment)
                new_comment.content = f"{new_comment.content} X{len(group)}"
                processed_comments.append(new_comment)

        formatted = []
        for c in processed_comments:
            # Sanitize content to remove null characters, which are invalid in PostgreSQL's TEXT type.
            sanitized_content = c.content.replace('\x00', '')
            if not sanitized_content: # Skip if the comment is empty after sanitization
                continue
            timestamp = c.progress / 1000.0
            # 修正：使用API返回的 c.fontsize 字段来添加字体大小
            p_string = f"{timestamp:.3f},{c.mode},{c.fontsize},{c.color},[{self.provider_name}]"
            formatted.append({"cid": str(c.id), "p": p_string, "m": sanitized_content, "t": round(timestamp, 2)})
        return formatted