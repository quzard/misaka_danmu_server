import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .. import models, security

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Constants and Helpers from the script ---

COOKIES = {
    '__guid': '26972607.2949894437869698600.1752640253092.913',
    'refer_scene': '47007',
    '__huid': '11da4Vxk54oFVy89kXmOuuvPhPxzN45efwa8EHQR4I8Tg%3D',
    '___sid': '26972607.3930629777557762600.1752655408731.65',
    '__DC_gid': '26972607.192430250.1752640253137.1752656674152.17',
    'monitor_count': '12',
}

def get_headers(encoded_keyword: str) -> Dict[str, str]:
    return {
        'accept': '*/*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'referer': f'https://so.360kan.com/?kw={encoded_keyword}',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    }

SKIP_KEYWORDS = ["花絮", "独家专访", "幕后", "专访", "无障碍", "路演"]

PLATFORM_ORDER = {
    'qq': 1, 'qiyi': 2, 'youku': 3, 'bilibili': 4, 'bilibili1': 4, 'imgo': 5,
}

PLATFORM_NAMES = {
    'qq': '腾讯视频', 'qiyi': '爱奇艺', 'youku': '优酷', 'bilibili': 'B站', 'bilibili1': 'B站', 'imgo': '芒果TV',
}

def convert_hunantv_to_mgtv(url):
    m = re.match(r'^https?://www\.hunantv\.com/v/1/([0-9]+)/f/([0-9]+)\.html', url)
    if m:
        return f'https://www.mgtv.com/b/{m.group(1)}/{m.group(2)}.html'
    return url

# --- Pydantic Models for the new API ---

class So360Episode(BaseModel):
    title: str
    url: str

class So360Platform(BaseModel):
    platform_code: str
    platform_name: str
    url: Optional[str] = None
    episodes: Optional[List[So360Episode]] = None

class So360SearchResult(BaseModel):
    title: str
    year: Optional[str] = None
    cover: Optional[str] = None
    content_type: str
    is_multi_episode: bool
    platforms: List[So360Platform]

# --- Async HTTP Client Dependency ---

async def get_so360_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(cookies=COOKIES, timeout=20.0)

# --- API Implementation ---

async def _get_zongyi_episodes(client: httpx.AsyncClient, ent_id: str, site: str, years: List[str], encoded_keyword: str) -> List[Dict]:
    all_episodes = []
    cb_index = 7
    for year in years:
        offset = 0
        count = 8
        while True:
            cb = f'__jp{cb_index}'
            cb_index += 1
            params = {'site': site, 'y': year, 'entid': ent_id, 'offset': offset, 'count': count, 'v_ap': '1', 'cb': cb}
            try:
                resp = await client.get('https://api.so.360kan.com/episodeszongyi', params=params, headers=get_headers(encoded_keyword))
                data = resp.text
                json_data = json.loads(data[data.index('(') + 1:data.rindex(')')])
                if json_data.get('code') == 0 and json_data.get('data'):
                    episodes = json_data['data'].get('list', []) or []
                    all_episodes.extend(episodes)
                    if len(episodes) < count: break
                    offset += count
                else: break
            except Exception: break
    return all_episodes

async def _get_platform_episodes(client: httpx.AsyncClient, cat_id: str, ent_id: str, site: str, cat_name: Optional[str], year: Optional[str], item: Dict, encoded_keyword: str) -> List[Dict]:
    try:
        if cat_id == '3' or (cat_name and '综艺' in cat_name):
            years = []
            if item and 'playlinks_year' in item and site in item['playlinks_year']:
                years = [str(y) for y in item['playlinks_year'][site] if y]
            if not years and item:
                for key in ['years', 'periods', 'yearlist']:
                    if key in item and isinstance(item[key], list) and item[key]:
                        years = [str(y) for y in item[key] if y]
                        break
            if not years: years = [str(year)] if year else ['']
            return await _get_zongyi_episodes(client, ent_id, site, years, encoded_keyword)
        
        s_param = json.dumps([{"cat_id": cat_id, "ent_id": ent_id, "site": site}])
        params = {'v_ap': '1', 's': s_param, 'cb': '__jp8'}
        resp = await client.get('https://api.so.360kan.com/episodesv2', params=params, headers=get_headers(encoded_keyword))
        data = resp.text
        json_data = json.loads(data[data.index('(') + 1:data.rindex(')')])
        if json_data.get('code') == 0 and len(json_data.get('data', [])) > 0:
            series_html = json_data['data'][0].get('seriesHTML', {})
            if 'seriesPlaylinks' in series_html:
                return series_html['seriesPlaylinks']
        return []
    except Exception as e:
        logger.error(f"获取 {site} 平台分集链接出错: {e}")
        return []

@router.get("/search", response_model=List[So360SearchResult], summary="通过360影视搜索作品")
async def search_so360(
    keyword: str = Query(..., min_length=1),
    client: httpx.AsyncClient = Depends(get_so360_client),
    current_user: models.User = Depends(security.get_current_user)
):
    encoded_keyword = quote(keyword)
    params = {'force_v': '1', 'kw': keyword, 'from': '', 'pageno': '1', 'v_ap': '1', 'tab': 'all', 'cb': '__jp0'}
    
    try:
        response = await client.get('https://api.so.360kan.com/index', params=params, headers=get_headers(encoded_keyword))
        data = response.text
        json_data = json.loads(data[data.index('(') + 1:data.rindex(')')])
        rows = json_data.get('data', {}).get('longData', {}).get('rows', [])
    except Exception as e:
        logger.error(f"360搜索API请求失败: {e}")
        raise HTTPException(status_code=500, detail="360搜索API请求失败")

    final_results = []
    keyword_lower = keyword.lower()

    for item in rows:
        title = item.get('titleTxt', '')
        if any(skip in title for skip in SKIP_KEYWORDS) or keyword_lower not in title.lower():
            continue
        
        cat_id = item.get('cat_id', '')
        cat_name = item.get('cat_name', '')
        is_multi_episode = ('seriesPlaylinks' in item and len(item.get('seriesPlaylinks', [])) > 1) or \
                           (item.get('is_serial') == 1) or \
                           ('集' in item.get('coverInfo', {}).get('txt', '')) or \
                           (cat_id == '3' or (cat_name and '综艺' in cat_name))

        content_type = "电影"
        if cat_id == '2' or (cat_name and '电视' in cat_name): content_type = "电视剧"
        elif cat_id == '4' or (cat_name and '动漫' in cat_name): content_type = "动漫"
        elif cat_id == '3' or (cat_name and '综艺' in cat_name): content_type = "综艺"
        elif is_multi_episode: content_type = "多集内容"

        platforms = []
        available_platforms = sorted(
            [p for p in item.get('playlinks', {}) if p in PLATFORM_ORDER],
            key=lambda x: PLATFORM_ORDER.get(x, 999)
        )

        if not is_multi_episode:
            for source in available_platforms:
                platforms.append(So360Platform(
                    platform_code=source,
                    platform_name=PLATFORM_NAMES.get(source, source),
                    url=item['playlinks'][source]
                ))
        else:
            ent_id = item.get('id', '') if (cat_id == '3' or (cat_name and '综艺' in cat_name)) else item.get('en_id', '')
            for source in available_platforms:
                episodes_data = await _get_platform_episodes(client, cat_id, ent_id, source, cat_name, item.get('year'), item, encoded_keyword)
                
                episodes = []
                if episodes_data:
                    for i, ep_item in enumerate(episodes_data):
                        ep_url = ""
                        ep_title = ""
                        if isinstance(ep_item, dict):
                            period = ep_item.get('period', '')
                            name = ep_item.get('name', '')
                            ep_title = f"{period} {name}".strip() or f"第{i+1}集"
                            ep_url = convert_hunantv_to_mgtv(ep_item.get('url', ''))
                        elif isinstance(ep_item, str):
                            ep_url = ep_item
                            ep_title = f"第{i+1}集"
                        
                        if ep_url:
                            episodes.append(So360Episode(title=ep_title, url=ep_url))

                if episodes:
                    platforms.append(So360Platform(
                        platform_code=source,
                        platform_name=PLATFORM_NAMES.get(source, source),
                        episodes=episodes
                    ))

        if platforms:
            final_results.append(So360SearchResult(
                title=title,
                year=item.get('year'),
                cover=item.get('cover'),
                content_type=content_type,
                is_multi_episode=is_multi_episode,
                platforms=platforms
            ))

    return final_results
