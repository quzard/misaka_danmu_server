import asyncio
import json
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError, field_validator

from .. import crud, models
from .base import BaseMetadataSource, HTTPStatusError

logger = logging.getLogger(__name__)
# 新增：获取用于记录元数据响应的专用 logger
metadata_logger = logging.getLogger('metadata_responses')

# --- Pydantic Models for Douban JSON API ---
class DoubanJsonSearchSubject(BaseModel):
    id: str
    title: str
    url: str
    cover: str
    rate: str
    cover_x: Optional[int] = None
    cover_y: Optional[int] = None

    @field_validator('cover_x', 'cover_y', mode='before')
    @classmethod
    def convert_empty_to_none(cls, v):
        """将空字符串转换为None"""
        if v == '' or v is None:
            return None
        return v

class DoubanJsonSearchResponse(BaseModel):
    subjects: List[DoubanJsonSearchSubject]

# --- Main Metadata Source Class ---
class DoubanMetadataSource(BaseMetadataSource): # type: ignore
    provider_name = "douban" # type: ignore
    test_url = "https://movie.douban.com"
    has_force_aux_search_toggle = True # 新增：硬编码标志
    is_failover_source = True
    supports_episode_urls = True  # 支持获取分集URL
    async def _create_client(self) -> httpx.AsyncClient:
        """Creates an httpx.AsyncClient with Douban cookie and proxy settings."""
        cookie = await self.config_manager.get("doubanCookie", "")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if cookie:
            headers["Cookie"] = cookie

        proxy_url = await self.config_manager.get("proxyUrl", "")
        proxy_enabled_globally = (await self.config_manager.get("proxyEnabled", "false")).lower() == 'true'

        async with self._session_factory() as session:
            metadata_settings = await crud.get_all_metadata_source_settings(session)

        provider_setting = next((s for s in metadata_settings if s['providerName'] == self.provider_name), None)
        use_proxy_for_this_provider = provider_setting.get('useProxy', False) if provider_setting else False

        proxy_to_use = proxy_url if proxy_enabled_globally and use_proxy_for_this_provider and proxy_url else None

        return httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True, proxy=proxy_to_use)

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        self.logger.info(f"豆瓣: 正在使用JSON API搜索 '{keyword}'")
        try:
            provider_setting = await self._get_provider_setting()
            log_raw = provider_setting.get('logRawResponses', False)

            async def log_response(name: str, response: httpx.Response):
                if log_raw:
                    log_message = (
                        f"Douban API Response for '{name}':\n"
                        f"URL: {response.url}\n"
                        f"Status Code: {response.status_code}\n"
                        f"Body: {response.text}\n"
                        "----------------------------------------"
                    )
                    metadata_logger.info(log_message)

            async with await self._create_client() as client:
                movie_task = client.get("https://movie.douban.com/j/search_subjects", params={"type": "movie", "tag": keyword, "page_limit": 20, "page_start": 0})
                tv_task = client.get("https://movie.douban.com/j/search_subjects", params={"type": "tv", "tag": keyword, "page_limit": 20, "page_start": 0})
                movie_res, tv_res = await asyncio.gather(movie_task, tv_task, return_exceptions=True)

                all_subjects = []
                # 记录每个subject的类型
                subject_types = {}

                # 处理电影结果
                if isinstance(movie_res, httpx.Response) and movie_res.status_code == 200:
                    await log_response(f"search '{keyword}'", movie_res)
                    try:
                        data = DoubanJsonSearchResponse.model_validate(movie_res.json())
                        all_subjects.extend(data.subjects)
                        for subject in data.subjects:
                            subject_types[subject.id] = "movie"
                    except ValidationError as e:
                        self.logger.warning(f"解析豆瓣JSON API响应失败: {e} - 响应: {movie_res.text[:200]}")
                elif isinstance(movie_res, Exception):
                    self.logger.error(f"请求豆瓣JSON API时发生网络错误: {movie_res}")

                # 处理电视剧结果
                if isinstance(tv_res, httpx.Response) and tv_res.status_code == 200:
                    await log_response(f"search '{keyword}'", tv_res)
                    try:
                        data = DoubanJsonSearchResponse.model_validate(tv_res.json())
                        all_subjects.extend(data.subjects)
                        for subject in data.subjects:
                            subject_types[subject.id] = "tv_series"
                    except ValidationError as e:
                        self.logger.warning(f"解析豆瓣JSON API响应失败: {e} - 响应: {tv_res.text[:200]}")
                elif isinstance(tv_res, Exception):
                    self.logger.error(f"请求豆瓣JSON API时发生网络错误: {tv_res}")

                seen_ids = set()
                results = []
                for subject in all_subjects:
                    if subject.id not in seen_ids:
                        results.append(models.MetadataDetailsResponse(
                            id=subject.id, doubanId=subject.id, title=subject.title,
                            details=f"评分: {subject.rate}", imageUrl=subject.cover,
                            type=subject_types.get(subject.id, "unknown"),  # 从记录的类型中获取
                            supportsEpisodeUrls=True  # 豆瓣源支持获取分集URL
                        ))
                        seen_ids.add(subject.id)
                return results
        except Exception as e:
            self.logger.error(f"豆瓣搜索失败，发生意外错误: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="豆瓣搜索时发生内部错误。")

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        self.logger.info(f"豆瓣: 正在获取详情 item_id={item_id}")
        try:
            provider_setting = await self._get_provider_setting()
            log_raw = provider_setting.get('logRawResponses', False)

            async with await self._create_client() as client:
                details_url = f"https://movie.douban.com/subject/{item_id}/"
                response = await client.get(details_url)

                if log_raw:
                    log_message = f"Douban Detail Page Response for ID '{item_id}':\nStatus: {response.status_code}\nBody:\n{response.text[:1000]}...\n----------------------------------------"
                    metadata_logger.info(log_message)

                response.raise_for_status()
                html = response.text

                title_match = re.search(r'<span property="v:itemreviewed">(.*?)</span>', html)
                title = title_match.group(1).strip() if title_match else ""

                aliases_cn = []
                alias_match = re.search(r'<span class="pl">又名:</span>(.*?)<br/>', html)
                if alias_match:
                    aliases_text = alias_match.group(1)
                    aliases_cn = [alias.strip() for alias in aliases_text.split("/") if alias.strip()]

                imdb_id_match = re.search(r'<a href="https://www.imdb.com/title/(tt\d+)"', html)
                imdb_id = imdb_id_match.group(1) if imdb_id_match else None

                # 提取年份信息
                year = None
                year_match = re.search(r'<span class="year">\((\d{4})\)</span>', html)
                if year_match:
                    try:
                        year = int(year_match.group(1))
                    except (ValueError, TypeError):
                        pass

                if title:
                    aliases_cn.insert(0, title)
                aliases_cn = list(dict.fromkeys(aliases_cn))

                return models.MetadataDetailsResponse(
                    id=item_id, doubanId=item_id, title=title,
                    imdbId=imdb_id, aliasesCn=aliases_cn, year=year,
                    supportsEpisodeUrls=True  # 豆瓣源支持获取分集URL
                )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                self.logger.error(f"豆瓣详情页请求被拒绝(403)，可能是Cookie已失效或IP被限制。ID: {item_id}")
                raise HTTPException(status_code=403, detail="豆瓣请求被拒绝，请检查Cookie或网络环境。")
            raise HTTPException(status_code=500, detail=f"请求豆瓣详情时发生错误: {e}")
        except Exception as e:
            self.logger.error(f"解析豆瓣详情页时发生错误: {e}")
            raise HTTPException(status_code=500, detail="解析豆瓣详情页失败。")

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        self.logger.info(f"豆瓣: 正在为 '{keyword}' 搜索别名")
        local_aliases: Set[str] = set()
        try:
            provider_setting = await self._get_provider_setting()
            log_raw = provider_setting.get('logRawResponses', False)

            async with await self._create_client() as client:
                movie_task = client.get("https://movie.douban.com/j/search_subjects", params={"type": "movie", "tag": keyword, "page_limit": 1, "page_start": 0})
                tv_task = client.get("https://movie.douban.com/j/search_subjects", params={"type": "tv", "tag": keyword, "page_limit": 1, "page_start": 0})
                movie_res, tv_res = await asyncio.gather(movie_task, tv_task, return_exceptions=True)

                best_subject_id = None
                if isinstance(movie_res, httpx.Response) and movie_res.status_code == 200:
                    if log_raw:
                        metadata_logger.info(
                            f"Douban Alias Search (Movie) for '{keyword}':\nBody: {movie_res.text}\n----------------------------------------"
                        )
                    if subjects := movie_res.json().get('subjects', []):
                        best_subject_id = subjects[0]['id']
                if not best_subject_id and isinstance(tv_res, httpx.Response) and tv_res.status_code == 200:
                    if log_raw:
                        metadata_logger.info(
                            f"Douban Alias Search (TV) for '{keyword}':\nBody: {tv_res.text}\n----------------------------------------"
                        )
                    if subjects := tv_res.json().get('subjects', []):
                        best_subject_id = subjects[0]['id']

                if best_subject_id:
                    details = await self.get_details(best_subject_id, user)
                    if details and details.aliasesCn:
                        local_aliases.update(details.aliasesCn)
                
                self.logger.info(f"豆瓣辅助搜索成功，找到别名: {[a for a in local_aliases if a]}")
        except Exception as e:
            self.logger.warning(f"豆瓣辅助搜索失败: {e}")
        return {alias for alias in local_aliases if alias}

    async def check_connectivity(self) -> str:
        """检查豆瓣源配置状态"""
        try:
            # 检查Cookie配置
            douban_cookie = await self.config_manager.get("doubanCookie", "")
            if not douban_cookie or douban_cookie.strip() == "":
                return "未配置 (缺少豆瓣Cookie)"

            # 检查Cookie格式是否合理
            if "bid=" not in douban_cookie and "dbcl2=" not in douban_cookie:
                return "配置异常 (Cookie格式不正确)"

            return "配置正常"
        except Exception as e:
            return f"配置检查失败: {e}"

    async def execute_action(self, action_name: str, payload: Dict, user: models.User) -> Any:
        """Douban source does not support custom actions."""
        raise NotImplementedError(f"源 '{self.provider_name}' 不支持任何自定义操作。")

    async def _get_provider_setting(self) -> Dict[str, Any]:
        """辅助函数,用于从数据库获取当前源的设置。"""
        async with self._session_factory() as session:
            settings = await crud.get_all_metadata_source_settings(session)
            provider_setting = next((s for s in settings if s['providerName'] == self.provider_name), None)
            return provider_setting or {}

    async def get_episode_urls(self, metadata_id: str, target_provider: Optional[str] = None) -> List[Tuple[int, str]]:
        """
        获取分集URL列表 (补充源功能)。

        Args:
            metadata_id: 豆瓣条目ID
            target_provider: 目标平台 (tencent/iqiyi/youku/bilibili/mgtv), 如果为None则返回所有平台

        Returns:
            List[Tuple[int, str]]: (集数, 播放URL) 的列表
        """
        return await self._get_episode_urls_from_douban_page(metadata_id, target_provider)

    async def _get_episode_urls_from_douban_page(self, douban_id: str, target_provider: Optional[str] = None) -> List[Tuple[int, str]]:
        """
        从豆瓣电影页面解析播放链接

        Args:
            douban_id: 豆瓣条目ID
            target_provider: 目标平台 (tencent/iqiyi/youku/bilibili/mgtv), 如果为None则返回所有平台

        Returns:
            List[Tuple[int, str]]: (集数, 播放URL) 的列表
        """
        # 平台映射: 你的项目provider名称 -> 豆瓣subtype ID
        provider_to_subtype = {
            "tencent": "1",   # 腾讯视频
            "iqiyi": "9",     # 爱奇艺
            "youku": "3",     # 优酷
            "bilibili": "11", # B站
            "mgtv": "17"      # 芒果TV
        }

        url = f"https://movie.douban.com/subject/{douban_id}/"
        self.logger.info(f"豆瓣: 正在从页面获取播放链接 {url}")

        try:
            async with await self._create_client() as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text

                # 提取sources数据: sources[9] = [...];
                pattern = r'sources\[(\d+)\]\s*=\s*(\[.*?\]);'
                matches = re.findall(pattern, html, re.DOTALL)

                if not matches:
                    self.logger.warning(f"豆瓣: 未在页面中找到播放链接数据 (douban_id={douban_id})")
                    return []

                episode_urls: List[Tuple[int, str]] = []

                for source_id, json_str in matches:
                    # 如果指定了target_provider,只处理对应的source_id
                    if target_provider:
                        expected_subtype = provider_to_subtype.get(target_provider)
                        if expected_subtype and source_id != expected_subtype:
                            continue

                    try:
                        episodes = json.loads(json_str)
                        for ep_data in episodes:
                            ep_num = int(ep_data['ep'])
                            encoded_url = ep_data['play_link']

                            # 解析link2跳转链接: https://www.douban.com/link2/?url=<编码后的URL>&...
                            parsed = urllib.parse.urlparse(encoded_url)
                            query = urllib.parse.parse_qs(parsed.query)

                            if 'url' not in query:
                                self.logger.warning(f"豆瓣: 播放链接格式异常,缺少url参数: {encoded_url}")
                                continue

                            real_url = urllib.parse.unquote(query['url'][0])
                            episode_urls.append((ep_num, real_url))

                    except json.JSONDecodeError as e:
                        self.logger.error(f"豆瓣: 解析播放链接JSON失败 (source_id={source_id}): {e}")
                        continue
                    except (KeyError, ValueError) as e:
                        self.logger.error(f"豆瓣: 解析播放链接数据失败: {e}")
                        continue

                # 按集数排序
                episode_urls.sort(key=lambda x: x[0])

                self.logger.info(f"豆瓣: 成功解析 {len(episode_urls)} 个播放链接")
                return episode_urls

        except httpx.HTTPStatusError as e:
            self.logger.error(f"豆瓣: 获取页面失败 (HTTP {e.response.status_code}): {url}")
            return []
        except Exception as e:
            self.logger.error(f"豆瓣: 解析播放链接时发生异常: {e}", exc_info=True)
            return []