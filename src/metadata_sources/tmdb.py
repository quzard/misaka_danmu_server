import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Set

import httpx
from pydantic import BaseModel, Field, ValidationError

from .. import crud, models
from .base import BaseMetadataSource

logger = logging.getLogger(__name__)

def _is_cjk(s: str) -> bool:
    if not s: return False
    return any('\u4e00' <= char <= '\u9fff' or '\u3040' <= char <= '\u309f' or '\u30a0' <= char <= '\u30ff' for char in s)

def _clean_movie_title(title: Optional[str]) -> Optional[str]:
    if not title: return None
    phrases_to_remove = ["劇場版", "the movie"]
    cleaned_title = title
    for phrase in phrases_to_remove:
        cleaned_title = re.sub(r'\s*' + re.escape(phrase) + r'\s*:?', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'\s{2,}', ' ', cleaned_title).strip().strip(':- ')
    return cleaned_title

class TMDBExternalIDs(BaseModel):
    imdb_id: Optional[str] = None
    tvdb_id: Optional[int] = None

class TMDBAlternativeTitle(BaseModel):
    iso_3166_1: str
    title: str
    type: str

class TMDBAlternativeTitles(BaseModel):
    titles: List[TMDBAlternativeTitle] = []

class TMDBTVDetails(BaseModel):
    id: int
    name: str
    original_language: str
    original_name: str
    alternative_titles: Optional[TMDBAlternativeTitles] = None
    external_ids: Optional[TMDBExternalIDs] = None

class TMDBMovieDetails(BaseModel):
    id: int
    original_language: str
    title: str
    original_title: str
    alternative_titles: Optional[TMDBAlternativeTitles] = None
    external_ids: Optional[TMDBExternalIDs] = None

class TMDBEpisodeWithStill(BaseModel):
    id: int
    still_path: Optional[str] = None

class TMDBSeasonDetails(BaseModel):
    episodes: List[TMDBEpisodeWithStill]

class TmdbMetadataSource(BaseMetadataSource):
    provider_name = "tmdb"

    async def _create_client(self) -> httpx.AsyncClient:
        api_key_task = self.config_manager.get("tmdbApiKey")
        domain_task = self.config_manager.get("tmdbApiBaseUrl", "https://api.themoviedb.org")
        proxy_url_task = self.config_manager.get("proxyUrl", "")
        proxy_enabled_globally_task = self.config_manager.get("proxyEnabled", "false")
        
        api_key, domain, proxy_url, proxy_enabled_str = await asyncio.gather(
            api_key_task, domain_task, proxy_url_task, proxy_enabled_globally_task
        )

        if not api_key:
            raise ValueError("TMDB API Key not configured.")
        if api_key.startswith("eyJ"):
            raise ValueError("配置的TMDB API Key似乎是v4访问令牌（JWT）。此应用需要v3 API Key。")

        proxy_enabled_globally = proxy_enabled_str.lower() == 'true'
        
        async with self._session_factory() as session:
            metadata_settings = await crud.get_all_metadata_source_settings(session)
        
        tmdb_setting = next((s for s in metadata_settings if s['providerName'] == 'tmdb'), None)
        use_proxy_for_tmdb = tmdb_setting.get('useProxy', False) if tmdb_setting else False

        proxies = proxy_url if proxy_enabled_globally and use_proxy_for_tmdb and proxy_url else None

        cleaned_domain = domain.rstrip('/')
        base_url = cleaned_domain if cleaned_domain.endswith('/3') else f"{cleaned_domain}/3"

        params = {"api_key": api_key}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        return httpx.AsyncClient(base_url=base_url, params=params, headers=headers, timeout=20.0, proxies=proxies)

    async def _get_robust_image_base_url(self) -> str:
        image_base_url_config = await self.config_manager.get("tmdbImageBaseUrl", "https://image.tmdb.org/t/p/w500")
        if '/t/p/' not in image_base_url_config:
            return f"{image_base_url_config.rstrip('/')}/t/p/w500"
        return image_base_url_config

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        if not mediaType or mediaType not in ["tv", "movie"]:
            raise ValueError("TMDB search requires a mediaType ('tv' or 'movie').")
        
        async with await self._create_client() as client:
            params = {"query": keyword, "include_adult": False, "language": "zh-CN"}
            response = await client.get(f"/search/{mediaType}", params=params)
            response.raise_for_status()
            data = response.json().get("results", [])
            
            image_base_url = await self._get_robust_image_base_url()
            
            results = []
            for item in data:
                title = item.get('name') if mediaType == 'tv' else item.get('title')
                release_date = item.get('first_air_date') if mediaType == 'tv' else item.get('release_date')
                details_str = f"{release_date or '未知年份'} / {item.get('original_language', 'N/A')}"
                
                results.append(models.MetadataDetailsResponse(
                    id=str(item['id']),
                    tmdbId=str(item['id']),
                    title=title,
                    imageUrl=f"{image_base_url.rstrip('/')}{item.get('poster_path')}" if item.get('poster_path') else None,
                    details=details_str
                ))
            return results

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        if not mediaType or mediaType not in ["tv", "movie"]:
            raise ValueError("TMDB get_details requires a mediaType ('tv' or 'movie').")

        async with await self._create_client() as client:
            details_cn_task = client.get(f"/{mediaType}/{item_id}", params={"append_to_response": "alternative_titles,external_ids", "language": "zh-CN"})
            details_en_task = client.get(f"/{mediaType}/{item_id}", params={"language": "en-US"})
            details_ja_task = client.get(f"/{mediaType}/{item_id}", params={"language": "ja-JP"})
            details_tw_task = client.get(f"/{mediaType}/{item_id}", params={"language": "zh-TW"})

            responses = await asyncio.gather(details_cn_task, details_en_task, details_ja_task, details_tw_task, return_exceptions=True)
            details_cn_res, details_en_res, details_ja_res, details_tw_res = responses

            if isinstance(details_cn_res, Exception) or details_cn_res.status_code != 200:
                self.logger.error(f"获取 TMDB 中文详情失败 (ID: {item_id}): {details_cn_res}")
                return None
            
            details_json = details_cn_res.json()
            
            name_en, name_jp, name_romaji, aliases_cn = None, None, None, []
            imdb_id, tvdb_id_int = None, None
            
            if mediaType == "tv":
                details = TMDBTVDetails.model_validate(details_json)
                main_title_cn = details.name
            else:
                details = TMDBMovieDetails.model_validate(details_json)
                main_title_cn = details.title

            if details.external_ids:
                imdb_id = details.external_ids.imdb_id
                tvdb_id_int = details.external_ids.tvdb_id

            if details.alternative_titles:
                for alt_title in details.alternative_titles.titles:
                    title_text, alt_type, alt_country = alt_title.title, alt_title.type or "", alt_title.iso_3166_1
                    if not title_text: continue
                    if alt_country == "JP" and alt_type == "Romaji" and not name_romaji and not _is_cjk(title_text):
                        name_romaji = title_text
                    elif alt_country in ["CN", "HK", "TW"] and _is_cjk(title_text):
                        aliases_cn.append(title_text)

            if isinstance(details_en_res, httpx.Response) and details_en_res.status_code == 200:
                name_en = details_en_res.json().get('name') or details_en_res.json().get('title')
            if isinstance(details_ja_res, httpx.Response) and details_ja_res.status_code == 200:
                name_jp = details_ja_res.json().get('name') or details_ja_res.json().get('title')
            if isinstance(details_tw_res, httpx.Response) and details_tw_res.status_code == 200:
                name_tw = details_tw_res.json().get('name') or details_tw_res.json().get('title')
                if name_tw and _is_cjk(name_tw): aliases_cn.append(name_tw)
            
            if main_title_cn: aliases_cn.append(main_title_cn)
            
            image_base_url = await self._get_robust_image_base_url()
            
            return models.MetadataDetailsResponse(
                id=str(details.id), tmdbId=str(details.id), title=main_title_cn,
                imdbId=imdb_id, tvdbId=str(tvdb_id_int) if tvdb_id_int else None,
                nameEn=_clean_movie_title(name_en), nameJp=_clean_movie_title(name_jp),
                nameRomaji=_clean_movie_title(name_romaji),
                aliasesCn=list(dict.fromkeys([_clean_movie_title(alias) for alias in aliases_cn if alias])),
                imageUrl=f"{image_base_url.rstrip('/')}{details_json.get('poster_path')}" if details_json.get('poster_path') else None,
                details=details_json.get('overview')
            )

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        aliases: Set[str] = set()
        try:
            async with await self._create_client() as client:
                tv_task = client.get("/search/tv", params={"query": keyword, "language": "zh-CN"})
                movie_task = client.get("/search/movie", params={"query": keyword, "language": "zh-CN"})
                tv_res, movie_res = await asyncio.gather(tv_task, movie_task, return_exceptions=True)

                tmdb_results = []
                if isinstance(tv_res, httpx.Response) and tv_res.status_code == 200:
                    tmdb_results.extend(tv_res.json().get("results", []))
                if isinstance(movie_res, httpx.Response) and movie_res.status_code == 200:
                    tmdb_results.extend(movie_res.json().get("results", []))

                if tmdb_results:
                    best_match = tmdb_results[0]
                    media_type = "tv" if "name" in best_match else "movie"
                    media_id = best_match['id']
                    details = await self.get_details(str(media_id), user, media_type)
                    if details:
                        aliases.add(details.title)
                        if details.nameEn: aliases.add(details.nameEn)
                        if details.nameJp: aliases.add(details.nameJp)
                        aliases.update(details.aliasesCn)
        except Exception as e:
            self.logger.warning(f"TMDB辅助搜索失败: {e}")
        return {alias for alias in aliases if alias}

    async def check_connectivity(self) -> str:
        try:
            async with await self._create_client() as client:
                response = await client.get("/configuration")
                return "连接成功" if response.status_code == 200 else f"连接失败 (状态码: {response.status_code})"
        except ValueError as e:
            return f"未配置: {e}"
        except Exception as e:
            return f"连接失败: {e}"

    async def execute_action(self, action_name: str, payload: Dict[str, Any], user: models.User) -> Any:
        async with await self._create_client() as client:
            if action_name == "get_episode_groups":
                tmdb_id = payload.get("tmdbId")
                if not tmdb_id: raise ValueError("缺少 tmdbId")
                response = await client.get(f"/tv/{tmdb_id}/episode_groups")
                response.raise_for_status()
                return response.json().get("results", [])
            elif action_name == "get_all_episodes":
                group_id = payload.get("egid")
                tv_id = payload.get("tmdbId")
                if not group_id or not tv_id: raise ValueError("缺少 egid 或 tmdbId")
                
                zh_task = client.get(f"/tv/episode_group/{group_id}", params={"language": "zh-CN"})
                ja_task = client.get(f"/tv/episode_group/{group_id}", params={"language": "ja-JP"})
                zh_response, ja_response = await asyncio.gather(zh_task, ja_task, return_exceptions=True)

                if isinstance(zh_response, Exception) or zh_response.status_code != 200:
                    raise ValueError("获取剧集组详情失败。")
                
                details = models.TMDBEpisodeGroupDetails.model_validate(zh_response.json())
                details.groups.sort(key=lambda g: g.order)

                ja_name_map = {}
                if isinstance(ja_response, httpx.Response) and ja_response.status_code == 200:
                    try:
                        ja_details = models.TMDBEpisodeGroupDetails.model_validate(ja_response.json())
                        for group in ja_details.groups:
                            for episode in group.episodes:
                                ja_name_map[episode.id] = episode.name
                    except ValidationError: pass

                image_map = {}
                season_numbers = {ep.season_number for group in details.groups for ep in group.episodes}
                
                async def fetch_season_stills(season_num: int):
                    try:
                        res = await client.get(f"/tv/{tv_id}/season/{season_num}")
                        res.raise_for_status()
                        season_details = TMDBSeasonDetails.model_validate(res.json())
                        return {ep.id: ep.still_path for ep in season_details.episodes if ep.still_path}
                    except Exception: return {}

                if season_numbers:
                    season_tasks = [fetch_season_stills(s_num) for s_num in season_numbers]
                    season_results = await asyncio.gather(*season_tasks)
                    for season_map in season_results: image_map.update(season_map)

                image_base_url = await self._get_robust_image_base_url()
                enriched_groups = []
                for group in details.groups:
                    enriched_episodes = [
                        models.EnrichedTMDBEpisodeInGroupDetail(
                            id=ep.id, name=ep.name, episodeNumber=ep.episode_number,
                            seasonNumber=ep.season_number, airDate=ep.air_date,
                            overview=ep.overview, order=ep.order,
                            nameJp=ja_name_map.get(ep.id),
                            imageUrl=f"{image_base_url.rstrip('/')}{image_map.get(ep.id)}" if image_map.get(ep.id) else None
                        ) for ep in group.episodes
                    ]
                    enriched_groups.append(models.EnrichedTMDBGroupInGroupDetail(
                        id=group.id, name=group.name, order=group.order, episodes=enriched_episodes
                    ))
                return models.EnrichedTMDBEpisodeGroupDetails(**details.model_dump(exclude={'groups'}), groups=enriched_groups)
            elif action_name == "update_mappings":
                tmdb_id = payload.get("tmdbId")
                group_id = payload.get("groupId")
                if not tmdb_id or not group_id: raise ValueError("缺少 tmdbId 或 groupId")
                await self.update_tmdb_mappings(int(tmdb_id), group_id, user)
                return {"message": "映射更新成功"}
        return await super().execute_action(action_name, payload, user)

    async def update_tmdb_mappings(self, tmdb_tv_id: int, group_id: str, user: models.User):
        self.logger.info(f"TMDB插件: 正在为 TV ID {tmdb_tv_id} 和 Group ID {group_id} 更新映射...")
        async with await self._create_client() as client:
            response = await client.get(f"/tv/episode_group/{group_id}", params={"language": "zh-CN"})
            response.raise_for_status()
            group_details = models.TMDBEpisodeGroupDetails.model_validate(response.json())
            async with self._session_factory() as session:
                await crud.save_tmdb_episode_group_mappings(
                    session=session, tmdb_tv_id=tmdb_tv_id, group_id=group_id, group_details=group_details
                )
        self.logger.info(f"TMDB插件: 映射更新完成。")
