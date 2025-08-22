import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import httpx
from fastapi import HTTPException, status

from .. import crud, models
from .base import BaseMetadataSource, HTTPStatusError

logger = logging.getLogger(__name__)

class TvdbMetadataSource(BaseMetadataSource):
    provider_name = "tvdb"

    async def _get_tvdb_token(self, client: httpx.AsyncClient) -> str:
        """获取一个有效的TVDB令牌，如果需要则从数据库或API刷新。"""
        # 1. 尝试从数据库配置中获取缓存的token和过期时间
        token = await self.config_manager.get("tvdbJwtToken")
        expires_at_str = await self.config_manager.get("tvdbTokenExpiresAt")

        if token and expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at > datetime.utcnow():
                    self.logger.debug("TVDB: 使用数据库中缓存的有效token。")
                    return token
            except ValueError:
                self.logger.warning("TVDB: 数据库中的过期时间格式无效，将重新获取token。")

        self.logger.info("TVDB token 已过期或未找到，正在请求新的令牌。")
        api_key = await self.config_manager.get("tvdbApiKey", "")
        if not api_key:
            raise ValueError("TVDB API Key 未配置。")

        try:
            # 登录端点不需要认证头
            login_response = await client.post("/login", json={"apikey": api_key})
            login_response.raise_for_status()
            new_token = login_response.json().get("data", {}).get("token")
            if not new_token:
                raise ValueError("登录响应中未包含令牌。")

            # 令牌有效期为一个月，我们设置一个29天的缓存
            new_expires_at = datetime.utcnow() + timedelta(days=29)
            await self.config_manager.setValue("tvdbJwtToken", new_token)
            await self.config_manager.setValue("tvdbTokenExpiresAt", new_expires_at.isoformat())
            
            self.logger.info("成功获取并缓存新的TVDB令牌。")
            return new_token
        except Exception as e:
            self.logger.error(f"获取TVDB令牌失败: {e}", exc_info=True)
            raise ValueError("TVDB认证失败。")

    async def _create_client(self) -> httpx.AsyncClient:
        # 1. 获取代理配置
        proxy_url = await self.config_manager.get("proxy_url", "")
        proxy_enabled_globally = (await self.config_manager.get("proxy_enabled", "false")).lower() == 'true'

        async with self._session_factory() as session:
            metadata_settings = await crud.get_all_metadata_source_settings(session)
        provider_setting = next((s for s in metadata_settings if s['providerName'] == self.provider_name), None)
        use_proxy_for_this_provider = provider_setting.get('use_proxy', False) if provider_setting else False
        proxy_to_use = proxy_url if proxy_enabled_globally and use_proxy_for_this_provider and proxy_url else None

        # 2. 创建一个基础客户端用于登录
        base_client = httpx.AsyncClient(base_url="https://api4.thetvdb.com/v4", timeout=20.0, follow_redirects=True, proxy=proxy_to_use)

        # 3. 使用基础客户端获取认证Token
        token = await self._get_tvdb_token(base_client)

        # 4. 将认证Token更新到客户端的请求头中
        base_client.headers.update({
            "Authorization": f"Bearer {token}",
            "User-Agent": "DanmuApiServer/1.0"
        })
        return base_client

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        try:
            async with await self._create_client() as client:
                # 修正：根据 mediaType 决定搜索类型
                params = {"query": keyword}
                if mediaType:
                    params["type"] = mediaType

                response = await client.get("/search", params=params)
                response.raise_for_status()
                data = response.json().get("data", [])
                
                results = []
                for item in data:
                    results.append(models.MetadataDetailsResponse(
                        id=item['tvdb_id'], tvdbId=item['tvdb_id'],
                        title=item.get('name'), imageUrl=item.get('image_url'),
                        details=f"Year: {item.get('year')}",
                        type="tv_series" if item.get("type") == "series" else item.get("type", "other")
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
                # 修正：根据 mediaType 决定请求的端点
                endpoint_type = "series" if mediaType == "series" else "movies"
                response = await client.get(f"/{endpoint_type}/{item_id}/extended")
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
