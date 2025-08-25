import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

import httpx
from bs4 import BeautifulSoup # type: ignore
from pydantic import BaseModel, Field, ValidationError

from .. import models
from .base import BaseMetadataSource

logger = logging.getLogger(__name__)

# --- Pydantic Models for 360 API ---

class So360PlayLink(BaseModel):
    play_link: Optional[str] = Field(None, alias="play_link")

class So360SearchResultItem(BaseModel):
    title: str
    play_link_obj: Optional[So360PlayLink] = Field(None, alias="play_link_obj")

    @property
    def composite_id(self) -> Optional[str]:
        if self.play_link_obj and self.play_link_obj.play_link:
            match = re.search(r'/(tv|va|ct|mv)/([a-zA-Z0-9=]+)\.html', self.play_link_obj.play_link)
            if match:
                prefix, b64_id = match.groups()
                return f"{prefix}_{b64_id}"
        return None

class So360SearchRes(BaseModel):
    res: List[So360SearchResultItem] = Field(default_factory=list)

class So360SearchResult(BaseModel):
    result: Optional[So360SearchRes] = None

class So360SearchResponse(BaseModel):
    data: Optional[So360SearchResult] = None

class So360CoverInfo(BaseModel):
    id: str
    title: str
    sub_title: Optional[str] = Field(None, alias="sub_title")
    description: Optional[str] = None
    cover: Optional[str] = None
    year: Optional[str] = None
    cat: Optional[str] = None  # e.g., "动漫,日本"

    @property
    def media_type(self) -> str:
        if not self.cat:
            return "other"
        if "电影" in self.cat:
            return "movie"
        # "动漫" or "电视剧" are both treated as tv_series for simplicity
        return "tv_series"

# --- Main Scraper Class ---

class So360MetadataSource(BaseMetadataSource):
    provider_name = "360"

    def __init__(self, session_factory, config_manager, scraper_manager):
        super().__init__(session_factory, config_manager, scraper_manager)
        self.api_base_url = "https://api.so.360.cn"
        self.web_base_url = "https://www.360kan.com"
        self.client = httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            timeout=20.0,
            follow_redirects=True
        )

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        search_url = f"{self.api_base_url}/search/index"
        params = {
            "kw": keyword,
            "from": "so_video",
            "pn": 1,
            "ps": 20,
            "scene": "video_home",
            "scene_type": 1
        }
        try:
            response = await self.client.get(search_url, params=params)
            response.raise_for_status()
            
            json_text = response.text
            if json_text.startswith('so.jsonp_video_search_result('):
                json_text = json_text[len('so.jsonp_video_search_result('):-1]
            
            data = So360SearchResponse.model_validate(json.loads(json_text))
            
            if not data.data or not data.data.result:
                return []

            tasks = []
            for item in data.data.result.res:
                if item.composite_id:
                    tasks.append(self.get_details(item.composite_id, user))
            
            detailed_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            final_results = []
            for res in detailed_results:
                if isinstance(res, models.MetadataDetailsResponse):
                    final_results.append(res)
                elif isinstance(res, Exception):
                    self.logger.error(f"获取360影视详情时出错: {res}")

            return final_results

        except Exception as e:
            self.logger.error(f"360影视搜索失败 for '{keyword}': {e}", exc_info=True)
            return []

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        try:
            prefix, b64_id = item_id.split("_", 1)
        except ValueError:
            self.logger.error(f"无效的360影视ID格式: {item_id}")
            return None

        detail_url = f"{self.web_base_url}/{prefix}/{b64_id}.html"
        try:
            response = await self.client.get(detail_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "lxml")
            script_tag = soup.find("script", string=re.compile(r"window\.g_initialData"))
            if not script_tag:
                self.logger.warning(f"在页面 {detail_url} 未找到 g_initialData")
                return None

            json_str_match = re.search(r"window\.g_initialData\s*=\s*({.*?});", script_tag.string)
            if not json_str_match:
                self.logger.warning(f"在页面 {detail_url} 未能从script中提取JSON")
                return None
                
            initial_data = json.loads(json_str_match.group(1))
            cover_info_raw = initial_data.get("coverInfo", {}).get("coverInfo")
            if not cover_info_raw:
                self.logger.warning(f"在页面 {detail_url} 的JSON中未找到 coverInfo")
                return None
                
            cover_info = So360CoverInfo.model_validate(cover_info_raw)
            
            aliases = [cover_info.sub_title] if cover_info.sub_title else []

            return models.MetadataDetailsResponse(
                id=item_id,
                title=cover_info.title,
                type=cover_info.media_type,
                imageUrl=cover_info.cover,
                details=cover_info.description,
                aliasesCn=aliases,
                year=int(cover_info.year) if cover_info.year and cover_info.year.isdigit() else None
            )
        except Exception as e:
            self.logger.error(f"获取360影视详情失败 (URL: {detail_url}): {e}", exc_info=True)
            return None

    async def get_comments_by_failover(self, title: str, season: int, episode_index: int, user: models.User) -> Optional[List[dict]]:
        self.logger.info(f"360 Failover: Searching for '{title}' S{season}E{episode_index}")
        
        # 1. Search 360 for the anime
        search_results = await self.search(keyword=title, user=user)
        if not search_results:
            self.logger.info("360 Failover: Initial search returned no results.")
            return None

        # 2. Find the best match
        best_match = next((r for r in search_results if r.season == season), search_results[0])
        self.logger.info(f"360 Failover: Found best match: '{best_match.title}' (ID: {best_match.id})")

        # 3. Get episode URL from 360's other platform links
        episode_url = await self._get_episode_url_from_360(best_match.id, episode_index)
        if not episode_url:
            self.logger.info(f"360 Failover: Could not find a URL for episode {episode_index}.")
            return None
        
        self.logger.info(f"360 Failover: Found episode URL: {episode_url}")

        # 4. Use ScraperManager to get comments from the URL
        try:
            scraper = self.scraper_manager.get_scraper_by_domain(episode_url)
            if not scraper:
                self.logger.warning(f"360 Failover: No scraper available for domain of URL: {episode_url}")
                return None
            
            provider_episode_id = await scraper.get_id_from_url(episode_url)
            if not provider_episode_id:
                self.logger.warning(f"360 Failover: Could not extract ID from URL: {episode_url}")
                return None
            
            episode_id_for_comments = scraper.format_episode_id_for_comments(provider_episode_id)
            self.logger.info(f"360 Failover: Getting comments from provider '{scraper.provider_name}' with ID '{episode_id_for_comments}'")
            
            comments = await scraper.get_comments(episode_id_for_comments)
            return comments
        except Exception as e:
            self.logger.error(f"360 Failover: Error getting comments from URL '{episode_url}': {e}", exc_info=True)
            return None

    async def _get_episode_url_from_360(self, media_id: str, episode_index: int) -> Optional[str]:
        try:
            params = {'kw': media_id, 'from': 'so_video', 'force_v': '1', 'v_ap': '1', 'tab': 'all', 'cb': '__jp0'}
            response = await self.client.get(f"{self.api_base_url}/index", params=params)
            response.raise_for_status()
            json_text = response.text
            if json_text.startswith('__jp0('):
                json_text = json_text[len('__jp0('):-1]
            
            data = json.loads(json_text)
            item_data = data.get('data', {}).get('longData', {}).get('rows', [{}])[0]

            cat_id = item_data.get('cat_id')
            ent_id = item_data.get('id')
            cat_name = item_data.get('cat_name')
            year = item_data.get('year')
            playlinks = item_data.get('playlinks', {})

            platform_order = ['qq', 'qiyi', 'youku', 'bilibili', 'bilibili1', 'imgo']
            
            for site in platform_order:
                if site in playlinks:
                    self.logger.info(f"360 Failover: Checking platform '{site}' for episodes.")
                    episodes = await self._get_360_platform_episodes(cat_id, ent_id, site, cat_name, year, item_data)
                    if episodes and len(episodes) >= episode_index:
                        episode_data = episodes[episode_index - 1]
                        url = episode_data.get('url') if isinstance(episode_data, dict) else episode_data if isinstance(episode_data, str) else None
                        if url: return url
            return None
        except Exception as e:
            self.logger.error(f"360 Failover: _get_episode_url_from_360 failed: {e}", exc_info=True)
            return None

    async def _get_360_platform_episodes(self, cat_id, ent_id, site, cat_name, year, item) -> List[Any]:
        if (cat_id == '3' or (cat_name and '综艺' in cat_name)):
            # Logic for variety shows (paginated)
            # This part is complex and less relevant for anime, so keeping it simple for now.
            # A full implementation would handle pagination for `episodeszongyi`.
            return [] 
        else:
            s_param = json.dumps([{"cat_id": cat_id, "ent_id": ent_id, "site": site}])
            params = {'v_ap': '1', 's': s_param, 'cb': '__jp8'}
            resp = await self.client.get(f'{self.api_base_url}/episodesv2', params=params)
            json_text = resp.text
            if json_text.startswith('__jp8('):
                json_text = json_text[len('__jp8('):-1]
            parsed = json.loads(json_text)
            if parsed.get('code') == 0 and parsed.get('data'):
                series_html = parsed['data'][0].get('seriesHTML', {})
                if 'seriesPlaylinks' in series_html:
                    return series_html['seriesPlaylinks']
        return []

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        search_results = await self.search(keyword, user)
        aliases: Set[str] = set()
        if search_results:
            best_match = search_results[0]
            aliases.add(best_match.title)
            if best_match.aliasesCn:
                aliases.update(best_match.aliasesCn)
        return {alias for alias in aliases if alias}

    async def check_connectivity(self) -> str:
        try:
            response = await self.client.get(self.web_base_url, timeout=10.0)
            if response.status_code == 200:
                return "连接成功"
            return f"连接失败 (状态码: {response.status_code})"
        except Exception as e:
            self.logger.error(f"360影视连接检查失败: {e}")
            return "连接失败"
            
    async def execute_action(self, action_name: str, payload: Dict[str, Any], user: models.User, request) -> Any:
        return await super().execute_action(action_name, payload, user, request)

    async def close(self):
        await self.client.aclose()
