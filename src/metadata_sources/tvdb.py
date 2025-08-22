import logging
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timedelta
import asyncio

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from .. import crud, models
from .base import BaseMetadataSource, HTTPStatusError

logger = logging.getLogger(__name__)

# --- TVDB Token Management ---
# Module-level cache for the TVDB JWT token
_tvdb_token_cache: Dict[str, Any] = {"token": None, "expires_at": datetime.utcnow()}

# --- Pydantic Models for TVDB ---
class TvdbSearchResult(BaseModel):
    tvdb_id: str
    name: str
    image_url: Optional[str] = None
    overview: Optional[str] = None
    year: Optional[str] = None
    type: str

class TvdbSearchResponse(BaseModel):
    data: List[TvdbSearchResult]

class TvdbAlias(BaseModel):
    language: str
    name: str

class TvdbRemoteId(BaseModel):
    id: str
    type: int
    sourceName: str

class TvdbDetailsData(BaseModel):
    id: int
    name: str
    translations: Optional[Dict[str, Optional[str]]] = None
    aliases: Optional[List[TvdbAlias]] = None
    overview: Optional[str] = None
    image: Optional[str] = None
    first_aired: Optional[str] = Field(None, alias="firstAired")
    last_aired: Optional[str] = Field(None, alias="lastAired")
    year: Optional[str] = None
    remote_ids: Optional[List[TvdbRemoteId]] = Field(None, alias="remoteIds")

class TvdbExtendedDetailsResponse(BaseModel):
    data: TvdbDetailsData

class TvdbMetadataSource(BaseMetadataSource):
    provider_name = "tvdb"

    async def _refresh_tvdb_token(self, client: httpx.AsyncClient) -> str:
        """Refreshes the TVDB token if necessary."""
        global _tvdb_token_cache
        if _tvdb_token_cache["token"] and _tvdb_token_cache["expires_at"] > datetime.utcnow():
            return _tvdb_token_cache["token"]

        self.logger.info("TVDB token expired or not found, requesting a new one.")
        api_key = await self.config_manager.get("tvdbApiKey", "")
        if not api_key:
            raise ValueError("TVDB API Key not configured.")
        
        try:
            response = await client.post("/login", json={"apikey": api_key})
            response.raise_for_status()
            token = response.json().get("data", {}).get("token")
            if not token:
                raise ValueError("Login response did not contain a token.")

            _tvdb_token_cache["token"] = token
            _tvdb_token_cache["expires_at"] = datetime.utcnow() + timedelta(hours=23)
            self.logger.info("Successfully obtained a new TVDB token.")
            return token
        except Exception as e:
            self.logger.error(f"Failed to get TVDB token: {e}", exc_info=True)
            raise ValueError("TVDB authentication failed.")

    async def _create_client(self) -> httpx.AsyncClient:
        """Creates an httpx.AsyncClient with TVDB auth and proxy settings."""
        proxy_url = await self.config_manager.get("proxy_url", "")
        proxy_enabled_globally = (await self.config_manager.get("proxy_enabled", "false")).lower() == 'true'

        async with self._session_factory() as session:
            metadata_settings = await crud.get_all_metadata_source_settings(session)

        provider_setting = next((s for s in metadata_settings if s['providerName'] == self.provider_name), None)
        use_proxy_for_this_provider = provider_setting.get('use_proxy', False) if provider_setting else False
        proxy_to_use = proxy_url if proxy_enabled_globally and use_proxy_for_this_provider and proxy_url else None
        
        client = httpx.AsyncClient(base_url="https://api4.thetvdb.com/v4", timeout=20.0, proxies=proxy_to_use)
        
        try:
            token = await self._refresh_tvdb_token(client)
            client.headers.update(
                {"Authorization": f"Bearer {token}", "User-Agent": "DanmuApiServer/1.0"}
            )
        except ValueError as e:
            self.logger.error(f"Could not create authenticated TVDB client: {e}")

        return client

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        self.logger.info(f"TVDB: Searching for '{keyword}'")
        try:
            async with await self._create_client() as client:
                response = await client.get("/search", params={"query": keyword})
                response.raise_for_status()
                results = TvdbSearchResponse.model_validate(response.json()).data
                
                formatted_results = []
                for item in results:
                    details_parts = []
                    type_map = {"series": "电视剧", "movie": "电影", "person": "人物", "company": "公司"}
                    details_parts.append(f"类型: {type_map.get(item.type, item.type)}")
                    if item.year:
                        details_parts.append(f"年份: {item.year}")
                    
                    details_str = " / ".join(details_parts)
                    
                    if item.overview:
                        details_str += f" / {item.overview[:100]}..."

                    formatted_results.append(
                        models.MetadataDetailsResponse(
                            id=item.tvdb_id, tvdbId=item.tvdb_id, title=item.name,
                            details=details_str, imageUrl=item.image_url,
                        )
                    )
                return formatted_results
        except ValueError as e: # Catches API key error
            raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(e))
        except HTTPStatusError as e:
            detail = f"TVDB服务返回错误: {e.response.status_code}"
            if e.response.status_code == 401:
                detail += "，请检查您的API Key是否正确或Token是否失效。"
            self.logger.error(f"TVDB搜索失败，HTTP错误: {e.response.status_code} for URL: {e.request.url}")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
        except Exception as e:
            self.logger.error(f"TVDB搜索失败，发生意外错误: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="TVDB搜索时发生内部错误。")

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        self.logger.info(f"TVDB: Getting details for id={item_id}")
        try:
            async with await self._create_client() as client:
                response = await client.get(f"/series/{item_id}/extended")
                if response.status_code == 404: return None
                response.raise_for_status()
                
                details = TvdbExtendedDetailsResponse.model_validate(response.json()).data

                imdb_id, tmdb_id = None, None
                if remote_ids := details.get('remoteIds'):
                    imdb_entry = next((rid for rid in remote_ids if rid.get('sourceName') == 'IMDB'), None)
                    tmdb_entry = next((rid for rid in remote_ids if rid.get('sourceName') == 'TheMovieDB.com'), None)
                    if imdb_entry: imdb_id = imdb_entry.get('id')
                    if tmdb_entry: tmdb_id = tmdb_entry.get('id')

                name_cn, name_en, name_jp, name_romaji, other_cn_aliases = None, None, None, None, []
                if details.translations:
                    name_cn, name_en, name_jp, name_romaji = details.translations.get("zho"), details.translations.get("eng"), details.translations.get("jpn"), details.translations.get("rom")
                
                if details.aliases:
                    for alias in details.aliases:
                        if alias.language == 'zh':
                            if not name_cn: name_cn = alias.name
                            elif alias.name != name_cn: other_cn_aliases.append(alias.name)
                        elif alias.language == 'en' and not name_en: name_en = alias.name
                        elif alias.language == 'ja' and not name_jp: name_jp = alias.name

                if not name_cn: name_cn = details.name

                return models.MetadataDetailsResponse(
                    id=str(details.id), tvdbId=str(details.id), title=name_cn,
                    nameEn=name_en, nameJp=name_jp, nameRomaji=name_romaji,
                    aliasesCn=list(dict.fromkeys(other_cn_aliases)),
                    imdbId=imdb_id, tmdbId=tmdb_id,
                    details=details.overview, imageUrl=details.image
                )
        except Exception as e:
            self.logger.error(f"获取 TVDB 详情失败 (ID: {item_id}): {e}", exc_info=True)
            return None

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        self.logger.info(f"TVDB: Searching aliases for '{keyword}'")
        local_aliases: Set[str] = set()
        try:
            async with await self._create_client() as client:
                search_response = await client.get("/search", params={"query": keyword})
                search_response.raise_for_status()
                search_results = TvdbSearchResponse.model_validate(search_response.json()).data

                if not search_results: return local_aliases

                best_match_id = search_results[0].tvdb_id
                details = await self.get_details(best_match_id, user)

                if details:
                    if details.title: local_aliases.add(details.title)
                    if details.nameEn: local_aliases.add(details.nameEn)
                    if details.aliasesCn: local_aliases.update(details.aliasesCn)

                self.logger.info(f"TVDB辅助搜索成功，找到别名: {[a for a in local_aliases if a]}")
        except Exception as e:
            self.logger.warning(f"TVDB辅助搜索失败: {e}")

        return {alias for alias in local_aliases if alias}

    async def check_connectivity(self) -> str:
        try:
            async with await self._create_client() as client:
                # A simple search is a good way to check connectivity and auth
                response = await client.get("/search", params={"query": "test"})
                if response.status_code == 200:
                    return "连接成功"
                elif response.status_code == 401:
                    return "连接失败 (API Key或Token无效)"
                else:
                    return f"连接失败 (状态码: {response.status_code})"
        except ValueError as e:
            return f"未配置: {e}"
        except Exception as e:
            return f"连接失败: {e}"

    async def execute_action(self, action_name: str, payload: Dict, user: models.User) -> Any:
        """TVDB source does not support custom actions."""
        raise NotImplementedError(f"源 '{self.provider_name}' 不支持任何自定义操作。")