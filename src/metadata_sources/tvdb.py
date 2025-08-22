import logging
from typing import Any, Dict, List, Optional, Set

import httpx

from .. import models
from .base import BaseMetadataSource

logger = logging.getLogger(__name__)

class TvdbMetadataSource(BaseMetadataSource):
    provider_name = "tvdb"

    async def _create_client(self) -> httpx.AsyncClient:
        api_key = await self.config_manager.get("tvdbApiKey")
        if not api_key:
            raise ValueError("TVDB API Key not configured.")
        
        headers = {"Authorization": f"Bearer {api_key}"}
        return httpx.AsyncClient(base_url="https://api4.thetvdb.com/v4", headers=headers, timeout=20.0)

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        async with await self._create_client() as client:
            response = await client.get("/search", params={"query": keyword})
            response.raise_for_status()
            data = response.json().get("data", [])
            
            results = []
            for item in data:
                results.append(models.MetadataDetailsResponse(
                    id=item['tvdb_id'],
                    tvdbId=item['tvdb_id'],
                    title=item.get('name'),
                    imageUrl=item.get('image_url'),
                    details=f"Year: {item.get('year')}"
                ))
            return results

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        async with await self._create_client() as client:
            response = await client.get(f"/series/{item_id}/extended")
            if response.status_code == 404: return None
            response.raise_for_status()
            
            details = response.json().get("data", {})
            
            return models.MetadataDetailsResponse(
                id=str(details['id']),
                tvdbId=str(details['id']),
                title=details.get('name'),
                imageUrl=details.get('image'),
                details=details.get('overview'),
                imdbId=details.get('remoteIds', [{}])[0].get('id') if details.get('remoteIds') else None
            )

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        return set() # TVDB is not a good source for aliases

    async def check_connectivity(self) -> str:
        try:
            async with await self._create_client() as client:
                response = await client.get("/search", params={"query": "test"})
                return "连接成功" if response.status_code == 200 else f"连接失败 (状态码: {response.status_code})"
        except ValueError as e:
            return f"未配置: {e}"
        except Exception as e:
            return f"连接失败: {e}"

    async def execute_action(self, action_name: str, payload: Dict[str, Any], user: models.User) -> Any:
        return await super().execute_action(action_name, payload, user)