import logging
import re
from typing import Any, Dict, List, Optional, Set

import httpx
from bs4 import BeautifulSoup

from .. import models
from .base import BaseMetadataSource

logger = logging.getLogger(__name__)

class ImdbMetadataSource(BaseMetadataSource):
    provider_name = "imdb"

    async def _create_client(self) -> httpx.AsyncClient:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
        }
        return httpx.AsyncClient(base_url="https://www.imdb.com", headers=headers, timeout=20.0)

    async def search(self, keyword: str, user: models.User, mediaType: Optional[str] = None) -> List[models.MetadataDetailsResponse]:
        async with await self._create_client() as client:
            response = await client.get("/find", params={"q": keyword, "s": "tt"})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            
            results = []
            result_table = soup.find("table", class_="findList")
            if not result_table: return []

            for row in result_table.find_all("tr"):
                result_text = row.find("td", class_="result_text")
                if not result_text: continue
                
                link = result_text.find("a")
                if not link or not link.get("href"): continue
                
                id_match = re.search(r"/title/(tt\d+)/", link["href"])
                if not id_match: continue
                
                title = link.text.strip()
                year_match = re.search(r"\((\d{4})\)", result_text.text)
                year = year_match.group(1) if year_match else ""
                
                img_td = row.find("td", class_="primary_photo")
                img_url = img_td.find("img")["src"] if img_td and img_td.find("img") else None

                results.append(models.MetadataDetailsResponse(
                    id=id_match.group(1),
                    imdbId=id_match.group(1),
                    title=title,
                    imageUrl=img_url,
                    details=f"Year: {year}"
                ))
            return results

    async def get_details(self, item_id: str, user: models.User, mediaType: Optional[str] = None) -> Optional[models.MetadataDetailsResponse]:
        async with await self._create_client() as client:
            response = await client.get(f"/title/{item_id}/")
            if response.status_code == 404: return None
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "lxml")
            
            title_tag = soup.find("h1")
            title = title_tag.text.strip() if title_tag else "未知标题"
            
            return models.MetadataDetailsResponse(
                id=item_id,
                imdbId=item_id,
                title=title,
                details=soup.find("span", {"data-testid": "plot-l"}).text.strip() if soup.find("span", {"data-testid": "plot-l"}) else None
            )

    async def search_aliases(self, keyword: str, user: models.User) -> Set[str]:
        return set() # IMDb is not a good source for aliases

    async def check_connectivity(self) -> str:
        try:
            async with await self._create_client() as client:
                response = await client.get("/")
                return "连接成功" if response.status_code == 200 else f"连接失败 (状态码: {response.status_code})"
        except Exception as e:
            return f"连接失败: {e}"

    async def execute_action(self, action_name: str, payload: Dict[str, Any], user: models.User) -> Any:
        return await super().execute_action(action_name, payload, user)