import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from .. import crud, models
from ..config import settings
from .base import BaseMetadataSource

logger = logging.getLogger(__name__)

def _clean_movie_title(title: Optional[str]) -> Optional[str]:
    if not title: return None
    phrases_to_remove = ["劇場版", "the movie"]
    cleaned_title = title
    for phrase in phrases_to_remove:
        cleaned_title = re.sub(r'\s*' + re.escape(phrase) + r'\s*:?', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'\s{2,}', ' ', cleaned_title).strip().strip(':- ')
    return cleaned_title

class InfoboxItem(BaseModel):
    key: str
    value: Any

class BangumiSearchSubject(BaseModel):
    id: int
    name: str
    name_cn: str
    images: Optional[Dict[str, str]] = None
    date: Optional[str] = None
    infobox: Optional[List[InfoboxItem]] = None

    @model_validator(mode='after')
    def clean_titles(self) -> 'BangumiSearchSubject':
        self.name = _clean_movie_title(self.name)
        self.name_cn = _clean_movie_title(self.name_cn)
        return self

    @property
    def display_name(self) -> str:
        return self.name_cn or self.name

    @property
    def image_url(self) -> Optional[str]:
        if self.images:
            for size in ["large", "common", "medium", "small", "grid"]:
                if url := self.images.get(size):
                    return url
        return None

    @property
    def aliases(self) -> Dict[str, Any]:
        data = {"name_en": None, "name_romaji": None, "aliases_cn": []}
        if not self.infobox: return data

        def extract_value(value: Any) -> List[str]:
            if isinstance(value, str): return [v.strip() for v in value.split('/') if v.strip()]
            elif isinstance(value, list): return [v.get("v", "").strip() for v in value if isinstance(v, dict) and v.get("v")]
            return []

        all_raw_aliases = []
        for item in self.infobox:
            key, value = item.key.strip(), item.value
            if key == "英文名" and isinstance(value, str): data["name_en"] = _clean_movie_title(value.strip())
            elif key == "罗马字" and isinstance(value, str): data["name_romaji"] = _clean_movie_title(value.strip())
            elif key == "别名": all_raw_aliases.extend(extract_value(value))

        chinese_char_pattern = re.compile(r'[\u4e00-\u9fa5]')
        cleaned_aliases = [_clean_movie_title(alias) for alias in all_raw_aliases]
        data["aliases_cn"] = [alias for alias in cleaned_aliases if alias and chinese_char_pattern.search(alias)]
        data["aliases_cn"] = list(dict.fromkeys(data["aliases_cn"]))
        return data

    @property
    def details_string(self) -> str:
        parts = []
        if self.date:
            try: parts.append(datetime.fromisoformat(self.date).strftime('%Y年%m月%d日'))
            except (ValueError, TypeError): parts.append(self.date)

        if self.infobox:
            staff_keys = ["导演", "原作", "脚本", "人物设定", "系列构成", "总作画监督"]
            staff_found = {}
            for item in self.infobox:
                if item.key in staff_keys:
                    value_str = ""
                    if isinstance(item.value, str): value_str = item.value.strip()
                    elif isinstance(item.value, list): value_str = "、".join([v.get("v", "").strip() for v in item.value if isinstance(v, dict) and v.get("v")])
                    if value_str: staff_found[item.key] = value_str
            for key in staff_keys:
                if key in staff_found and len(parts) < 5: parts.append(staff_found[key])
        return " / ".join(parts)

class BangumiSearchResponse(BaseModel):
    data: Optional[List[BangumiSearchSubject]] = None

class BangumiMetadataSource(BaseMetadataSource):
    provider_name = "bangumi"

    async def _create_client(self, user: models.User) -> httpx.AsyncClient:
        async with self._session_factory() as session:
            auth_info = await crud.get_bangumi_auth(session, user.id)
        
        headers = {"User-Agent": f"DanmuApiServer/1.0 ({settings.jwt.secret_key[:8]})"}
        if auth_info and auth_info.get("isAuthenticated") and auth_info.get("accessToken"):
            headers["Authorization"] = f"Bearer {auth_info['accessToken']}"
        
        return httpx.AsyncClient(base_url="https://api.bgm.tv", headers=headers, timeout=20.0)

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        async with await self._create_client(user) as client:
            search_payload = {"keyword": keyword, "filter": {"type": [2]}}
            search_response = await client.post("/v0/search/subjects", json=search_payload)
            if search_response.status_code == 404: return []
            search_response.raise_for_status()
            
            search_result = BangumiSearchResponse.model_validate(search_response.json())
            if not search_result.data: return []

            tasks = [self.get_details(str(subject.id), user) for subject in search_result.data]
            detailed_results = await asyncio.gather(*tasks)
            return [res for res in detailed_results if res]

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        async with await self._create_client(user) as client:
            details_url = f"/v0/subjects/{item_id}"
            details_response = await client.get(details_url)
            if details_response.status_code == 404: return None
            details_response.raise_for_status()

            subject_data = details_response.json()
            subject = BangumiSearchSubject.model_validate(subject_data)
            aliases = subject.aliases

            return models.MetadataDetailsResponse(
                id=str(subject.id), bangumiId=str(subject.id), title=subject.display_name,
                nameJp=subject.name, imageUrl=subject.image_url, details=subject.details_string,
                nameEn=aliases.get("name_en"), nameRomaji=aliases.get("name_romaji"),
                aliasesCn=aliases.get("aliases_cn", [])
            )

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        local_aliases: Set[str] = set()
        try:
            async with await self._create_client(user) as client:
                search_payload = {"keyword": keyword, "filter": {"type": [2]}}
                search_response = await client.post("/v0/search/subjects", json=search_payload)
                if search_response.status_code != 200: return set()

                search_result = BangumiSearchResponse.model_validate(search_response.json())
                if not search_result.data: return set()

                best_match = search_result.data[0]
                details_response = await client.get(f"/v0/subjects/{best_match.id}")
                if details_response.status_code != 200: return set()

                details = details_response.json()
                local_aliases.add(details.get('name'))
                local_aliases.add(details.get('name_cn'))
                for item in details.get('infobox', []):
                    if item.get('key') == '别名':
                        if isinstance(item['value'], str): local_aliases.add(item['value'])
                        elif isinstance(item['value'], list):
                            for v_item in item['value']:
                                if isinstance(v_item, dict) and v_item.get('v'): local_aliases.add(v_item['v'])
                self.logger.info(f"Bangumi辅助搜索成功，找到别名: {[a for a in local_aliases if a]}")
        except Exception as e:
            self.logger.warning(f"Bangumi辅助搜索失败: {e}")
        return {alias for alias in local_aliases if alias}

    async def check_connectivity(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get("https://api.bgm.tv/v0/ping")
                return "连接成功" if response.status_code == 204 else f"连接失败 (状态码: {response.status_code})"
        except Exception as e:
            return f"连接失败: {e}"

    async def execute_action(self, action_name: str, payload: Dict[str, Any], user: models.User) -> Any:
        if action_name == "get_auth_state":
            async with self._session_factory() as session:
                auth_info = await crud.get_bangumi_auth(session, user.id)
                return models.BangumiAuthStatus(**auth_info)
        elif action_name == "get_auth_url":
            async with self._session_factory() as session:
                client_id = await self.config_manager.get("bangumiClientId")
                if not client_id: raise ValueError("Bangumi App ID is not configured.")
                state = await crud.create_oauth_state(session, user.id)
                return {"url": f"https://bgm.tv/oauth/authorize?client_id={client_id}&response_type=code&state={state}"}
        elif action_name == "logout":
            async with self._session_factory() as session:
                await crud.delete_bangumi_auth(session, user.id)
            return {"message": "注销成功"}
        elif action_name == "handle_auth_callback":
            return await self._handle_auth_callback(payload, user)
        else:
            return await super().execute_action(action_name, payload, user)

    async def _handle_auth_callback(self, payload: Dict[str, Any], user: models.User) -> str:
        code = payload.get("code")
        state = payload.get("state")
        if not code or not state: raise ValueError("缺少 code 或 state 参数")

        async with self._session_factory() as session:
            user_id = await crud.consume_oauth_state(session, state)
            if user_id != user.id: raise ValueError("无效的 state 参数")

            client_id = await self.config_manager.get("bangumiClientId")
            client_secret = await self.config_manager.get("bangumiClientSecret")
            if not client_id or not client_secret: raise ValueError("服务器未配置Bangumi App ID或App Secret。")

            token_data = {
                "grant_type": "authorization_code", "client_id": client_id,
                "client_secret": client_secret, "code": code,
                "redirect_uri": payload.get("redirect_uri")
            }
            
            class BangumiTokenResponse(BaseModel):
                access_token: str
                refresh_token: str
                expires_in: int
                user_id: int

            class BangumiUser(BaseModel):
                id: int
                username: str
                nickname: str
                avatar: Dict[str, str]

            async with httpx.AsyncClient() as client:
                response = await client.post("https://bgm.tv/oauth/access_token", data=token_data)
                response.raise_for_status()
                token_info = BangumiTokenResponse.model_validate(response.json())

                user_resp = await client.get("/v0/me", headers={"Authorization": f"Bearer {token_info.access_token}"})
                user_resp.raise_for_status()
                bgm_user = BangumiUser.model_validate(user_resp.json())

                auth_to_save = {
                    "bangumiUserId": bgm_user.id, "nickname": bgm_user.nickname,
                    "avatarUrl": bgm_user.avatar.get("large"), "accessToken": token_info.access_token,
                    "refreshToken": token_info.refresh_token,
                    "expiresAt": datetime.now() + timedelta(seconds=token_info.expires_in)
                }
                await crud.save_bangumi_auth(session, user.id, auth_to_save)
        
        return "认证成功！"