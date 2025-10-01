import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup # type: ignore
from pydantic import BaseModel, Field

from .. import models
from ..config_manager import ConfigManager
from .base import BaseMetadataSource
from ..scrapers.base import get_season_from_title

logger = logging.getLogger(__name__)

# --- Simplified Pydantic Models for 360 API (based on reference implementation) ---

class So360SearchResultItem(BaseModel):
    id: str
    en_id: Optional[str] = Field(None, alias="en_id")
    titleTxt: str
    year: Optional[str] = None
    cover: Optional[str] = None
    cat_id: Optional[str] = Field(None, alias="cat_id")
    cat_name: Optional[str] = Field(None, alias="cat_name")
    playlinks: Dict[str, Any] = Field(default_factory=dict)
    playlinks_year: Optional[Dict[str, List[int]]] = Field(None, alias="playlinks_year")
    seriesPlaylinks: Optional[List[Union[Dict[str, Any], str]]] = Field(None, alias="seriesPlaylinks")
    seriesSite: Optional[str] = Field(None, alias="seriesSite")
    years: Optional[List[int]] = None
    alias: Optional[List[str]] = None
    is_serial: Optional[int] = Field(None, alias="is_serial")

class So360LongData(BaseModel):
    rows: List[So360SearchResultItem] = Field(default_factory=list)

class So360Data(BaseModel):
    longData: Optional[So360LongData] = Field(None, alias="longData")

class So360SearchResponse(BaseModel):
    data: Optional[So360Data] = None

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
        return "tv_series"

# --- Main Scraper Class ---

class So360MetadataSource(BaseMetadataSource):
    provider_name = "360"
    test_url = "https://so.360kan.com"
    is_failover_source = True
    has_force_aux_search_toggle = True

    def __init__(self, session_factory, config_manager: ConfigManager, scraper_manager):
        super().__init__(session_factory, config_manager, scraper_manager)
        self.api_base_url = "https://api.so.360kan.com"
        self.web_base_url = "https://www.360kan.com"

        # 基于参考实现的Cookie和Headers配置
        self.cookies = {
            '__guid': '26972607.2949894437869698600.1752640253092.913',
            'refer_scene': '47007',
            '__huid': '11da4Vxk54oFVy89kXmOuuvPhPxzN45efwa8EHQR4I8Tg%3D',
            '___sid': '26972607.3930629777557762600.1752655408731.65',
            '__DC_gid': '26972607.192430250.1752640253137.1752656674152.17',
            'monitor_count': '12',
        }

        self.headers = {
            'accept': '*/*',
            'accept-language': 'zh-CN,zh;q=0.9',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'script',
            'sec-fetch-mode': 'no-cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        self.client = httpx.AsyncClient(
            headers=self.headers,
            cookies=self.cookies,
            timeout=20.0,
        )

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        """基于参考实现的简化搜索方法"""
        search_url = f"{self.api_base_url}/index"
        params = {
            'force_v': '1',
            'kw': keyword,
            'from': '',
            'pageno': '1',
            'v_ap': '1',
            'tab': 'all',
            'cb': '__jp0'
        }

        try:
            # 设置Referer头
            encoded_keyword = quote(keyword)
            headers = {**self.headers, 'referer': f'https://so.360kan.com/?kw={encoded_keyword}'}

            self.logger.info(f"360搜索: {keyword}")
            response = await self.client.get(search_url, params=params, headers=headers)
            response.raise_for_status()

            # 解析JSONP响应 (参考实现的方式)
            data_text = response.text
            try:
                start_index = data_text.index('(') + 1
                end_index = data_text.rindex(')')
                json_payload = data_text[start_index:end_index]
            except ValueError:
                self.logger.error(f"360搜索失败: 无法解析JSONP响应格式")
                return []

            # 解析JSON数据
            parsed_data = json.loads(json_payload)

            # 调试：记录数据结构类型
            self.logger.debug(f"360搜索: 解析数据类型 {type(parsed_data)}")

            # 检查数据结构并提取rows
            rows = []
            if isinstance(parsed_data, dict):
                # 标准格式: {data: {longData: {rows: [...]}}}
                data_section = parsed_data.get('data', {})
                if isinstance(data_section, dict):
                    long_data = data_section.get('longData', {})
                    if isinstance(long_data, dict):
                        rows = long_data.get('rows', [])
                        self.logger.debug(f"360搜索: 从标准格式提取到 {len(rows)} 条数据")
                    else:
                        self.logger.debug(f"360搜索: longData不是字典类型: {type(long_data)}")
                else:
                    self.logger.debug(f"360搜索: data不是字典类型: {type(data_section)}")
            elif isinstance(parsed_data, list):
                # 直接是列表格式
                rows = parsed_data
                self.logger.debug(f"360搜索: 从列表格式提取到 {len(rows)} 条数据")
            else:
                self.logger.debug(f"360搜索: 未知数据格式: {type(parsed_data)}")

            if not rows:
                self.logger.info(f"360搜索: 未找到'{keyword}'的结果")
                return []
            self.logger.info(f"360搜索: 找到 {len(rows)} 个结果")

            # 过滤和转换结果
            results: List[models.MetadataDetailsResponse] = []
            skip_keywords = ["花絮", "独家专访", "幕后", "专访", "无障碍", "路演"]

            for item in rows:
                title = item.get('titleTxt', '')

                # 跳过包含特定关键词的内容
                if any(skip_word in title for skip_word in skip_keywords):
                    continue

                # 检查标题是否包含搜索关键词
                if keyword.lower() not in title.lower():
                    continue

                # 确定媒体类型
                cat_name = item.get('cat_name', '')
                if '电影' in cat_name:
                    media_type = "movie"
                elif '电视' in cat_name or '动漫' in cat_name:
                    media_type = "tv_series"
                else:
                    media_type = "other"

                media_id = item.get('en_id') or item.get('id', '')

                results.append(models.MetadataDetailsResponse(
                    id=str(media_id),
                    provider=self.provider_name,
                    title=title,
                    type=media_type,
                    imageUrl=item.get('cover'),
                    year=int(item['year']) if item.get('year') and str(item['year']).isdigit() else None,
                    aliasesCn=item.get('alias', []),
                    extra={"item_data": item}  # 保存原始数据用于后续处理
                ))

            self.logger.info(f"360搜索: 过滤后返回 {len(results)} 个结果")
            return results

        except httpx.ConnectError as e:
            self.logger.error(f"360搜索连接失败 '{keyword}': {e}")
            return []
        except json.JSONDecodeError as e:
            self.logger.error(f"360搜索JSON解析失败 '{keyword}': {e}")
            return []
        except Exception as e:
            self.logger.error(f"360搜索失败 '{keyword}': {e}", exc_info=True)
            return []

    async def find_url_for_provider(self, keyword: str, target_provider: str, user: models.User, season: Optional[int] = None, episode_index: Optional[int] = None) -> Optional[str]:
        """通过360搜索查找指定平台（如腾讯、B站）的播放链接。"""
        provider_map = { "tencent": "qq", "iqiyi": "qiyi", "youku": "youku", "bilibili": "bilibili", "mgtv": "imgo" }
        target_site = provider_map.get(target_provider)
        if not target_site:
            self.logger.debug(f"360故障转移：不支持的目标平台 '{target_provider}'")
            return None
        
        # 修正：直接调用 _get_episode_url_from_360 来处理所有逻辑
        # 1. 先进行搜索
        search_results = await self.search(keyword, user)
        if not search_results: return None

        # 2. 智能选择最佳匹配项
        best_match = None
        if season is not None:
            candidates = [r for r in search_results if get_season_from_title(r.title) == season]
            if candidates: best_match = candidates[0]
        else:
            best_match = search_results[0]
        
        if not best_match or not episode_index:
            self.logger.info(f"360故障转移：未找到与 '{keyword}' S{season} 匹配的结果。")
            return None

        # 3. 使用重构的函数获取特定分集的URL
        return await self._get_episode_url_from_360(best_match, episode_index, target_site)

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        possible_paths = [f"/dianshiju/{item_id}.html", f"/dongman/{item_id}.html", f"/dianying/{item_id}.html"]
        try:
            for path in possible_paths:
                detail_url = f"{self.web_base_url}{path}"
                try:
                    response = await self.client.get(detail_url)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, "lxml")
                        script_tag = soup.find("script", string=re.compile(r"window\.g_initialData\s*="))
                        if not script_tag: continue

                        json_str_match = re.search(r"window\.g_initialData\s*=\s*({.*?});", script_tag.string)
                        if not json_str_match: continue
                            
                        initial_data = json.loads(json_str_match.group(1))
                        cover_info_raw = initial_data.get("coverInfo", {}).get("coverInfo")
                        if not cover_info_raw: continue
                            
                        cover_info = So360CoverInfo.model_validate(cover_info_raw)
                        aliases = [cover_info.sub_title] if cover_info.sub_title else []

                        return models.MetadataDetailsResponse(
                            id=item_id,
                            provider=self.provider_name,
                            title=cover_info.title,
                            type=cover_info.media_type,
                            imageUrl=cover_info.cover,
                            details=cover_info.description,
                            aliasesCn=aliases,
                            year=int(cover_info.year) if cover_info.year and cover_info.year.isdigit() else None
                        )
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        continue
                    raise
            
            self.logger.warning(f"无法通过任何已知路径找到 {item_id} 的详情页。")
            return None
        except Exception as e:
            self.logger.error(f"获取360影视详情失败 (ID: {item_id}): {e}", exc_info=True)
            return None

    async def get_comments_by_failover(self, title: str, season: int, episode_index: int, user: models.User) -> Optional[List[dict]]:
        self.logger.info(f"360 Failover: Searching for '{title}' S{season}E{episode_index}")
        search_results = await self.search(keyword=title, user=user)
        if not search_results:
            self.logger.info("360 Failover: Initial search returned no results.")
            return None

        best_match = next((r for r in search_results if get_season_from_title(r.title) == season), search_results[0])
        self.logger.info(f"360 Failover: Found best match: '{best_match.title}' (ID: {best_match.id})")

        episode_url = await self._get_episode_url_from_360(best_match, episode_index, None)
        if not episode_url:
            self.logger.info(f"360 Failover: Could not find a URL for episode {episode_index}.")
            return None
        
        self.logger.info(f"360 Failover: Found episode URL: {episode_url}")

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

    def _convert_hunantv_to_mgtv(self, url: str) -> str:
        m = re.match(r'https?://www\.hunantv\.com/v/1/(\d+)/f/(\d+)\.html', url)
        if m:
            new_url = f'https://www.mgtv.com/b/{m.group(1)}/{m.group(2)}.html'
            self.logger.debug(f"Converted hunantv URL '{url}' to '{new_url}'")
            return new_url
        return url

    async def _get_episode_url_from_360(self, best_match: models.MetadataDetailsResponse, episode_index: int, target_site: Optional[str]) -> Optional[str]:
        """基于参考实现的简化分集获取方法"""
        try:
            item_data = best_match.extra.get("item_data", {}) if best_match.extra else {}

            cat_id = item_data.get('cat_id', '')
            cat_name = item_data.get('cat_name', '')
            ent_id = item_data.get('id', '')
            en_id = item_data.get('en_id', '')
            playlinks = item_data.get('playlinks', {})

            platform_order = ['qq', 'qiyi', 'youku', 'bilibili', 'bilibili1', 'imgo']
            sites_to_check = [target_site] if target_site else [site for site in platform_order if site in playlinks]

            for site in sites_to_check:
                self.logger.info(f"360 Failover: 检查平台 '{site}' 的分集")
                episodes = await self._get_platform_episodes_simple(cat_id, ent_id, en_id, site, item_data)
                if episodes and len(episodes) >= episode_index:
                    episode_data = episodes[episode_index - 1]
                    url = episode_data.get('url') if isinstance(episode_data, dict) else episode_data if isinstance(episode_data, str) else None
                    if url:
                        return self._convert_hunantv_to_mgtv(url)
            return None
        except Exception as e:
            self.logger.error(f"360 Failover: 获取分集URL失败: {e}", exc_info=True)
            return None

    async def _get_platform_episodes_simple(self, cat_id: str, ent_id: str, en_id: str, site: str, item_data: dict) -> List[Any]:
        """基于参考实现的简化分集获取方法"""
        try:
            # 综艺类型处理
            if cat_id == '3' or (item_data.get('cat_name') and '综艺' in item_data.get('cat_name', '')):
                return await self._get_zongyi_episodes(ent_id, site, item_data)
            else:
                # 电视剧/动漫处理
                return await self._get_series_episodes(cat_id, en_id or ent_id, site)
        except Exception as e:
            self.logger.error(f"360获取分集失败 (site={site}): {e}")
            return []

    async def _get_zongyi_episodes(self, ent_id: str, site: str, item_data: dict) -> List[Any]:
        """获取综艺分集 (基于参考实现)"""
        all_episodes = []

        # 获取年份列表
        years = []
        if item_data.get('playlinks_year') and site in item_data['playlinks_year']:
            years = [str(y) for y in item_data['playlinks_year'][site] if y]
        elif item_data.get('years'):
            years = [str(y) for y in item_data['years'] if y]
        elif item_data.get('year'):
            years = [str(item_data['year'])]

        if not years:
            years = ['']

        for year in years:
            offset = 0
            count = 8
            cb_index = 7

            while True:
                cb = f'__jp{cb_index}'
                cb_index += 1
                params = {
                    'site': site,
                    'y': year,
                    'entid': ent_id,
                    'offset': offset,
                    'count': count,
                    'v_ap': '1',
                    'cb': cb
                }

                try:
                    url = f'{self.api_base_url}/episodeszongyi'
                    resp = await self.client.get(url, params=params)
                    data_text = resp.text
                    json_data = data_text[data_text.index('(') + 1:data_text.rindex(')')]
                    parsed = json.loads(json_data)

                    if parsed['code'] == 0 and parsed['data']:
                        episodes = parsed['data'].get('list', [])
                        if episodes is None:
                            episodes = []
                        all_episodes.extend(episodes)
                        if len(episodes) < count:
                            break
                        offset += count
                    else:
                        break
                except Exception as e:
                    self.logger.error(f"360获取综艺分集失败 (year={year}): {e}")
                    break

        return all_episodes

    async def _get_series_episodes(self, cat_id: str, ent_id: str, site: str) -> List[Any]:
        """获取电视剧/动漫分集 (基于参考实现)"""
        s_param = json.dumps([{"cat_id": cat_id, "ent_id": ent_id, "site": site}])
        params = {
            'v_ap': '1',
            's': s_param,
            'cb': '__jp8'
        }

        try:
            resp = await self.client.get(f'{self.api_base_url}/episodesv2', params=params)
            data_text = resp.text
            json_data = data_text[data_text.index('(') + 1:data_text.rindex(')')]
            parsed = json.loads(json_data)

            if parsed['code'] == 0 and len(parsed['data']) > 0:
                series_html = parsed['data'][0].get('seriesHTML', {})
                if 'seriesPlaylinks' in series_html:
                    return series_html['seriesPlaylinks']
        except Exception as e:
            self.logger.error(f"360获取剧集分集失败: {e}")

        return []

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        search_results = await self.search(keyword, user)
        aliases: Set[str] = set()
        for item in search_results:
            aliases.add(item.title)
            if item.aliasesCn:
                aliases.update(item.aliasesCn)
        return {alias for alias in aliases if alias}

    async def check_connectivity(self) -> str:
        """检查360源配置状态"""
        # 360源不需要特殊配置，只要Cookie和Headers正确即可
        if self.cookies and self.headers:
            return "配置正常"
        else:
            return "配置异常 (缺少必要的Cookie或Headers)"
            
    async def execute_action(self, action_name: str, payload: Dict[str, Any], user: models.User, request: Any) -> Any:
        raise NotImplementedError(f"操作 '{action_name}' 在 {self.provider_name} 中未实现。")

    async def close(self):
        await self.client.aclose()
