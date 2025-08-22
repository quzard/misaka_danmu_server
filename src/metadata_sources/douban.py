import logging
import re
from typing import Any, Dict, List, Optional, Set

import httpx
from bs4 import BeautifulSoup

from .. import models
from .base import BaseMetadataSource

logger = logging.getLogger(__name__)

class DoubanMetadataSource(BaseMetadataSource):
    provider_name = "douban"

    async def _create_client(self) -> httpx.AsyncClient:
        cookie = await self.config_manager.get("doubanCookie", "")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cookie
        }
        return httpx.AsyncClient(base_url="https://movie.douban.com", headers=headers, timeout=20.0)

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        async with await self._create_client() as client:
            response = await client.get("/j/search_subjects", params={"q": keyword, "cat": "1002"})
            response.raise_for_status()
            data = response.json().get("subjects", [])
            
            results = []
            for item in data:
                results.append(models.MetadataDetailsResponse(
                    id=item['id'],
                    doubanId=item['id'],
                    title=item['title'],
                    imageUrl=item.get('cover'),
                    details=f"{item.get('type', '')} / {item.get('release_year', '')}"
                ))
            return results

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        async with await self._create_client() as client:
            response = await client.get(f"/subject/{item_id}/")
            if response.status_code == 404: return None
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "lxml")
            info_div = soup.find("div", id="info")
            if not info_div: return None

            info_text = info_div.get_text(" ", strip=True)
            
            def get_info(label: str):
                match = re.search(rf"{label}:\s*(.*?)\s*(?=\w+:|$)", info_text)
                return match.group(1).strip() if match else None

            title_tag = soup.find("span", property="v:itemreviewed")
            title = title_tag.text if title_tag else "未知标题"
            
            aliases_cn = [alias.strip() for alias in (get_info("又名") or "").split('/') if alias.strip()]
            
            imdb_tag = info_div.find("a", href=lambda x: x and "imdb.com" in x)
            
            return models.MetadataDetailsResponse(
                id=item_id,
                doubanId=item_id,
                title=title,
                nameEn=get_info("官方网站"), # Douban doesn't have a clear EN name field
                aliasesCn=aliases_cn,
                imageUrl=soup.find("img", rel="v:image")['src'] if soup.find("img", rel="v:image") else None,
                details=soup.find("span", property="v:summary").get_text(strip=True) if soup.find("span", property="v:summary") else None,
                imdbId=imdb_tag.text if imdb_tag else None
            )

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        aliases: Set[str] = set()
        try:
            results = await self.search(keyword, user)
            if not results: return set()
            
            best_match = results[0]
            details = await self.get_details(best_match.id, user)
            if details:
                aliases.add(details.title)
                if details.nameEn: aliases.add(details.nameEn)
                aliases.update(details.aliasesCn)
        except Exception as e:
            self.logger.warning(f"Douban辅助搜索失败: {e}")
        return {alias for alias in aliases if alias}

    async def check_connectivity(self) -> str:
        try:
            async with await self._create_client() as client:
                response = await client.get("/")
                return "连接成功" if response.status_code == 200 else f"连接失败 (状态码: {response.status_code})"
        except Exception as e:
            return f"连接失败: {e}"

    async def execute_action(self, action_name: str, payload: Dict[str, Any], user: models.User) -> Any:
        return await super().execute_action(action_name, payload, user)
