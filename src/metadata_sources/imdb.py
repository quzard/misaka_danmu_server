import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Final

import httpx
from pydantic import BaseModel, Field
from fastapi import HTTPException, Request

from .. import models
from .. import crud
from .base import BaseMetadataSource

logger = logging.getLogger(__name__)

# Cache lifespan in seconds (24 hours)
CACHE_LIFESPAN: Final[int] = 86400

# --- Enums ---
class ImdbType(Enum):
    """IMDb media types"""
    TV_SERIES = "tvSeries"
    TV_MINI_SERIES = "tvMiniSeries"
    MOVIE = "movie"
    TV_MOVIE = "tvMovie"
    MUSIC_VIDEO = "musicVideo"
    TV_SHORT = "tvShort"
    SHORT = "short"
    TV_EPISODE = "tvEpisode"
    TV_SPECIAL = "tvSpecial"
    VIDEO_GAME = "videoGame"
    VIDEO = "video"
    PODCAST_SERIES = "podcastSeries"
    PODCAST_EPISODE = "podcastEpisode"

# --- Pydantic Models for IMDb API (api.imdbapi.dev) ---
class ImdbApiImage(BaseModel):
    """Image model for IMDb API"""
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    type: Optional[str] = None

class ImdbApiCountry(BaseModel):
    """Country model for IMDb API"""
    code: Optional[str] = None  # ISO 3166-1 alpha-2
    name: Optional[str] = None

class ImdbApiLanguage(BaseModel):
    """Language model for IMDb API"""
    code: Optional[str] = None  # ISO 639-3
    name: Optional[str] = None

class RatingsSummary(BaseModel):
    """Ratings summary model"""
    aggregate_rating: Optional[float] = Field(None, alias='aggregateRating')
    vote_count: Optional[int] = Field(None, alias='voteCount')

class ImdbApiTitle(BaseModel):
    """Title model for IMDb API"""
    id: str
    type: ImdbType
    is_adult: Optional[bool] = Field(None, alias='isAdult')
    primary_title: Optional[str] = Field(None, alias='primaryTitle')
    original_title: Optional[str] = Field(None, alias='originalTitle')
    primary_image: Optional[ImdbApiImage] = Field(None, alias='primaryImage')
    start_year: Optional[int] = Field(None, alias='startYear')
    end_year: Optional[int] = Field(None, alias='endYear')
    runtime_seconds: Optional[int] = Field(None, alias='runtimeSeconds')
    genres: Optional[List[str]] = None
    rating: Optional[RatingsSummary] = None
    plot: Optional[str] = None
    origin_countries: Optional[List[ImdbApiCountry]] = Field(default_factory=list, alias='originCountries')
    spoken_languages: Optional[List[ImdbApiLanguage]] = Field(default_factory=list, alias='spokenLanguages')

class ImdbApiSearchTitlesResponse(BaseModel):
    """Search response model"""
    titles: List[ImdbApiTitle]

class ImdbApiAka(BaseModel):
    """Alternative title (AKA) model"""
    text: Optional[str] = ''
    attributes: List[str] = Field(default_factory=list)

class ImdbApiListTitleAKAsResponse(BaseModel):
    """AKAs response model"""
    akas: List[ImdbApiAka]


class ImdbApiClient:
    """Client for IMDb API (api.imdbapi.dev)"""
    BASE_URL = 'https://api.imdbapi.dev'

    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url
        self.logger = logging.getLogger(self.__class__.__name__)

    async def _make_request(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make a request to the IMDb API"""
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                proxy=self.proxy_url,
                follow_redirects=True
            ) as client:
                response = await client.get(f"{self.BASE_URL}{path}", params=params)
                if response.status_code != 200:
                    self.logger.warning(f"IMDb API request failed: {path}, status: {response.status_code}")
                    return None
                return response.json()
        except Exception as e:
            self.logger.error(f"IMDb API request error: {e}")
            return None

    async def search_titles(self, query: str, limit: Optional[int] = None) -> Optional[ImdbApiSearchTitlesResponse]:
        """Search for titles using a query string"""
        path = '/search/titles'
        params: Dict[str, Any] = {'query': query}
        if limit:
            params['limit'] = limit

        try:
            data = await self._make_request(path, params)
            if data is None:
                return None
            return ImdbApiSearchTitlesResponse.model_validate(data)
        except Exception as e:
            self.logger.debug(f"Error searching titles: {e}")
            return None

    async def get_title(self, title_id: str) -> Optional[ImdbApiTitle]:
        """Retrieve a title's details using its IMDb ID"""
        path = f'/titles/{title_id}'
        try:
            data = await self._make_request(path)
            if data is None:
                return None
            return ImdbApiTitle.model_validate(data)
        except Exception as e:
            self.logger.debug(f"Error getting title details: {e}")
            return None

    async def get_akas(self, title_id: str) -> Optional[ImdbApiListTitleAKAsResponse]:
        """Retrieve alternative titles (AKAs) for a title"""
        path = f'/titles/{title_id}/akas'
        try:
            data = await self._make_request(path)
            if data is None:
                return None
            return ImdbApiListTitleAKAsResponse.model_validate(data)
        except Exception as e:
            self.logger.debug(f"Error getting AKAs: {e}")
            return None


class ImdbMetadataSource(BaseMetadataSource):
    provider_name = "imdb"
    test_url = "https://api.imdbapi.dev"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_client: Optional[ImdbApiClient] = None

    async def _get_api_client(self) -> ImdbApiClient:
        """Get or create the IMDb API client"""
        if self._api_client is None:
            proxy_url = await self.config_manager.get("proxyUrl", "")
            proxy_enabled_globally = (await self.config_manager.get("proxyEnabled", "false")).lower() == 'true'

            async with self._session_factory() as session:
                metadata_settings = await crud.get_all_metadata_source_settings(session)

            provider_setting = next((s for s in metadata_settings if s['providerName'] == self.provider_name), None)
            use_proxy_for_this_provider = provider_setting.get('useProxy', False) if provider_setting else False

            proxy_to_use = proxy_url if proxy_enabled_globally and use_proxy_for_this_provider and proxy_url else None
            self._api_client = ImdbApiClient(proxy_url=proxy_to_use)

        return self._api_client

    def _map_imdb_type_to_media_type(self, imdb_type: ImdbType) -> Optional[str]:
        """Map IMDb type to our media type"""
        type_mapping = {
            ImdbType.MOVIE: "movie",
            ImdbType.TV_MOVIE: "movie",
            ImdbType.TV_SERIES: "tv",
            ImdbType.TV_MINI_SERIES: "tv",
            ImdbType.TV_SPECIAL: "tv",
        }
        return type_mapping.get(imdb_type)

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        """Search for titles using the new IMDb API"""
        self.logger.info(f"IMDb: 正在使用新API搜索 '{keyword}'")
        formatted_keyword = keyword.strip()
        if not formatted_keyword:
            return []

        try:
            client = await self._get_api_client()
            response = await client.search_titles(formatted_keyword, limit=20)

            if not response or not response.titles:
                return []

            results = []
            for title in response.titles:
                # Filter by media type if specified
                if mediaType:
                    title_media_type = self._map_imdb_type_to_media_type(title.type)
                    if title_media_type != mediaType:
                        continue

                # Build details string
                details_parts = []
                if title.start_year:
                    details_parts.append(f"年份: {title.start_year}")
                if title.genres:
                    details_parts.append(f"类型: {', '.join(title.genres[:3])}")
                if title.rating and title.rating.aggregate_rating:
                    details_parts.append(f"评分: {title.rating.aggregate_rating:.1f}")

                results.append(models.MetadataDetailsResponse(
                    id=title.id,
                    imdbId=title.id,
                    title=title.primary_title or title.original_title or "",
                    type=self._map_imdb_type_to_media_type(title.type),
                    year=title.start_year,
                    details=" / ".join(details_parts),
                    imageUrl=title.primary_image.url if title.primary_image else None
                ))

            return results

        except Exception as e:
            self.logger.error(f"IMDb API 搜索失败: {e}")
            raise HTTPException(status_code=500, detail=f"IMDb API 搜索失败: {str(e)}")

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        """Get detailed information for a title using the new IMDb API"""
        self.logger.info(f"IMDb: 正在获取详情 item_id={item_id}")

        try:
            client = await self._get_api_client()

            # Get title details
            title = await client.get_title(item_id)
            if not title:
                self.logger.error(f"IMDb: 无法获取标题详情 (item_id={item_id})")
                return None

            # Get alternative titles (AKAs)
            aliases_cn: List[str] = []
            akas_response = await client.get_akas(item_id)
            if akas_response and akas_response.akas:
                for aka in akas_response.akas:
                    if aka.text:
                        aliases_cn.append(aka.text)

            # Add original title if different from primary title
            if title.original_title and title.primary_title and title.original_title != title.primary_title:
                aliases_cn.append(title.original_title)

            # Remove duplicates while preserving order
            aliases_cn = list(dict.fromkeys(filter(None, aliases_cn)))

            return models.MetadataDetailsResponse(
                id=item_id,
                imdbId=item_id,
                title=title.primary_title or title.original_title or "",
                nameEn=title.primary_title or title.original_title,
                type=self._map_imdb_type_to_media_type(title.type),
                year=title.start_year,
                aliasesCn=aliases_cn,
                imageUrl=title.primary_image.url if title.primary_image else None
            )

        except Exception as e:
            self.logger.error(f"获取 IMDb 详情时发生错误: {e}")
            return None

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        self.logger.info(f"IMDb: 正在为 '{keyword}' 搜索别名")
        local_aliases: Set[str] = set()
        try:
            search_results = await self.search(keyword, user)
            if not search_results:
                return local_aliases

            best_match_id = search_results[0].id
            details = await self.get_details(best_match_id, user)

            if details:
                if details.nameEn:
                    local_aliases.add(details.nameEn)
                if details.aliasesCn:
                    local_aliases.update(details.aliasesCn)

            self.logger.info(f"IMDb辅助搜索成功，找到别名: {[a for a in local_aliases if a]}")
        except Exception as e:
            self.logger.warning(f"IMDb辅助搜索失败: {e}")

        return {alias for alias in local_aliases if alias}

    async def check_connectivity(self) -> str:
        """检查IMDb源配置状态"""
        # IMDb源不需要特殊配置，只要能正常运行即可
        return "配置正常 (无需特殊配置)"

    async def execute_action(self, action_name: str, payload: Dict[str, Any], user: models.User, request: Request) -> Any:
        """IMDb source does not support custom actions."""
        raise NotImplementedError(f"源 '{self.provider_name}' 不支持任何自定义操作。")