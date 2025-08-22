import logging
from typing import Any, Dict, List, Optional, Set

import httpx
from fastapi import HTTPException, status

from .. import crud, models
from .base import BaseMetadataSource, HTTPStatusError

logger = logging.getLogger(__name__)

class TvdbMetadataSource(BaseMetadataSource):
    provider_name = "tvdb"

    async def _create_client(self) -> httpx.AsyncClient:
        api_key = await self.config_manager.get("tvdbApiKey", "")
        if not api_key:
            raise ValueError("TVDB API Key not configured.")
        
        headers = {"Authorization": f"Bearer {api_key}"}
        
        proxy_url = await self.config_manager.get("proxy_url", "")
        proxy_enabled_globally = (await self.config_manager.get("proxy_enabled", "false")).lower() == 'true'

        async with self._session_factory() as session:
            metadata_settings = await crud.get_all_metadata_source_settings(session)

        provider_setting = next((s for s in metadata_settings if s['providerName'] == self.provider_name), None)
        use_proxy_for_this_provider = provider_setting.get('use_proxy', False) if provider_setting else False

        proxy_to_use = proxy_url if proxy_enabled_globally and use_proxy_for_this_provider and proxy_url else None

        return httpx.AsyncClient(base_url="https://api4.thetvdb.com/v4", headers=headers, timeout=20.0, follow_redirects=True, proxy=proxy_to_use)

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        try:
            async with await self._create_client() as client:
                response = await client.get("/search", params={"query": keyword})
                response.raise_for_status()
                data = response.json().get("data", [])
                
                results = []
                for item in data:
                    if item.get("type") != "series":
                        continue
                    
                    results.append(models.MetadataDetailsResponse(
                        id=item['tvdb_id'], tvdbId=item['tvdb_id'],
                        title=item.get('name'), imageUrl=item.get('image_url'),
                        details=f"Year: {item.get('year')}"
                    ))
                return results
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(e))
        except HTTPStatusError as e:
            detail = f"TVDB服务返回错误: {e.response.status_code}"
            if e.response.status_code == 401:
                detail += "，请检查您的API Key是否正确。"
            self.logger.error(f"TVDB搜索失败，HTTP错误: {e.response.status_code} for URL: {e.request.url}")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
        except Exception as e:
            self.logger.error(f"TVDB搜索失败，发生意外错误: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="TVDB搜索时发生内部错误。")

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        try:
            async with await self._create_client() as client:
                response = await client.get(f"/series/{item_id}/extended")
                if response.status_code == 404: return None
                response.raise_for_status()
                
                details = response.json().get("data", {})
                imdb_id = None
                if remote_ids := details.get('remoteIds'):
                    imdb_entry = next((rid for rid in remote_ids if rid.get('sourceName') == 'IMDB'), None)
                    if imdb_entry: imdb_id = imdb_entry.get('id')

                return models.MetadataDetailsResponse(
                    id=str(details['id']), tvdbId=str(details['id']), title=details.get('name'),
                    imageUrl=details.get('image'), details=details.get('overview'), imdbId=imdb_id
                )
        except Exception as e:
            self.logger.error(f"TVDB获取详情失败: {e}", exc_info=True)
            return None

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        return set()

    async def check_connectivity(self) -> str:
        try:
            async with await self._create_client() as client:
                response = await client.get("/search", params={"query": "test"})
                if response.status_code == 200: return "连接成功"
                elif response.status_code == 401: return "连接失败 (API Key无效)"
                else: return f"连接失败 (状态码: {response.status_code})"
        except ValueError as e: return f"未配置: {e}"
        except Exception as e: return f"连接失败: {e}"
    async def execute_action(self, action_name: str, payload: Dict, user: models.User) -> Any:
        """TVDB source does not support custom actions."""
        raise NotImplementedError(f"源 '{self.provider_name}' 不支持任何自定义操作。")
