import asyncio
import logging
import json
import re
import time
import ipaddress
from typing import List, Optional, Dict, Any, Tuple
from typing import Callable
from datetime import datetime, timezone
from opencc import OpenCC
from thefuzz import fuzz

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from . import crud, models, orm_models, tasks
from .config_manager import ConfigManager
from .timezone import get_now, get_app_timezone
from .database import get_db_session
from .utils import parse_search_keyword
from .rate_limiter import RateLimiter
from .task_manager import TaskManager
from .metadata_manager import MetadataSourceManager
from .scraper_manager import ScraperManager
from .api.control_api import ControlAutoImportRequest, get_title_recognition_manager

logger = logging.getLogger(__name__)

# --- Module-level Constants for Type Mappings and Parsing ---
# To avoid repetition and improve maintainability.
DANDAN_TYPE_MAPPING = {
    "tv_series": "tvseries", "movie": "movie", "ova": "ova", "other": "other"
}
DANDAN_TYPE_DESC_MAPPING = {
    "tv_series": "TV动画", "movie": "电影/剧场版", "ova": "OVA", "other": "其他"
}

# 后备搜索状态管理
fallback_search_cache = {}  # 存储搜索状态和结果
FALLBACK_SEARCH_BANGUMI_ID = 999999999  # 搜索中的固定bangumiId

# Token级别的搜索任务限制
token_search_tasks = {}  # 格式：{token: search_key}

# 弹幕获取缓存（避免重复获取）
comments_fetch_cache = {}  # 存储已获取的弹幕数据

# 弹幕采样结果缓存（避免重复采样）
# 格式: {f"sampled_{episodeId}_{limit}": (sampled_comments, timestamp)}
sampled_comments_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}
SAMPLED_CACHE_TTL = 86400  # 缓存1天 (24小时)

# 用户最后选择的虚拟bangumiId记录（用于确定使用哪个源）
user_last_bangumi_choice = {}  # 格式：{search_key: last_bangumi_id}

# episodeId到源映射的缓存键前缀
EPISODE_MAPPING_CACHE_PREFIX = "episode_mapping_"

async def _store_episode_mapping(session: AsyncSession, episode_id: int, provider: str, media_id: str, episode_index: int, original_title: str):
    """
    存储episodeId到源的映射关系到数据库缓存
    """
    from . import crud
    import json

    mapping_data = {
        "provider": provider,
        "media_id": media_id,
        "episode_index": episode_index,
        "original_title": original_title,
        "timestamp": time.time()
    }

    cache_key = f"{EPISODE_MAPPING_CACHE_PREFIX}{episode_id}"
    # 使用3小时过期时间（10800秒）
    await crud.set_cache(session, cache_key, json.dumps(mapping_data), ttl_seconds=10800)
    logger.debug(f"存储episodeId映射: {episode_id} -> {provider}:{media_id}")

async def _get_episode_mapping(session: AsyncSession, episode_id: int) -> Optional[Dict[str, Any]]:
    """
    从数据库缓存中获取episodeId的映射关系
    """
    from . import crud
    import json

    cache_key = f"{EPISODE_MAPPING_CACHE_PREFIX}{episode_id}"
    cached_data = await crud.get_cache(session, cache_key)

    if cached_data:
        try:
            # cached_data可能已经是dict类型（从crud.get_cache返回）
            if isinstance(cached_data, str):
                mapping_data = json.loads(cached_data)
            else:
                mapping_data = cached_data
            logger.info(f"从缓存获取episodeId映射: {episode_id} -> {mapping_data['provider']}:{mapping_data['media_id']}")
            return mapping_data
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"解析episodeId映射缓存失败: {e}")
            return None

    return None


def _format_episode_ranges(episodes: List[int]) -> str:
    """
    将分集列表格式化为简洁的范围表示
    例如: [1,2,3,5,6,7,10] -> "1-3,5-7,10"
    """
    if not episodes:
        return ""

    episodes = sorted(set(episodes))  # 去重并排序
    ranges = []
    start = episodes[0]
    end = episodes[0]

    for i in range(1, len(episodes)):
        if episodes[i] == end + 1:
            # 连续的集数
            end = episodes[i]
        else:
            # 不连续，保存当前范围
            if start == end:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{end}")
            start = episodes[i]
            end = episodes[i]

    # 保存最后一个范围
    if start == end:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{end}")

    return ",".join(ranges)
   
async def _find_existing_anime_by_bangumi_id(session: AsyncSession, bangumi_id: str, search_key: str) -> Optional[Dict[str, Any]]:
    """
    根据bangumiId和搜索会话查找已存在的映射记录，返回anime信息
    使用bangumiId确保精确匹配，避免不同搜索结果被错误合并
    """
    # 只在当前搜索会话的结果中查找
    if search_key in fallback_search_cache:
        search_info = fallback_search_cache[search_key]
        if "bangumi_mapping" in search_info:
            if bangumi_id in search_info["bangumi_mapping"]:
                mapping_info = search_info["bangumi_mapping"][bangumi_id]
                if mapping_info.get("real_anime_id"):
                    real_anime_id = mapping_info["real_anime_id"]
                    title = mapping_info.get("original_title", "未知")
                    logger.debug(f"在当前搜索会话中找到已存在的剧集: bangumiId={bangumi_id}, title='{title}' (anime_id={real_anime_id})")
                    return {"animeId": real_anime_id, "title": title}

    logger.debug(f"在当前搜索会话中未找到已存在的剧集: bangumiId={bangumi_id}")
    return None
  
async def _update_episode_mapping(session: AsyncSession, episode_id: int, provider: str, media_id: str, episode_index: int, original_title: str):
    """
    更新episodeId的映射关系（同时更新数据库缓存和内存缓存）
    """
    # 更新数据库缓存
    await _store_episode_mapping(session, episode_id, provider, media_id, episode_index, original_title)

    # 同时更新内存缓存中的映射关系
    # 查找并更新fallback_search_cache中的real_anime_id映射
    real_anime_id = int(str(episode_id)[2:8])  # 从episodeId提取real_anime_id

    for search_key, search_info in fallback_search_cache.items():
        if search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
            for bangumi_id, mapping_info in search_info["bangumi_mapping"].items():
                if mapping_info.get("real_anime_id") == real_anime_id:
                    # 更新映射信息
                    mapping_info["provider"] = provider
                    mapping_info["media_id"] = media_id
                    # 更新用户选择记录
                    user_last_bangumi_choice[search_key] = bangumi_id
                    logger.info(f"更新内存缓存映射: real_anime_id={real_anime_id}, provider={provider}")
                    break

    logger.debug(f"更新episodeId映射: {episode_id} -> {provider}:{media_id}")

async def _check_related_match_fallback_task(session: AsyncSession, search_term: str) -> Optional[Dict[str, Any]]:
    """
    检查是否有相关的后备匹配任务正在进行
    返回任务信息（包含进度）或None
    """
    from . import crud
    from .task_manager import TaskStatus

    # 查找正在进行的匹配后备任务
    # 通过TaskStateCache查找match_fallback类型的任务

    # 查询正在进行的匹配后备任务
    stmt = select(orm_models.TaskStateCache).where(
        orm_models.TaskStateCache.taskType == "match_fallback"
    ).order_by(orm_models.TaskStateCache.createdAt.desc()).limit(10)  # 获取最近10个任务

    result = await session.execute(stmt)
    task_caches = result.scalars().all()

    # 检查任务参数中是否包含相关的搜索词
    for task_cache in task_caches:
        # 获取对应的TaskHistory记录
        history_stmt = select(orm_models.TaskHistory).where(
            orm_models.TaskHistory.taskId == task_cache.taskId,
            orm_models.TaskHistory.status.in_(['排队中', '运行中'])
        )
        history_result = await session.execute(history_stmt)
        task_history = history_result.scalar_one_or_none()

        if task_history:
            # 简单的标题匹配 - 检查任务标题是否包含搜索词
            if search_term.lower() in task_history.title.lower():
                return {
                    "task_id": task_history.taskId,
                    "title": task_history.title,
                    "progress": task_history.progress or 0,
                    "status": task_history.status,
                    "description": task_history.description or "匹配后备正在进行"
                }

            # 也可以检查任务描述
            if task_history.description and search_term.lower() in task_history.description.lower():
                return {
                    "task_id": task_history.taskId,
                    "title": task_history.title,
                    "progress": task_history.progress or 0,
                    "status": task_history.status,
                    "description": task_history.description
                }

    return None

async def _get_next_virtual_anime_id() -> int:
    """
    获取下一个虚拟animeId（6位数字，从900000开始）
    用于后备搜索结果显示
    """
    # 查找当前最大的虚拟animeId
    max_id = None
    for search_key, search_info in fallback_search_cache.items():
        if search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
            for bangumi_id, mapping_info in search_info["bangumi_mapping"].items():
                anime_id = mapping_info.get("anime_id")
                if anime_id and 900000 <= anime_id <= 999999:
                    if max_id is None or anime_id > max_id:
                        max_id = anime_id

    if max_id is None:
        return 900000  # 如果没有找到，从900000开始
    else:
        return max_id + 1

async def _get_next_real_anime_id(session: AsyncSession) -> int:
    """
    获取下一个真实的animeId（当前最大animeId + 1）
    用于实际的episodeId生成
    """
    from . import orm_models

    # 查询当前最大的animeId
    result = await session.execute(
        select(func.max(orm_models.Anime.id))
    )
    max_id = result.scalar()

    if max_id is None:
        return 1  # 如果没有找到，从1开始
    else:
        return max_id + 1

def _generate_episode_id(anime_id: int, source_order: int, episode_number: int) -> int:
    """
    生成episode ID，格式：25 + animeid（6位）+ 源顺序（2位）+ 集编号（4位）
    按照弹幕库标准，animeId补0到6位
    例如：animeId=136 → episodeId=25000136010001
    """
    # 按照弹幕库标准：animeId补0到6位
    # 格式化为：25 + 6位animeId + 2位源顺序 + 4位集编号
    episode_id = int(f"25{anime_id:06d}{source_order:02d}{episode_number:04d}")
    return episode_id

# 后备搜索函数将在模型定义后添加
# 新增：用于清理文件名中常见元数据关键词的正则表达式
METADATA_KEYWORDS_PATTERN = re.compile(
    r'1080p|720p|2160p|4k|bluray|x264|h\s*\.?\s*264|hevc|x265|h\s*\.?\s*265|aac|flac|web-dl|BDRip|WEBRip|TVRip|DVDrip|AVC|CHT|CHS|BIG5|GB|10bit|8bit',
    re.IGNORECASE
)

# 这个子路由将包含所有接口的实际实现。
# 它将被挂载到主路由的不同路径上。
implementation_router = APIRouter()

def _process_comments_for_dandanplay(comments_data: List[Dict[str, Any]]) -> List[models.Comment]:
    """
    将弹幕字典列表处理为符合 dandanplay 客户端规范的格式。
    核心逻辑是移除 p 属性中的字体大小参数，同时保留其他所有部分。
    原始格式: "时间,模式,字体大小,颜色,[来源]"
    目标格式: "时间,模式,颜色,[来源]"
    """
    processed_comments = []
    for i, item in enumerate(comments_data):
        p_attr = item.get("p", "")
        p_parts = p_attr.split(',')

        # 查找可选的用户标签（如[bilibili]），以确定核心参数的数量
        core_parts_count = len(p_parts)
        for j, part in enumerate(p_parts):
            if '[' in part and ']' in part:
                core_parts_count = j
                break
        
        if core_parts_count == 4:
            del p_parts[2] # 移除字体大小 (index 2)
        
        new_p_attr = ','.join(p_parts)
        processed_comments.append(models.Comment(cid=i, p=new_p_attr, m=item.get("m", "")))
    return processed_comments


class DandanApiRoute(APIRoute):
    """
    自定义的 APIRoute 类，用于为 dandanplay 兼容接口定制异常处理。
    捕获 HTTPException，并以 dandanplay API v2 的格式返回错误信息。
    """
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except HTTPException as exc:
                # 简单的 HTTP 状态码到 dandanplay 错误码的映射
                # 1001: 无效的参数
                # 1003: 未授权或资源不可用
                # 404: 未找到
                # 500: 服务器内部错误
                error_code_map = {
                    status.HTTP_400_BAD_REQUEST: 1001,
                    status.HTTP_422_UNPROCESSABLE_ENTITY: 1001,
                    # 新增：将404也映射到1003，对外统一表现为“资源不可用”
                    status.HTTP_404_NOT_FOUND: 1003,
                    status.HTTP_403_FORBIDDEN: 1003,
                    status.HTTP_500_INTERNAL_SERVER_ERROR: 500,
                }
                error_code = error_code_map.get(exc.status_code, 1003) # 默认客户端错误为1003

                # 为常见的错误代码提供更统一的错误消息
                error_message = "请求的资源不可用或您没有权限访问。" if error_code == 1003 else exc.detail

                # 始终返回 200 OK，错误信息在 JSON body 中体现
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "success": False,
                        "errorCode": error_code,
                        "errorMessage": error_message,
                    },
                )
        return custom_route_handler

async def get_config_manager(request: Request) -> ConfigManager:
    """依赖项：从应用状态获取配置管理器"""
    return request.app.state.config_manager

async def get_task_manager(request: Request) -> TaskManager:
    """依赖项：从应用状态获取任务管理器"""
    return request.app.state.task_manager

async def get_metadata_manager(request: Request) -> MetadataSourceManager:
    """依赖项：从应用状态获取元数据源管理器"""
    return request.app.state.metadata_manager

async def get_rate_limiter(request: Request) -> RateLimiter:
    """依赖项：从应用状态获取速率限制器"""
    return request.app.state.rate_limiter

# 这是将包含在 main.py 中的主路由。
# 使用自定义的 Route 类来应用特殊的异常处理。
dandan_router = APIRouter(route_class=DandanApiRoute)

class DandanResponseBase(BaseModel):
    """模仿 dandanplay API v2 的基础响应模型"""
    success: bool = True
    errorCode: int = 0
    errorMessage: str = Field("", description="错误信息")


class DandanEpisodeInfo(BaseModel):
    """dandanplay /search/episodes 接口中的分集信息模型"""
    episodeId: int
    episodeTitle: str

class DandanAnimeInfo(BaseModel):
    """dandanplay /search/episodes 接口中的番剧信息模型"""
    animeId: int
    animeTitle: str
    imageUrl: str = ""
    searchKeyword: str = ""
    type: str
    typeDescription: str
    isOnAir: bool = False
    airDay: int = 0
    isFavorited: bool = False
    rating: float = 0.0
    episodes: List[DandanEpisodeInfo]

class DandanSearchEpisodesResponse(DandanResponseBase):
    hasMore: bool = False
    animes: List[DandanAnimeInfo]

# --- Models for /search/anime ---
class DandanSearchAnimeItem(BaseModel):
    animeId: Optional[int] = None  # 支持后备搜索时animeId为None
    bangumiId: Optional[str] = ""
    animeTitle: str
    type: str
    typeDescription: str
    imageUrl: Optional[str] = None
    startDate: Optional[str] = None # To keep compatibility, but will be populated from year
    year: Optional[int] = None
    episodeCount: int
    rating: float = 0.0
    isFavorited: bool = False

class DandanSearchAnimeResponse(DandanResponseBase):
    animes: List[DandanSearchAnimeItem]


# --- Models for /bangumi/{anime_id} ---

class BangumiTitle(BaseModel):
    language: str
    title: str

class BangumiEpisodeSeason(BaseModel):
    id: str
    airDate: Optional[datetime] = None
    name: str
    episodeCount: int
    summary: str

class BangumiEpisode(BaseModel):
    seasonId: Optional[str] = None
    episodeId: int
    episodeTitle: str
    episodeNumber: str
    lastWatched: Optional[datetime] = None
    airDate: Optional[datetime] = None

class BangumiIntro(BaseModel):
    animeId: int
    bangumiId: Optional[str] = ""
    animeTitle: str
    imageUrl: Optional[str] = None
    searchKeyword: Optional[str] = None
    isOnAir: bool = False
    airDay: int = 0
    isRestricted: bool = False
    rating: float = 0.0

class BangumiTag(BaseModel):
    id: int
    name: str
    count: int

class BangumiOnlineDatabase(BaseModel):
    name: str
    url: str

class BangumiTrailer(BaseModel):
    id: int
    url: str
    title: str
    imageUrl: str
    date: datetime

class BangumiDetails(BangumiIntro):
    type: str
    typeDescription: str
    titles: List[BangumiTitle] = []
    seasons: List[BangumiEpisodeSeason] = []
    episodes: List[BangumiEpisode] = []
    summary: Optional[str] = ""
    metadata: List[str] = []
    year: Optional[int] = None
    userRating: int = 0
    favoriteStatus: Optional[str] = None
    comment: Optional[str] = None
    ratingDetails: Dict[str, float] = {}
    relateds: List[BangumiIntro] = []
    similars: List[BangumiIntro] = []
    tags: List[BangumiTag] = []
    onlineDatabases: List[BangumiOnlineDatabase] = []
    trailers: List[BangumiTrailer] = []

class BangumiDetailsResponse(DandanResponseBase):
    bangumi: Optional[BangumiDetails] = None

# --- Models for /match ---

class DandanMatchInfo(BaseModel):
    episodeId: int
    animeId: int
    animeTitle: str
    episodeTitle: str
    type: str
    typeDescription: str
    shift: int = 0

class DandanMatchResponse(DandanResponseBase):
    isMatched: bool = False
    matches: List[DandanMatchInfo] = []

# --- Models for /match/batch ---

class DandanBatchMatchRequestItem(BaseModel):
    fileName: str
    fileHash: Optional[str] = None
    fileSize: Optional[int] = None
    videoDuration: Optional[int] = None
    matchMode: Optional[str] = "hashAndFileName"

class DandanBatchMatchRequest(BaseModel):
    requests: List[DandanBatchMatchRequestItem]

# --- 后备搜索函数 ---

async def _handle_fallback_search(
    search_term: str,
    token: str,
    session: AsyncSession,
    scraper_manager: ScraperManager,
    metadata_manager: MetadataSourceManager,
    config_manager: ConfigManager,
    rate_limiter: RateLimiter,
    title_recognition_manager
) -> DandanSearchAnimeResponse:
    """
    处理后备搜索逻辑
    """
    import time

    # 生成搜索任务的唯一标识
    search_key = f"search_{hash(search_term + token)}"

    # 检查该token是否已有正在进行的搜索任务
    if token in token_search_tasks:
        existing_search_key = token_search_tasks[token]
        if existing_search_key in fallback_search_cache:
            existing_search = fallback_search_cache[existing_search_key]
            if existing_search["status"] == "running":
                # 返回正在进行的搜索状态
                elapsed_time = time.time() - existing_search["start_time"]
                progress = min(int((elapsed_time / 60) * 100), 95)
                return DandanSearchAnimeResponse(animes=[
                    DandanSearchAnimeItem(
                        animeId=999999999,
                        bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
                        animeTitle=f"{existing_search['search_term']} 搜索正在运行",
                        type="tvseries",
                        typeDescription=f"{progress}%",
                        imageUrl="/static/logo.png",
                        startDate="2025-01-01T00:00:00+08:00",
                        year=2025,
                        episodeCount=1,
                        rating=0.0,
                        isFavorited=False
                    )
                ])

    # 首先检查是否有相关的后备匹配任务正在进行
    match_fallback_task = await _check_related_match_fallback_task(session, search_term)
    if match_fallback_task:
        # 返回后备匹配的进度信息，格式类似后备搜索
        progress = match_fallback_task['progress']
        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999999,
                bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
                animeTitle=f"{search_term} 匹配后备正在运行",
                type="tvseries",
                typeDescription=f"{progress}%",
                imageUrl="/static/logo.png",
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=1,
                rating=0.0,
                isFavorited=False
            )
        ])

    # 检查是否已有正在进行的搜索
    if search_key in fallback_search_cache:
        search_info = fallback_search_cache[search_key]

        # 如果搜索已完成，返回结果
        if search_info["status"] == "completed":
            return DandanSearchAnimeResponse(animes=search_info["results"])

        # 如果搜索失败，返回空结果
        if search_info["status"] == "failed":
            return DandanSearchAnimeResponse(animes=[])

        # 如果搜索正在进行中，返回搜索状态
        if search_info["status"] == "running":
            elapsed_time = time.time() - search_info["start_time"]
            if elapsed_time >= 5:  # 5秒后返回搜索中状态
                progress = min(int((elapsed_time / 60) * 100), 95)  # 假设最多1分钟完成，最高95%
                return DandanSearchAnimeResponse(animes=[
                    DandanSearchAnimeItem(
                        animeId=999999999,  # 使用特定的不会冲突的数字
                        bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
                        animeTitle=f"{search_term} 搜索正在运行",
                        type="tvseries",
                        typeDescription=f"{progress}%",
                        imageUrl="/static/logo.png",
                        startDate="2025-01-01T00:00:00+08:00",
                        year=2025,
                        episodeCount=1,
                        rating=0.0,
                        isFavorited=False
                    )
                ])
            else:
                # 5秒内返回搜索启动状态
                return DandanSearchAnimeResponse(animes=[
                    DandanSearchAnimeItem(
                        animeId=999999999,
                        bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
                        animeTitle=f"{search_term} 搜索正在启动",
                        type="tvseries",
                        typeDescription="搜索正在启动",
                        imageUrl="/static/logo.png",
                        startDate="2025-01-01T00:00:00+08:00",
                        year=2025,
                        episodeCount=1,
                        rating=0.0,
                        isFavorited=False
                    )
                ])

    # 解析搜索词，提取季度和集数信息
    from .utils import parse_search_keyword
    parsed_info = parse_search_keyword(search_term)

    # 启动新的搜索任务
    search_info = {
        "status": "running",
        "start_time": time.time(),
        "search_term": search_term,
        "parsed_info": parsed_info,  # 保存解析信息
        "results": []
    }
    fallback_search_cache[search_key] = search_info

    # 记录该token正在执行的搜索任务
    token_search_tasks[token] = search_key

    # 直接启动异步搜索任务，不通过任务管理器
    import asyncio

    async def run_fallback_search():
        """在后台运行后备搜索，不阻塞主流程"""
        try:
            # 空的进度回调，因为不在任务管理器中
            async def dummy_progress_callback(progress: int, message: str):
                pass

            # 直接使用传入的session执行搜索
            await _execute_fallback_search_task(
                search_term, search_key, token, session, dummy_progress_callback,
                scraper_manager, metadata_manager, config_manager,
                rate_limiter, title_recognition_manager
            )
        except Exception as e:
            logger.error(f"后备搜索任务执行失败: {e}", exc_info=True)
            # 更新缓存状态为失败
            if search_key in fallback_search_cache:
                fallback_search_cache[search_key]["status"] = "failed"
        finally:
            # 清理token搜索任务记录
            if token in token_search_tasks and token_search_tasks[token] == search_key:
                del token_search_tasks[token]

    # 启动后台任务
    try:
        asyncio.create_task(run_fallback_search())
        logger.info(f"后备搜索任务已启动: {search_term}")
    except Exception as e:
        logger.error(f"启动后备搜索任务失败: {e}")
        search_info["status"] = "failed"
        return DandanSearchAnimeResponse(animes=[])

    # 立即返回"搜索中"状态，让用户知道搜索正在进行
    return DandanSearchAnimeResponse(animes=[
        DandanSearchAnimeItem(
            animeId=999999999,  # 使用特定的不会冲突的数字
            bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
            animeTitle=f"{search_term} 搜索正在启动",
            type="tvseries",
            typeDescription="0%",
            imageUrl="/static/logo.png",
            startDate="2025-01-01T00:00:00+08:00",
            year=2025,
            episodeCount=1,
            rating=0.0,
            isFavorited=False
        )
    ])

async def _execute_fallback_search_task(
    search_term: str,
    search_key: str,
    token: str,
    session: AsyncSession,
    progress_callback,
    scraper_manager: ScraperManager,
    metadata_manager: MetadataSourceManager,
    config_manager: ConfigManager,
    rate_limiter: RateLimiter,
    title_recognition_manager
):
    """
    执行后备搜索任务
    """
    try:
        # 更新进度
        await progress_callback(10, "开始搜索...")

        # 1. 使用与WebUI相同的搜索逻辑
        from . import crud
        import re

        # 获取用户对象（系统用户）
        from . import models
        user = models.User(id=0, username="system")

        # 2. 获取别名和补充搜索结果（与WebUI相同）
        await progress_callback(20, "获取别名...")
        try:
            all_possible_aliases, _ = await metadata_manager.search_supplemental_sources(search_term, user)
        except Exception as e:
            logger.warning(f"获取别名失败: {e}")
            all_possible_aliases = set()

        # 3. 验证别名相似度（与WebUI相同的逻辑）
        validated_aliases = set()
        for alias in all_possible_aliases:
            similarity = fuzz.token_set_ratio(search_term, alias)
            if similarity >= 75:  # 与WebUI相同的阈值
                validated_aliases.add(alias)

        filter_aliases = validated_aliases
        filter_aliases.add(search_term)  # 确保原始搜索词总是在列表中
        logger.info(f"用于过滤的别名列表: {list(filter_aliases)}")

        # 4. 执行全网搜索（与WebUI相同）
        await progress_callback(40, "执行全网搜索...")
        all_results = await scraper_manager.search_all([search_term])
        logger.info(f"直接搜索完成，找到 {len(all_results)} 个原始结果。")

        # 5. 使用与WebUI相同的过滤逻辑
        def normalize_for_filtering(title: str) -> str:
            if not title: return ""
            title = re.sub(r'[\[【(（].*?[\]】)）]', '', title)
            return title.lower().replace(" ", "").replace("：", ":").strip()

        normalized_filter_aliases = {normalize_for_filtering(alias) for alias in filter_aliases if alias}
        filtered_results = []
        for item in all_results:
            normalized_item_title = normalize_for_filtering(item.title)
            if not normalized_item_title: continue

            # 使用与WebUI相同的过滤条件
            if any(fuzz.partial_ratio(normalized_item_title, alias) > 85 for alias in normalized_filter_aliases):
                filtered_results.append(item)

        logger.info(f"别名过滤: 从 {len(all_results)} 个原始结果中，保留了 {len(filtered_results)} 个相关结果。")

        # 6. 使用与WebUI相同的排序逻辑
        await progress_callback(70, "排序搜索结果...")
        source_settings = await crud.get_all_scraper_settings(session)
        source_order_map = {s['providerName']: s['displayOrder'] for s in source_settings}

        def sort_key(item):
            provider_order = source_order_map.get(item.provider, 999)
            similarity_score = fuzz.token_set_ratio(search_term, item.title)
            return (provider_order, -similarity_score)

        sorted_results = sorted(filtered_results, key=sort_key)

        # 7. 转换为DandanSearchAnimeItem格式
        await progress_callback(80, "转换搜索结果...")
        search_results = []

        # 获取下一个虚拟animeId（6位数字，用于显示）
        next_virtual_anime_id = await _get_next_virtual_anime_id()

        for i, result in enumerate(sorted_results):
            # 为每个搜索结果分配一个虚拟animeId
            current_virtual_anime_id = next_virtual_anime_id + i

            # 使用弹幕库现有的格式：A + 虚拟animeId
            unique_bangumi_id = f"A{current_virtual_anime_id}"

            # 在标题后面添加来源和年份信息
            year_info = f" 年份：{result.year}" if result.year else ""
            title_with_source = f"{result.title} （来源：{result.provider}{year_info}）"

            # 存储bangumiId到原始信息的映射
            if search_key in fallback_search_cache:
                if "bangumi_mapping" not in fallback_search_cache[search_key]:
                    fallback_search_cache[search_key]["bangumi_mapping"] = {}
                fallback_search_cache[search_key]["bangumi_mapping"][unique_bangumi_id] = {
                    "provider": result.provider,
                    "media_id": result.mediaId,
                    "original_title": result.title,
                    "type": result.type,
                    "anime_id": current_virtual_anime_id  # 存储虚拟animeId
                }

            # 检查库内是否已有相同标题的分集
            base_type_desc = DANDAN_TYPE_DESC_MAPPING.get(result.type, "其他")
            type_description = base_type_desc

            try:
                # 查询库内已有的分集信息
                from . import crud
                existing_episodes = await crud.get_episode_indices_by_anime_title(session, result.title)
                if existing_episodes:
                    # 将分集列表转换为简洁的范围表示
                    episode_ranges = _format_episode_ranges(existing_episodes)
                    type_description = f"{base_type_desc}（库内：{episode_ranges}）"
            except Exception as e:
                logger.debug(f"查询库内分集信息失败: {e}")
                # 如果查询失败，使用原始描述
                type_description = base_type_desc

            search_results.append(DandanSearchAnimeItem(
                animeId=current_virtual_anime_id,  # 使用虚拟animeId
                bangumiId=unique_bangumi_id,
                animeTitle=title_with_source,
                type=DANDAN_TYPE_MAPPING.get(result.type, "other"),
                typeDescription=type_description,
                imageUrl=result.imageUrl,
                startDate=f"{result.year}-01-01T00:00:00+08:00" if result.year else None,
                year=result.year,
                episodeCount=result.episodeCount or 0,
                rating=0.0,
                isFavorited=False
            ))

        await progress_callback(90, "整理搜索结果...")

        # 更新缓存状态为完成
        if search_key in fallback_search_cache:
            fallback_search_cache[search_key]["status"] = "completed"
            fallback_search_cache[search_key]["results"] = search_results

        # 将搜索结果存储到数据库缓存中（与WebUI搜索一致）
        try:
            from . import crud
            import json

            # 构造缓存键，与WebUI搜索保持一致的格式
            cache_key = f"fallback_search_{search_term}"

            # 将搜索结果转换为可缓存的格式
            cache_data = {
                "search_term": search_term,
                "results": [result.model_dump() for result in search_results],
                "timestamp": time.time()
            }

            # 存储到数据库缓存（10分钟过期）
            await crud.set_cache(session, cache_key, json.dumps(cache_data), ttl_seconds=600)
            logger.info(f"后备搜索结果已存储到数据库缓存: {cache_key}")

        except Exception as e:
            logger.warning(f"存储后备搜索结果到数据库缓存失败: {e}")

        await progress_callback(100, "搜索完成")

    except Exception as e:
        logger.error(f"后备搜索任务执行失败: {e}", exc_info=True)
        # 更新缓存状态为失败
        if search_key in fallback_search_cache:
            fallback_search_cache[search_key]["status"] = "failed"
    finally:
        # 清理token搜索任务记录
        if token in token_search_tasks and token_search_tasks[token] == search_key:
            del token_search_tasks[token]

async def _search_implementation(
    search_term: str,
    episode: Optional[str],
    session: AsyncSession
) -> DandanSearchEpisodesResponse:
    """搜索接口的通用实现，避免代码重复。"""
    search_term = search_term.strip()
    if not search_term:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required query parameter: 'anime' or 'keyword'"
        )

    # 修正：调用 utils 中的全局解析函数，以保持逻辑统一
    parsed_info = parse_search_keyword(search_term)
    title_to_search = parsed_info["title"]
    season_to_search = parsed_info.get("season")
    episode_from_title = parsed_info.get("episode")

    # 优先使用独立的 'episode' 参数
    episode_number_from_param = int(episode) if episode and episode.isdigit() else None
    final_episode_to_search = episode_number_from_param if episode_number_from_param is not None else episode_from_title

    # 使用解析后的信息进行数据库查询
    flat_results = await crud.search_episodes_in_library(
        session,
        anime_title=title_to_search,
        episode_number=final_episode_to_search,
        season_number=season_to_search
    )

    grouped_animes: Dict[int, DandanAnimeInfo] = {}

    for res in flat_results:
        anime_id = res['animeId']
        if anime_id not in grouped_animes:
            dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
            dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")

            grouped_animes[anime_id] = DandanAnimeInfo(
                animeId=anime_id,
                animeTitle=res['animeTitle'],
                imageUrl=res.get('imageUrl') or "",
                searchKeyword=search_term or "",
                type=dandan_type,
                typeDescription=dandan_type_desc,
                # isFavorited 字段现在由数据库查询提供
                isFavorited=res.get('isFavorited', False),
                episodes=[]
            )
        
        grouped_animes[anime_id].episodes.append(
            DandanEpisodeInfo(episodeId=res['episodeId'], episodeTitle=res['episodeTitle'])
        )
    
    return DandanSearchEpisodesResponse(animes=list(grouped_animes.values()))

def _parse_filename_for_match(filename: str) -> Optional[Dict[str, Any]]:
    """
    使用正则表达式从文件名中解析出番剧标题和集数。
    这是一个简化的实现，用于 dandanplay 兼容接口。
    """
    # 移除文件扩展名
    name_without_ext = filename.rsplit('.', 1)[0] if '.' in filename else filename

    # 模式1: SXXEXX 格式 (e.g., "Some.Anime.S01E02.1080p.mkv")
    s_e_pattern = re.compile(
        r"^(?P<title>.+?)"
        r"[\s._-]*"
        r"[Ss](?P<season>\d{1,2})"
        r"[Ee](?P<episode>\d{1,4})"
        r"\b",
        re.IGNORECASE
    )
    match = s_e_pattern.search(name_without_ext)
    if match:
        data = match.groupdict()
        title = data["title"].replace(".", " ").replace("_", " ").strip()
        title = re.sub(r'\[.*?\]', '', title).strip() # 移除字幕组标签
        # 新增：移除标题中的年份并清理多余空格
        title = re.sub(r'\b(19|20)\d{2}\b', '', title).strip()
        title = re.sub(r'\s+', ' ', title).strip(' -')
        return {
            "title": title,
            "season": int(data["season"]),
            "episode": int(data["episode"])
        }

    # 模式2: 只有集数 (e.g., "[Subs] Some Anime - 02 [1080p].mkv")
    ep_only_patterns = [
        re.compile(r"^(?P<title>.+?)\s*[-_]\s*\b(?P<episode>\d{1,4})\b", re.IGNORECASE),
        re.compile(r"^(?P<title>.+?)\s+\b(?P<episode>\d{1,4})\b", re.IGNORECASE),
    ]
    for pattern in ep_only_patterns:
        match = pattern.search(name_without_ext)
        if match:
            data = match.groupdict()
            title = data["title"]
            # 清理标题中的元数据
            title = re.sub(r'\[.*?\]|\(.*?\)|\【.*?\】', '', title).strip()
            title = METADATA_KEYWORDS_PATTERN.sub('', title).strip()
            title = title.replace("_", " ").replace(".", " ").strip()
            # 新增：移除标题中的年份并清理多余空格
            title = re.sub(r'\b(19|20)\d{2}\b', '', title).strip()
            title = re.sub(r'\s+', ' ', title).strip(' -')
            return {
                "title": title,
                "season": None, # 此模式无法识别季度
                "episode": int(data["episode"]),
            }
    
    # 模式3: 电影或单文件视频 (没有集数)
    title = name_without_ext
    title = re.sub(r'\[.*?\]|\(.*?\)|\【.*?\】', '', title).strip()
    title = METADATA_KEYWORDS_PATTERN.sub('', title).strip()
    title = title.replace("_", " ").replace(".", " ").strip()
    # 移除年份, 兼容括号内和独立两种形式
    title = re.sub(r'\(\s*(19|20)\d{2}\s*\)', '', title).strip()
    title = re.sub(r'\b(19|20)\d{2}\b', '', title).strip()
    title = re.sub(r'\s+', ' ', title).strip(' -')
    
    if title:
        return {
            "title": title,
            "season": 1,  # 对电影，默认匹配第1季
            "episode": 1, # 修正：对电影，默认匹配第1集
        }

    return None


async def get_token_from_path(
    request: Request,
    token: str = Path(..., description="路径中的API授权令牌"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    一个 FastAPI 依赖项，用于验证路径中的 token。
    这是为 dandanplay 客户端设计的特殊鉴权方式。
    此函数现在还负责UA过滤和访问日志记录。
    """
    # --- 新增：解析真实客户端IP ---
    # --- 新增：解析真实客户端IP，支持CIDR ---
    config_manager: ConfigManager = request.app.state.config_manager
    trusted_proxies_str = await config_manager.get("trustedProxies", "")
    trusted_networks = []
    if trusted_proxies_str:
        for proxy_entry in trusted_proxies_str.split(','):
            try:
                trusted_networks.append(ipaddress.ip_network(proxy_entry.strip()))
            except ValueError:
                logger.warning(f"无效的受信任代理IP或CIDR: '{proxy_entry.strip()}'，已忽略。")
    
    client_ip_str = request.client.host if request.client else "127.0.0.1"
    is_trusted = False
    if trusted_networks:
        try:
            client_addr = ipaddress.ip_address(client_ip_str)
            is_trusted = any(client_addr in network for network in trusted_networks)
        except ValueError:
            logger.warning(f"无法将客户端IP '{client_ip_str}' 解析为有效的IP地址。")

    if is_trusted:
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            client_ip_str = x_forwarded_for.split(',')[0].strip()
        else:
            # 如果没有 X-Forwarded-For，则回退到 X-Real-IP
            client_ip_str = request.headers.get("x-real-ip", client_ip_str)
    # --- IP解析结束 ---

    # 1. 验证 token 是否存在、启用且未过期
    request_path = request.url.path
    log_path = re.sub(r'^/api/v1/[^/]+', '', request_path) # 从路径中移除 /api/v1/{token} 部分

    token_info = await crud.validate_api_token(session, token=token)
    if not token_info: 
        # 尝试记录失败的访问
        token_record = await crud.get_api_token_by_token_str(session, token)
        if token_record:
            expires_at = token_record.get('expiresAt')
            is_expired = False
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=get_app_timezone())
                is_expired = expires_at < get_now()
            status_to_log = 'denied_expired' if is_expired else 'denied_disabled'
            await crud.create_token_access_log(session, token_record['id'], client_ip_str, request.headers.get("user-agent"), log_status=status_to_log, path=log_path)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API token")

    # 2. UA 过滤
    ua_filter_mode = await crud.get_config_value(session, 'uaFilterMode', 'off')
    user_agent = request.headers.get("user-agent", "")

    if ua_filter_mode != 'off':
        ua_rules = await crud.get_ua_rules(session)
        ua_list = [rule['uaString'] for rule in ua_rules]
        
        is_matched = any(rule in user_agent for rule in ua_list)

        if ua_filter_mode == 'blacklist' and is_matched:
            await crud.create_token_access_log(session, token_info['id'], client_ip_str, user_agent, log_status='denied_ua_blacklist', path=log_path)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User-Agent is blacklisted")
        
        if ua_filter_mode == 'whitelist' and not is_matched:
            await crud.create_token_access_log(session, token_info['id'], client_ip_str, user_agent, log_status='denied_ua_whitelist', path=log_path)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User-Agent not in whitelist")

    # 3. 增加调用计数 (在所有验证通过后)
    await crud.increment_token_call_count(session, token_info['id'])
    await session.commit()

    # 3. 记录成功访问
    await crud.create_token_access_log(session, token_info['id'], client_ip_str, user_agent, log_status='allowed', path=log_path)

    return token

async def get_scraper_manager(request: Request) -> ScraperManager:
    """依赖项：从应用状态获取 Scraper 管理器"""
    return request.app.state.scraper_manager

@implementation_router.get(
    "/search/episodes",
    response_model=DandanSearchEpisodesResponse,
    summary="[dandanplay兼容] 搜索节目和分集"
)
async def search_episodes_for_dandan(
    anime: str = Query(..., description="节目名称"),
    episode: Optional[str] = Query(None, description="分集标题 (通常是数字)"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session)
):
    """
    模拟 dandanplay 的 /api/v2/search/episodes 接口。
    它会搜索 **本地弹幕库** 中的番剧和分集信息。
    """
    search_term = anime.strip()
    return await _search_implementation(search_term, episode, session)

@implementation_router.get(
    "/search/anime",
    response_model=DandanSearchAnimeResponse,
    summary="[dandanplay兼容] 搜索作品"
)
async def search_anime_for_dandan(
    keyword: Optional[str] = Query(None, description="节目名称 (兼容 keyword)"),
    anime: Optional[str] = Query(None, description="节目名称 (兼容 anime)"),
    episode: Optional[str] = Query(None, description="分集标题 (此接口中未使用)"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    config_manager: ConfigManager = Depends(get_config_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    title_recognition_manager = Depends(get_title_recognition_manager)
):
    """
    模拟 dandanplay 的 /api/v2/search/anime 接口。
    它会搜索 **本地弹幕库** 中的番剧信息，不包含分集列表。
    新增：支持后备搜索功能，当库内无结果或指定集数不存在时，触发全网搜索。
    支持SXXEXX格式的季度和集数搜索。
    """
    search_term = keyword or anime
    if not search_term:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required query parameter: 'keyword' or 'anime'"
        )

    # 解析搜索关键词，提取标题、季数和集数
    parsed_info = parse_search_keyword(search_term)
    title_to_search = parsed_info["title"]
    season_to_search = parsed_info.get("season")
    episode_to_search = parsed_info.get("episode")

    # 首先搜索本地库
    db_results = await crud.search_animes_for_dandan(session, search_term)

    # 如果指定了具体集数，需要检查该集数是否存在
    should_trigger_fallback = False
    if db_results and episode_to_search is not None:
        # 检查是否存在指定的集数
        episode_exists = False
        for anime_result in db_results:
            anime_id = anime_result['animeId']
            # 查询该番剧的所有分集
            episodes = await crud.search_episodes_in_library(
                session,
                anime_title=title_to_search,
                episode_number=episode_to_search,
                season_number=season_to_search
            )
            if episodes:
                episode_exists = True
                break

        if not episode_exists:
            logger.info(f"本地库中找到番剧但不存在指定集数 E{episode_to_search:02d}，将触发后备搜索")
            should_trigger_fallback = True

    # 如果本地库有结果且不需要触发后备搜索，直接返回
    if db_results and not should_trigger_fallback:
        animes = []
        for res in db_results:
            dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
            dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
            year = res.get('year')
            start_date_str = None
            if year:
                start_date_str = datetime(year, 1, 1, tzinfo=get_app_timezone()).isoformat()
            elif res.get('startDate'):
                start_date_str = res.get('startDate').isoformat()

            animes.append(DandanSearchAnimeItem(
                animeId=res['animeId'],
                bangumiId=res.get('bangumiId') or f"A{res['animeId']}",
                animeTitle=res['animeTitle'],
                type=dandan_type,
                typeDescription=dandan_type_desc,
                imageUrl=res.get('imageUrl'),
                startDate=start_date_str,
                year=year,
                episodeCount=res.get('episodeCount', 0),
                rating=0.0,
                isFavorited=False
            ))
        return DandanSearchAnimeResponse(animes=animes)

    # 如果本地库无结果或需要触发后备搜索，检查是否启用了后备搜索
    search_fallback_enabled = await config_manager.get("searchFallbackEnabled", "false")
    if search_fallback_enabled.lower() == 'true' and (not db_results or should_trigger_fallback):
        # 检查Token是否被允许使用后备搜索功能
        try:
            import json
            # 获取当前token的信息
            token_stmt = select(orm_models.ApiToken).where(orm_models.ApiToken.token == token)
            token_result = await session.execute(token_stmt)
            current_token_obj = token_result.scalar_one_or_none()

            if current_token_obj:
                # 获取允许的token列表
                allowed_tokens_str = await config_manager.get("matchFallbackTokens", "[]")
                allowed_token_ids = json.loads(allowed_tokens_str)

                # 如果配置了允许的token列表且当前token不在列表中，跳过后备搜索
                if allowed_token_ids and current_token_obj.id not in allowed_token_ids:
                    logger.info(f"Token '{current_token_obj.name}' (ID: {current_token_obj.id}) 未被授权使用后备搜索功能，跳过后备搜索。")
                    return DandanSearchAnimeResponse(animes=[])
                else:
                    logger.info(f"Token '{current_token_obj.name}' (ID: {current_token_obj.id}) 已被授权使用后备搜索功能。")
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"检查后备搜索Token授权时发生错误: {e}，继续执行后备搜索")

        # 使用解析后的标题进行后备搜索，但保留原始搜索词用于缓存键
        search_title_for_fallback = title_to_search
        if episode_to_search is not None:
            # 如果指定了集数，在后备搜索中包含季度和集数信息
            if season_to_search is not None:
                search_title_for_fallback = f"{title_to_search} S{season_to_search:02d}E{episode_to_search:02d}"
            else:
                search_title_for_fallback = f"{title_to_search} E{episode_to_search:02d}"
        elif season_to_search is not None:
            search_title_for_fallback = f"{title_to_search} S{season_to_search:02d}"

        return await _handle_fallback_search(
            search_title_for_fallback, token, session, scraper_manager,
            metadata_manager, config_manager, rate_limiter, title_recognition_manager
        )

    # 本地库无结果且未启用后备搜索，返回空结果
    return DandanSearchAnimeResponse(animes=[])

@implementation_router.get(
    "/bangumi/{bangumiId}",
    response_model=BangumiDetailsResponse,
    summary="[dandanplay兼容] 获取番剧详情"
)
async def get_bangumi_details(
    bangumiId: str = Path(..., description="作品ID, A开头的备用ID, 或真实的Bangumi ID"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    scraper_manager: ScraperManager = Depends(get_scraper_manager)
):
    """
    模拟 dandanplay 的 /api/v2/bangumi/{bangumiId} 接口。
    返回数据库中存储的番剧详细信息。
    新增：处理后备搜索的特殊bangumiId。
    """
    # 检查是否是搜索中的固定bangumiId
    if bangumiId == str(FALLBACK_SEARCH_BANGUMI_ID):
        return BangumiDetailsResponse(
            success=False,
            bangumi=None,
            errorMessage="搜索正在进行，请耐心等待"
        )





    anime_id_int: Optional[int] = None
    if bangumiId.startswith('A') and bangumiId[1:].isdigit():
        # 格式1: "A" + animeId, 例如 "A123"
        anime_id_int = int(bangumiId[1:])

        # 检查是否是后备搜索的虚拟animeId范围（900000-999999）
        if 900000 <= anime_id_int < 1000000:
            # 从所有搜索缓存中查找
            for search_key, search_info in fallback_search_cache.items():
                if search_info["status"] == "completed" and "bangumi_mapping" in search_info:
                    if bangumiId in search_info["bangumi_mapping"]:
                        mapping_info = search_info["bangumi_mapping"][bangumiId]
                        provider = mapping_info["provider"]
                        media_id = mapping_info["media_id"]
                        original_title = mapping_info["original_title"]
                        anime_id = mapping_info["anime_id"]

                        # 记录用户最后选择的虚拟bangumiId
                        user_last_bangumi_choice[search_key] = bangumiId
                        logger.info(f"记录用户选择: search_key={search_key}, bangumiId={bangumiId}, provider={provider}")

                        # 获取原始搜索的季度和集数信息
                        parsed_info = search_info.get("parsed_info", {})
                        target_season = parsed_info.get("season")
                        target_episode = parsed_info.get("episode")

                        episodes = []
                        try:
                            # 完全按照WebUI的流程：调用scraper获取真实的分集信息
                            scraper = scraper_manager.get_scraper(provider)
                            if scraper:
                                # 从映射信息中获取media_type
                                media_type = None
                                for search_key, search_info in fallback_search_cache.items():
                                    if search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
                                        for bangumi_id, mapping_info in search_info["bangumi_mapping"].items():
                                            if mapping_info.get("anime_id") == anime_id:
                                                media_type = mapping_info.get("type")
                                                break
                                        if media_type:
                                            break

                                # 使用与WebUI完全相同的调用方式
                                actual_episodes = await scraper.get_episodes(media_id, db_media_type=media_type)

                                if actual_episodes:
                                    # 检查是否已经有相同剧集的记录（源切换检测）
                                    existing_anime = await _find_existing_anime_by_bangumi_id(session, bangumiId, search_key)

                                    if existing_anime:
                                        # 找到现有剧集，这是源切换行为
                                        real_anime_id = existing_anime['animeId']
                                        logger.info(f"检测到源切换: 剧集'{original_title}' 已存在 (anime_id={real_anime_id})，将更新映射到新源 {provider}")

                                        # 更新现有episodeId的映射关系
                                        for i, episode_data in enumerate(actual_episodes):
                                            episode_id = _generate_episode_id(real_anime_id, 1, i + 1)
                                            await _update_episode_mapping(
                                                session, episode_id, provider, media_id,
                                                i + 1, original_title
                                            )
                                        logger.info(f"源切换: '{original_title}' 更新 {len(actual_episodes)} 个分集映射到 {provider}")
                                    else:
                                        # 新剧集，先检查数据库中是否已有相同标题的条目
                                        from .utils import parse_search_keyword
                                        from .orm_models import Anime

                                        # 解析搜索关键词，提取纯标题
                                        parsed_info = parse_search_keyword(original_title)
                                        base_title = parsed_info["title"]

                                        # 直接在数据库中查找相同标题的条目
                                        stmt = select(Anime.id, Anime.title).where(
                                            Anime.title == base_title,
                                            Anime.season == 1
                                        )
                                        result = await session.execute(stmt)
                                        existing_db_anime = result.mappings().first()

                                        if existing_db_anime:
                                            # 如果数据库中已有相同标题的条目，使用已有的anime_id
                                            real_anime_id = existing_db_anime['id']
                                            logger.info(f"复用已存在的番剧: '{base_title}' (ID={real_anime_id}) 共 {len(actual_episodes)} 集")
                                        else:
                                            # 如果数据库中没有，获取新的真实animeId
                                            real_anime_id = await _get_next_real_anime_id(session)
                                            logger.info(f"新剧集: '{base_title}' (ID={real_anime_id}) 共 {len(actual_episodes)} 集")

                                    # 存储真实animeId到虚拟animeId的映射关系
                                    mapping_info["real_anime_id"] = real_anime_id

                                    for i, episode_data in enumerate(actual_episodes):
                                        episode_index = i + 1

                                        # 如果指定了特定集数，只返回该集数
                                        if target_episode is not None and episode_index != target_episode:
                                            continue

                                        # 使用真实animeId生成标准的episodeId
                                        episode_id = _generate_episode_id(real_anime_id, 1, episode_index)
                                        # 直接使用原始分集标题
                                        episode_title = episode_data.title

                                        # 只有在新剧集时才存储映射关系（源切换时已经在上面更新了）
                                        if not existing_anime:
                                            await _store_episode_mapping(
                                                session, episode_id, provider, media_id,
                                                episode_index, original_title
                                            )

                                        episodes.append(BangumiEpisode(
                                            episodeId=episode_id,
                                            episodeTitle=episode_title,
                                            episodeNumber=str(episode_data.episodeIndex if episode_data.episodeIndex else episode_index)
                                        ))

                                else:
                                    logger.warning(f"从 {provider} 获取分集列表为空: media_id={media_id}")
                            else:
                                logger.error(f"找不到 {provider} 的scraper")

                        except Exception as e:
                            logger.error(f"获取分集列表失败: {e}")
                            episodes = []

                        bangumi_details = BangumiDetails(
                            animeId=anime_id,  # 使用分配的animeId
                            bangumiId=bangumiId,
                            animeTitle=f"{original_title} （来源：{provider}）",
                            imageUrl="/static/logo.png",
                            searchKeyword=original_title,
                            type="other",
                            typeDescription="其他",
                            episodes=episodes,
                            year=2025,
                            summary=f"来自后备搜索的结果 (源: {provider})",
                        )

                        return BangumiDetailsResponse(bangumi=bangumi_details)

            # 如果没找到对应的后备搜索ID，但在范围内，返回过期信息
            if 900000 <= anime_id_int < 1000000:
                return BangumiDetailsResponse(
                    success=True,
                    bangumi=None,
                    errorMessage="搜索结果不存在或已过期"
                )

    elif bangumiId.isdigit():
        # 格式2: 纯数字的 Bangumi ID, 例如 "148099"
        # 我们需要通过 bangumi_id 找到我们自己数据库中的 anime_id
        anime_id_int = await crud.get_anime_id_by_bangumi_id(session, bangumiId)


    if anime_id_int is None:
        return BangumiDetailsResponse(
            success=True,
            bangumi=None,
            errorMessage=f"找不到与标识符 '{bangumiId}' 关联的作品。"
        )

    details = await crud.get_anime_details_for_dandan(session, anime_id_int)
    if not details:
        return BangumiDetailsResponse(
            success=True,
            bangumi=None,
            errorMessage=f"在数据库中找不到ID为 {anime_id_int} 的作品详情。"
        )

    anime_data = details['anime']
    episodes_data = details['episodes']

    dandan_type = DANDAN_TYPE_MAPPING.get(anime_data.get('type'), "other")
    dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(anime_data.get('type'), "其他")

    formatted_episodes = [
        BangumiEpisode(
            episodeId=ep['episodeId'],
            episodeTitle=ep['episodeTitle'],
            episodeNumber=str(ep['episodeNumber'])
        ) for ep in episodes_data
    ]

    bangumi_id_str = anime_data.get('bangumiId') or f"A{anime_data['animeId']}"

    bangumi_details = BangumiDetails(
        animeId=anime_data['animeId'],
        bangumiId=bangumi_id_str,
        animeTitle=anime_data['animeTitle'],
        imageUrl=anime_data.get('imageUrl'),
        searchKeyword=anime_data['animeTitle'],
        type=dandan_type,
        typeDescription=dandan_type_desc,
        episodes=formatted_episodes,
        year=anime_data.get('year'),
        summary="暂无简介",
    )

    return BangumiDetailsResponse(bangumi=bangumi_details)

async def _get_match_for_item(
    item: DandanBatchMatchRequestItem,
    session: AsyncSession,
    task_manager: TaskManager,
    scraper_manager: ScraperManager,
    metadata_manager: MetadataSourceManager,
    config_manager: ConfigManager,
    rate_limiter: RateLimiter,
    title_recognition_manager,
    current_token: Optional[str] = None
) -> DandanMatchResponse:
    """
    通过文件名匹配弹幕库的核心逻辑。此接口不使用文件Hash。
    优先进行库内直接匹配，失败后回退到TMDB剧集组映射。
    新增：如果所有匹配都失败，且启用了后备机制，则触发自动搜索导入任务。
    """
    logger.info(f"执行匹配逻辑, 文件名: '{item.fileName}'")
    parsed_info = _parse_filename_for_match(item.fileName)
    logger.info(f"文件名解析结果: {parsed_info}")
    if not parsed_info:
        response = DandanMatchResponse(isMatched=False)
        logger.info(f"发送匹配响应 (解析失败): {response.model_dump_json(indent=2)}")
        return response

    # --- 步骤 1: 优先进行库内直接搜索 ---
    logger.info("正在进行库内直接搜索...")
    results = await crud.search_episodes_in_library(
        session, parsed_info["title"], parsed_info["episode"], parsed_info.get("season")
    )
    logger.info(f"直接搜索为 '{parsed_info['title']}' (季:{parsed_info.get('season')} 集:{parsed_info.get('episode')}) 找到 {len(results)} 条记录")
    
    if results:
        # 对结果进行严格的标题过滤，避免模糊匹配带来的问题
        normalized_search_title = parsed_info["title"].replace("：", ":").replace(" ", "")
        exact_matches = []
        for r in results:
            all_titles_to_check = [
                r.get('animeTitle'), r.get('nameEn'), r.get('nameJp'), r.get('nameRomaji'),
                r.get('aliasCn1'), r.get('aliasCn2'), r.get('aliasCn3'),
            ]
            aliases_to_check = {t for t in all_titles_to_check if t}
            # 使用normalized_search_title进行更精确的匹配
            if any(fuzz.partial_ratio(alias.replace("：", ":").replace(" ", ""), normalized_search_title) > 85 for alias in aliases_to_check):
                exact_matches.append(r)

        if len(exact_matches) < len(results):
            logger.info(f"过滤掉 {len(results) - len(exact_matches)} 条模糊匹配的结果。")
            results = exact_matches

        if results:
            # 优先处理被精确标记的源
            favorited_results = [r for r in results if r.get('isFavorited')]
            if favorited_results:
                res = favorited_results[0]
                dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
                dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
                match = DandanMatchInfo(
                    episodeId=res['episodeId'], animeId=res['animeId'], animeTitle=res['animeTitle'],
                    episodeTitle=res['episodeTitle'], type=dandan_type, typeDescription=dandan_type_desc,
                )
                response = DandanMatchResponse(isMatched=True, matches=[match])
                logger.info(f"发送匹配响应 (精确标记匹配): {response.model_dump_json(indent=2)}")
                return response

            # 如果没有精确标记，检查所有匹配项是否都指向同一个番剧ID
            first_animeId = results[0]['animeId']
            all_from_same_anime = all(res['animeId'] == first_animeId for res in results)

            if all_from_same_anime:
                res = results[0]
                dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
                dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
                match = DandanMatchInfo(
                    episodeId=res['episodeId'], animeId=res['animeId'], animeTitle=res['animeTitle'],
                    episodeTitle=res['episodeTitle'], type=dandan_type, typeDescription=dandan_type_desc,
                )
                response = DandanMatchResponse(isMatched=True, matches=[match])
                logger.info(f"发送匹配响应 (单一作品匹配): {response.model_dump_json(indent=2)}")
                return response

            # 如果匹配到了多个不同的番剧，则返回所有结果让用户选择
            matches = []
            for res in results:
                dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
                dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
                matches.append(DandanMatchInfo(
                    episodeId=res['episodeId'], animeId=res['animeId'], animeTitle=res['animeTitle'],
                    episodeTitle=res['episodeTitle'], type=dandan_type, typeDescription=dandan_type_desc,
                ))
            response = DandanMatchResponse(isMatched=False, matches=matches)
            logger.info(f"发送匹配响应 (多个匹配): {response.model_dump_json(indent=2)}")
            return response

    # --- 步骤 2: 如果直接搜索无果，则回退到 TMDB 映射 ---
    logger.info("直接搜索未找到精确匹配，回退到 TMDB 映射匹配。")
    potential_animes = await crud.find_animes_for_matching(session, parsed_info["title"])
    logger.info(f"为标题 '{parsed_info['title']}' 找到 {len(potential_animes)} 个可能的库内作品进行TMDB匹配。")

    for anime in potential_animes:
        if anime.get("tmdbId") and anime.get("tmdbEpisodeGroupId"):
            logger.info(f"正在为作品 ID {anime['animeId']} (TMDB ID: {anime['tmdbId']}) 尝试 TMDB 映射匹配...")
            tmdb_results = await crud.find_episode_via_tmdb_mapping(
                session,
                tmdb_id=anime["tmdbId"],
                group_id=anime["tmdbEpisodeGroupId"],
                custom_season=parsed_info.get("season"),
                custom_episode=parsed_info["episode"]
            )
            if tmdb_results:
                logger.info(f"TMDB 映射匹配成功，找到 {len(tmdb_results)} 个结果。")
                res = tmdb_results[0]
                dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
                dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
                match = DandanMatchInfo(
                    episodeId=res['episodeId'], animeId=res['animeId'], animeTitle=res['animeTitle'],
                    episodeTitle=res['episodeTitle'], type=dandan_type, typeDescription=dandan_type_desc,
                )
                response = DandanMatchResponse(isMatched=True, matches=[match])
                logger.info(f"发送匹配响应 (TMDB 映射匹配): {response.model_dump_json(indent=2)}")
                return response

    # --- 步骤 3: 如果所有方法都失败 ---
    # 新增：后备机制 (Fallback Mechanism)
    fallback_enabled_str = await config_manager.get("matchFallbackEnabled", "false")
    if fallback_enabled_str.lower() == 'true':
        # 检查Token是否被允许使用匹配后备功能
        if current_token:
            try:
                import json
                # 获取当前token的信息
                token_stmt = select(orm_models.ApiToken).where(orm_models.ApiToken.token == current_token)
                token_result = await session.execute(token_stmt)
                current_token_obj = token_result.scalar_one_or_none()

                if current_token_obj:
                    # 获取允许的token列表
                    allowed_tokens_str = await config_manager.get("matchFallbackTokens", "[]")
                    allowed_token_ids = json.loads(allowed_tokens_str)

                    # 如果配置了允许的token列表且当前token不在列表中，跳过后备机制
                    if allowed_token_ids and current_token_obj.id not in allowed_token_ids:
                        logger.info(f"Token '{current_token_obj.name}' (ID: {current_token_obj.id}) 未被授权使用匹配后备功能，跳过后备机制。")
                        response = DandanMatchResponse(isMatched=False, matches=[])
                        logger.info(f"发送匹配响应 (Token未授权): {response.model_dump_json(indent=2)}")
                        return response
                    else:
                        logger.info(f"Token '{current_token_obj.name}' (ID: {current_token_obj.id}) 已被授权使用匹配后备功能。")
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"检查匹配后备Token授权时发生错误: {e}，继续执行后备机制")

        # 检查黑名单
        blacklist_pattern = await config_manager.get("matchFallbackBlacklist", "")
        if blacklist_pattern.strip():
            try:
                import re
                if re.search(blacklist_pattern, item.fileName, re.IGNORECASE):
                    logger.info(f"文件 '{item.fileName}' 匹配黑名单规则 '{blacklist_pattern}'，跳过后备机制。")
                    response = DandanMatchResponse(isMatched=False, matches=[])
                    logger.info(f"发送匹配响应 (黑名单过滤): {response.model_dump_json(indent=2)}")
                    return response
            except re.error as e:
                logger.warning(f"黑名单正则表达式 '{blacklist_pattern}' 格式错误: {e}，忽略黑名单检查")

        logger.info(f"匹配失败，已启用后备机制，正在为 '{item.fileName}' 创建自动搜索任务。")
        try:
            # 构造 auto_search_and_import_task 需要的 payload
            # 如果文件名能解析出季度/集数，则认为是电视剧，否则认为是电影
            media_type_for_fallback = "tv_series" if parsed_info.get("season") is not None or parsed_info.get("episode") is not None else "movie"
            
            auto_import_payload = ControlAutoImportRequest(
                searchType="keyword",
                searchTerm=parsed_info["title"],
                season=parsed_info.get("season"),
                episode=parsed_info.get("episode"),
                mediaType=media_type_for_fallback
            )

            # 为后备任务创建一个唯一的键，以防止在短时间内重复提交
            unique_key_parts = ["match-fallback", auto_import_payload.searchTerm]
            if auto_import_payload.season is not None:
                unique_key_parts.append(f"s{auto_import_payload.season}")
            if auto_import_payload.episode is not None:
                # 关键修复：对于单集匹配，将集数也加入唯一键
                unique_key_parts.append(f"e{auto_import_payload.episode}")
            # 关键修复：将媒体类型也加入唯一键，以区分同名的电影和电视剧
            if auto_import_payload.mediaType:
                unique_key_parts.append(auto_import_payload.mediaType)
            unique_key = "-".join(unique_key_parts)

            task_title = f"匹配后备: {item.fileName}"

            # 创建任务协程
            task_coro = lambda session, cb: tasks.auto_search_and_import_task(
                auto_import_payload, cb, session, config_manager, scraper_manager, metadata_manager, task_manager,
                rate_limiter=rate_limiter,
                title_recognition_manager=title_recognition_manager,
                api_key=None # 这是一个内部任务，没有API Key
            )
            
            # 准备任务参数用于恢复
            task_parameters = {
                "searchType": auto_import_payload.searchType,
                "searchTerm": auto_import_payload.searchTerm,
                "season": auto_import_payload.season,
                "episode": auto_import_payload.episode,
                "mediaType": auto_import_payload.mediaType,
                "fileName": item.fileName
            }

            # 提交任务，并捕获可能的冲突异常
            try:
                await task_manager.submit_task(
                    task_coro,
                    task_title,
                    unique_key=unique_key,
                    task_type="match_fallback",
                    task_parameters=task_parameters
                )
                logger.info(f"已为 '{item.fileName}' 成功提交匹配后备任务。")
            except HTTPException as e:
                if e.status_code == 409: # Conflict
                    logger.info(f"匹配后备任务已存在，跳过提交: {e.detail}")
                else:
                    raise # 重新抛出其他HTTP异常
        except Exception as e:
            logger.error(f"提交匹配后备任务时发生错误: {e}", exc_info=True)

    response = DandanMatchResponse(isMatched=False, matches=[])
    logger.info(f"发送匹配响应 (所有方法均未匹配): {response.model_dump_json(indent=2)}")
    return response

@implementation_router.post(
    "/match",
    response_model=DandanMatchResponse,
    summary="[dandanplay兼容] 匹配单个文件"
)
async def match_single_file(
    request: DandanBatchMatchRequestItem,
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    config_manager: ConfigManager = Depends(get_config_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    title_recognition_manager = Depends(get_title_recognition_manager)
):
    """
    通过文件名匹配弹幕库。此接口不使用文件Hash。
    优先进行库内直接匹配，失败后回退到TMDB剧集组映射。
    """
    return await _get_match_for_item(
        request, session, task_manager, scraper_manager,
        metadata_manager, config_manager, rate_limiter, title_recognition_manager,
        current_token=token
    )


@implementation_router.post(
    "/match/batch",
    response_model=List[DandanMatchResponse],
    summary="[dandanplay兼容] 批量匹配文件"
)
async def match_batch_files(
    request: DandanBatchMatchRequest,
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    config_manager: ConfigManager = Depends(get_config_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    title_recognition_manager = Depends(get_title_recognition_manager)
):
    """
    批量匹配文件。
    """
    if len(request.requests) > 32:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="批量匹配请求不能超过32个文件。")

    tasks = [
        _get_match_for_item(
            item, session, task_manager, scraper_manager, metadata_manager, config_manager, rate_limiter, title_recognition_manager,
            current_token=token
        ) for item in request.requests
    ]
    results = await asyncio.gather(*tasks)
    return results


@implementation_router.get(
    "/extcomment",
    response_model=models.CommentResponse,
    summary="[dandanplay兼容] 获取外部弹幕"
)
async def get_external_comments_from_url(
    url: str = Query(..., description="外部视频链接 (支持 Bilibili, 腾讯, 爱奇艺, 优酷, 芒果TV)"),
    chConvert: int = Query(0, description="中文简繁转换。0-不转换，1-转换为简体，2-转换为繁体。"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    manager: ScraperManager = Depends(get_scraper_manager)
):
    """
    从外部URL获取弹幕，并转换为dandanplay格式。
    结果会被缓存5小时。
    """
    cache_key = f"ext_danmaku_v2_{url}"
    cached_comments = await crud.get_cache(session, cache_key)
    if cached_comments is not None:
        logger.info(f"外部弹幕缓存命中: {url}")
        comments_data = cached_comments
    else:
        logger.info(f"外部弹幕缓存未命中，正在从网络获取: {url}")
        scraper = manager.get_scraper_by_domain(url)
        if not scraper:
            raise HTTPException(status_code=400, detail="不支持的URL或视频源。")

        try:
            provider_episode_id = await scraper.get_id_from_url(url)
            if not provider_episode_id:
                raise ValueError(f"无法从URL '{url}' 中解析出有效的视频ID。")
            
            episode_id_for_comments = scraper.format_episode_id_for_comments(provider_episode_id)
            comments_data = await scraper.get_comments(episode_id_for_comments)

            # 修正：使用 scraper.provider_name 修复未定义的 'provider' 变量
            if not comments_data: logger.warning(f"未能从 {scraper.provider_name} URL 获取任何弹幕: {url}")

        except Exception as e:
            logger.error(f"处理 {scraper.provider_name} 外部弹幕时出错: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"获取 {scraper.provider_name} 弹幕失败。")

        # 缓存结果5小时 (18000秒)
        await crud.set_cache(session, cache_key, comments_data, 18000)

    # 处理简繁转换
    if chConvert in [1, 2]:
        converter = None
        if chConvert == 1:
            converter = OpenCC('t2s')  # 繁转简
        elif chConvert == 2:
            converter = OpenCC('s2t')  # 简转繁
        
        if converter:
            for comment in comments_data:
                comment['m'] = converter.convert(comment['m'])

    # 修正：使用统一的弹幕处理函数，以确保输出格式符合 dandanplay 客户端规范
    processed_comments = _process_comments_for_dandanplay(comments_data)
    return models.CommentResponse(count=len(processed_comments), comments=processed_comments)

@implementation_router.get(
    "/comment/{episodeId}",
    response_model=models.CommentResponse,
    summary="[dandanplay兼容] 获取弹幕"
)
async def get_comments_for_dandan(
    episodeId: int = Path(..., description="分集ID (来自 /search/episodes 响应中的 episodeId)"),
    chConvert: int = Query(0, description="中文简繁转换。0-不转换，1-转换为简体，2-转换为繁体。"),
    # 'from' 是 Python 的关键字，所以我们必须使用别名
    fromTime: int = Query(0, alias="from", description="弹幕开始时间(秒)"),
    withRelated: bool = Query(True, description="是否包含关联弹幕"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    task_manager: TaskManager = Depends(get_task_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter)
):
    """
    模拟 dandanplay 的弹幕获取接口。
    优化：优先使用弹幕库，如果没有则直接从源站获取并异步存储。
    """
    # 导入必要的模块
    from . import crud

    # 1. 优先从弹幕库获取弹幕
    comments_data = await crud.fetch_comments(session, episodeId)

    if not comments_data:
        logger.info(f"弹幕库中未找到 episodeId={episodeId} 的弹幕，尝试直接从源站获取")

        # 检查弹幕获取缓存
        cache_key = f"comments_{episodeId}"
        if cache_key in comments_fetch_cache:
            logger.info(f"从缓存中获取 episodeId={episodeId} 的弹幕")
            comments_data = comments_fetch_cache[cache_key]

            # 即使从缓存获取，也需要保存到数据库和XML文件
            if comments_data and str(episodeId).startswith("25") and len(str(episodeId)) >= 13:
                try:
                    # 解析episodeId获取anime_id和episode_number
                    episode_id_str = str(episodeId)
                    real_anime_id = int(episode_id_str[2:8])
                    episode_number = int(episode_id_str[10:14])

                    # 获取映射信息
                    mapping_data = await _get_episode_mapping(session, episodeId)
                    if mapping_data:
                        provider = mapping_data["provider"]
                        media_id = mapping_data["media_id"]
                        original_title = mapping_data["original_title"]

                        # 复用现有的保存逻辑：查找或创建动画条目、源关联、分集条目，然后保存弹幕
                        try:
                            # 1. 首先尝试根据real_anime_id查找已存在的anime记录
                            from .orm_models import Anime
                            existing_anime_stmt = select(Anime).where(Anime.id == real_anime_id)
                            existing_anime_result = await session.execute(existing_anime_stmt)
                            existing_anime = existing_anime_result.scalar_one_or_none()

                            if existing_anime:
                                # 如果已存在，直接使用
                                anime_id = existing_anime.id
                                logger.info(f"找到已存在的番剧: ID={anime_id}, 标题='{existing_anime.title}', 季数={existing_anime.season}")
                            else:
                                # 如果不存在，解析标题并检查数据库中是否已有相同条目
                                from .utils import parse_search_keyword
                                parsed_info = parse_search_keyword(original_title)
                                base_title = parsed_info["title"]

                                # 直接在数据库中查找相同标题的条目（不应用标题识别转换）
                                stmt = select(Anime.id, Anime.title).where(
                                    Anime.title == base_title,
                                    Anime.season == 1
                                )
                                result = await session.execute(stmt)
                                existing_anime_row = result.mappings().first()

                                if existing_anime_row:
                                    # 如果已存在，直接使用
                                    anime_id = existing_anime_row['id']
                                    logger.info(f"找到已存在的番剧（按标题）: ID={anime_id}, 标题='{base_title}'")
                                else:
                                    # 如果不存在，创建新的（使用解析后的纯标题）
                                    anime_id = await crud.get_or_create_anime(
                                        session, base_title, "tv_series", 1,
                                        None, None, None, None, provider
                                    )

                            # 2. 创建源关联
                            source_id = await crud.link_source_to_anime(
                                session, anime_id, provider, media_id
                            )

                            # 3. 创建分集条目（使用原生标题）
                            episode_title = f"第{episode_number}集"  # 缓存弹幕时暂时使用默认标题
                            episode_db_id = await crud.create_episode_if_not_exists(
                                session, anime_id, source_id, episode_number,
                                episode_title, "", f"{provider}_{media_id}_{episode_number}"
                            )

                            # 4. 保存弹幕到数据库和XML文件
                            added_count = await crud.save_danmaku_for_episode(
                                session, episode_db_id, comments_data, config_manager
                            )
                            await session.commit()

                            logger.info(f"缓存弹幕已保存到数据库和XML文件: anime_id={anime_id}, source_id={source_id}, episode_db_id={episode_db_id}, 保存了 {added_count} 条弹幕")
                        except Exception as save_error:
                            logger.error(f"保存缓存弹幕到数据库失败: {save_error}", exc_info=True)
                            await session.rollback()
                except Exception as e:
                    logger.warning(f"处理缓存弹幕保存时发生错误: {e}")
                    # 不影响弹幕返回，继续执行
        else:
            # 2. 检查是否是后备搜索的特殊episodeId（以25开头的新格式）
            if str(episodeId).startswith("25") and len(str(episodeId)) >= 13:  # 新的ID格式
                # 解析episodeId：25 + animeId(6位) + 源顺序(2位) + 集编号(4位)
                episode_id_str = str(episodeId)
                real_anime_id = int(episode_id_str[2:8])  # 提取真实animeId
                _ = int(episode_id_str[8:10])  # 提取源顺序（暂时不使用）
                episode_number = int(episode_id_str[10:14])  # 提取集编号

            # 查找对应的映射信息
            episode_url = None
            provider = None

            # 首先尝试从数据库缓存中获取episodeId的映射
            mapping_data = await _get_episode_mapping(session, episodeId)
            if mapping_data:
                episode_url = mapping_data["media_id"]
                provider = mapping_data["provider"]
                logger.info(f"从缓存获取episodeId映射: episodeId={episodeId}, provider={provider}, url={episode_url}")
            else:
                # 如果缓存中没有，回退到原来的逻辑（兼容性）
                # 首先尝试根据用户最后的选择来确定源
                for search_key, search_info in fallback_search_cache.items():
                    if search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
                        # 检查是否有用户最后的选择记录
                        if search_key in user_last_bangumi_choice:
                            last_bangumi_id = user_last_bangumi_choice[search_key]
                            if last_bangumi_id in search_info["bangumi_mapping"]:
                                mapping_info = search_info["bangumi_mapping"][last_bangumi_id]
                                # 检查真实animeId是否匹配
                                if mapping_info.get("real_anime_id") == real_anime_id:
                                    episode_url = mapping_info["media_id"]
                                    provider = mapping_info["provider"]
                                    logger.info(f"根据用户最后选择找到映射: bangumiId={last_bangumi_id}, provider={provider}")
                                    break

                # 如果没有找到用户最后的选择，则使用原来的逻辑
                if not episode_url:
                    for _, search_info in fallback_search_cache.items():
                        if search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
                            for bangumi_id, mapping_info in search_info["bangumi_mapping"].items():
                                # 检查真实animeId是否匹配
                                if mapping_info.get("real_anime_id") == real_anime_id:
                                    episode_url = mapping_info["media_id"]
                                    provider = mapping_info["provider"]
                                    logger.info(f"根据真实animeId={real_anime_id}找到映射: bangumiId={bangumi_id}, provider={provider}")
                                    break
                            if episode_url:
                                break

            if episode_url and provider:
                logger.info(f"找到后备搜索映射: provider={provider}, url={episode_url}")

                # 检查是否已有相同的弹幕下载任务正在进行
                task_unique_key = f"fallback_comments_{episodeId}"
                existing_task = await crud.find_recent_task_by_unique_key(session, task_unique_key, 1)
                if existing_task:
                    logger.info(f"弹幕下载任务已存在: {task_unique_key}")
                    # 如果任务正在进行，返回空结果，让用户稍后再试
                    return models.CommentResponse(count=0, comments=[])

                # 3. 将弹幕下载包装成任务管理器任务
                # 保存当前作用域的变量，避免闭包问题
                current_provider = provider
                current_episode_url = episode_url
                current_episode_number = episode_number
                current_episodeId = episodeId
                current_config_manager = config_manager
                current_scraper_manager = scraper_manager
                current_rate_limiter = rate_limiter

                async def download_comments_task(task_session, progress_callback):
                    try:
                        await progress_callback(10, "开始获取弹幕...")
                        scraper = current_scraper_manager.get_scraper(current_provider)
                        if scraper:
                            # 首先获取分集列表
                            await progress_callback(30, "获取分集列表...")
                            # 查找映射信息
                            mapping_info = None
                            for search_key, search_info in fallback_search_cache.items():
                                if search_key in user_last_bangumi_choice:
                                    last_bangumi_id = user_last_bangumi_choice[search_key]
                                    if last_bangumi_id in search_info.get("bangumi_mapping", {}):
                                        mapping_info = search_info["bangumi_mapping"][last_bangumi_id]
                                        break

                            if not mapping_info:
                                logger.error("无法找到映射信息")
                                return None

                            media_type = mapping_info.get("type", "movie")
                            episodes_list = await scraper.get_episodes(current_episode_url, db_media_type=media_type)

                        if episodes_list and len(episodes_list) >= current_episode_number:
                            # 获取对应集数的分集信息（episode_number是从1开始的）
                            target_episode = episodes_list[current_episode_number - 1]
                            provider_episode_id = target_episode.episodeId
                            # 使用原生分集标题
                            original_episode_title = target_episode.title

                            if provider_episode_id:
                                episode_id_for_comments = scraper.format_episode_id_for_comments(provider_episode_id)

                                # 使用三线程下载模式获取弹幕
                                from .models import ProviderEpisodeInfo
                                virtual_episode = ProviderEpisodeInfo(
                                    provider=current_provider,
                                    episodeIndex=current_episode_number,
                                    title=original_episode_title,  # 使用原生标题
                                    episodeId=episode_id_for_comments,
                                    url=""
                                )

                                # 使用并发下载获取弹幕（三线程模式）
                                async def dummy_progress_callback(_, _unused):
                                    pass  # 空的异步进度回调，忽略所有参数

                                download_results = await tasks._download_episode_comments_concurrent(
                                    scraper, [virtual_episode], current_rate_limiter,
                                    dummy_progress_callback
                                )

                                # 提取弹幕数据
                                raw_comments_data = None
                                if download_results and len(download_results) > 0:
                                    _, comments = download_results[0]  # 忽略episode_index
                                    raw_comments_data = comments
                            else:
                                logger.warning(f"无法获取 {current_provider} 的分集ID: episode_number={current_episode_number}")
                                raw_comments_data = None
                        else:
                            logger.warning(f"从 {current_provider} 获取分集列表失败或集数不足: media_id={current_episode_url}, episode_number={current_episode_number}")
                            raw_comments_data = None

                        if raw_comments_data:
                                logger.info(f"成功从 {current_provider} 获取 {len(raw_comments_data)} 条弹幕")
                                await progress_callback(90, "弹幕获取完成，正在创建数据库条目...")

                                # 参考 WebUI 导入逻辑：先获取弹幕成功，再创建数据库条目
                                try:
                                    from . import crud

                                    # 从映射信息中获取创建条目所需的数据
                                    original_title = mapping_info.get("original_title", "未知标题")
                                    media_type = mapping_info.get("type", "movie")

                                    # 从搜索缓存中获取更多信息（年份、海报等）和搜索关键词
                                    year = None
                                    image_url = None
                                    search_keyword = None
                                    for search_key, search_info in fallback_search_cache.items():
                                        if search_key in user_last_bangumi_choice:
                                            last_bangumi_id = user_last_bangumi_choice[search_key]
                                            if last_bangumi_id in search_info.get("bangumi_mapping", {}):
                                                # 获取搜索关键词（从search_key中提取）
                                                if search_key.startswith("search_"):
                                                    # 从fallback_search_cache中获取原始搜索词
                                                    search_keyword = search_info.get("search_term")

                                                for result in search_info.get("results", []):
                                                    # result 是 DandanSearchAnimeItem 对象，使用属性访问
                                                    if hasattr(result, 'bangumiId') and result.bangumiId == last_bangumi_id:
                                                        year = getattr(result, 'year', None)
                                                        image_url = getattr(result, 'imageUrl', None)
                                                        break
                                                break

                                    # 解析搜索关键词，提取纯标题（如"天才基本法 S01E13" -> "天才基本法"）
                                    from .utils import parse_search_keyword
                                    search_term = search_keyword or original_title
                                    parsed_info = parse_search_keyword(search_term)
                                    base_title = parsed_info["title"]

                                    # 由于我们在分配real_anime_id时已经检查了数据库，这里直接使用real_anime_id
                                    # 如果数据库中已有相同标题的条目，real_anime_id就是已有的anime_id
                                    # 如果没有，real_anime_id就是新分配的anime_id，需要创建条目

                                    # 检查数据库中是否已有这个anime_id的条目
                                    from .orm_models import Anime
                                    stmt = select(Anime.id).where(Anime.id == real_anime_id)
                                    result = await task_session.execute(stmt)
                                    existing_anime_row = result.scalar_one_or_none()

                                    if existing_anime_row:
                                        # 如果已存在，直接使用
                                        anime_id = real_anime_id
                                        logger.info(f"使用已存在的番剧: ID={anime_id}")
                                    else:
                                        # 如果不存在，直接创建新的（使用real_anime_id作为指定ID）
                                        from .orm_models import Anime
                                        from .timezone import get_now
                                        new_anime = Anime(
                                            id=real_anime_id,
                                            title=base_title,
                                            type=media_type,
                                            season=1,
                                            year=year,
                                            imageUrl=image_url,
                                            createdAt=get_now()
                                        )
                                        task_session.add(new_anime)
                                        await task_session.flush()  # 确保ID可用
                                        anime_id = real_anime_id
                                        logger.info(f"创建新番剧: ID={anime_id}, 标题='{base_title}', 年份={year}")

                                    # 2. 创建源关联
                                    source_id = await crud.link_source_to_anime(
                                        task_session, anime_id, current_provider, current_episode_url
                                    )

                                    # 3. 创建分集条目（使用原生标题）
                                    episode_db_id = await crud.create_episode_if_not_exists(
                                        task_session, anime_id, source_id, current_episode_number,
                                        original_episode_title, "", provider_episode_id
                                    )

                                    # 4. 保存弹幕到数据库
                                    added_count = await crud.save_danmaku_for_episode(
                                        task_session, episode_db_id, raw_comments_data, current_config_manager
                                    )
                                    await task_session.commit()

                                    logger.info(f"数据库条目创建完成: anime_id={anime_id}, source_id={source_id}, episode_db_id={episode_db_id}, 保存了 {added_count} 条弹幕")

                                except Exception as db_error:
                                    logger.error(f"创建数据库条目失败: {db_error}", exc_info=True)
                                    await task_session.rollback()

                                # 存储到缓存中
                                cache_key = f"comments_{current_episodeId}"
                                comments_fetch_cache[cache_key] = raw_comments_data

                                # 返回弹幕数据（无论数据库操作是否成功）
                                return raw_comments_data
                        else:
                            logger.warning(f"获取弹幕失败")
                            return None
                    except Exception as e:
                        logger.error(f"弹幕下载任务执行失败: {e}", exc_info=True)
                        return None

                # 提交弹幕下载任务
                try:
                    task_id, done_event = await task_manager.submit_task(
                        download_comments_task,
                        f"后备搜索弹幕下载: episodeId={episodeId}",
                        unique_key=task_unique_key,
                        task_type="download_comments"
                    )
                    logger.info(f"已提交弹幕下载任务: {task_id}")

                    # 等待任务完成，但设置较短的超时时间（30秒）
                    try:
                        await asyncio.wait_for(done_event.wait(), timeout=30.0)
                        # 任务完成，检查缓存中是否有结果
                        cache_key = f"comments_{episodeId}"
                        if cache_key in comments_fetch_cache:
                            comments_data = comments_fetch_cache[cache_key]
                            logger.info(f"弹幕下载任务快速完成，获得 {len(comments_data)} 条弹幕")
                        else:
                            logger.warning(f"任务完成但缓存中未找到弹幕数据")
                    except asyncio.TimeoutError:
                        logger.info(f"弹幕下载任务未在30秒内完成，任务将继续在后台运行")
                        # 任务继续在后台运行，下次访问时就能从数据库获取

                except HTTPException as e:
                    if e.status_code == 409:  # 任务已在运行中
                        logger.info(f"弹幕下载任务已在运行中，等待现有任务完成...")
                        # 尝试等待现有任务完成，但设置较短的超时时间
                        try:
                            # 等待一段时间，看是否能从缓存中获取结果
                            await asyncio.sleep(5.0)  # 等待5秒
                            cache_key = f"comments_{episodeId}"
                            if cache_key in comments_fetch_cache:
                                comments_data = comments_fetch_cache[cache_key]
                                logger.info(f"从缓存中获取到弹幕数据: {len(comments_data)} 条")
                            else:
                                logger.info(f"等待5秒后仍未从缓存获取到数据，任务可能仍在进行中")
                        except Exception as wait_error:
                            logger.warning(f"等待现有任务时发生错误: {wait_error}")
                    else:
                        logger.error(f"提交弹幕下载任务失败: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"提交弹幕下载任务失败: {e}", exc_info=True)

        # 如果仍然没有弹幕数据，返回空结果
        if not comments_data:
            logger.warning(f"无法获取 episodeId={episodeId} 的弹幕数据")
            return models.CommentResponse(count=0, comments=[])

    # 应用弹幕输出上限（按时间段均匀采样，带缓存）
    limit_str = await config_manager.get('danmakuOutputLimitPerSource', '-1')
    try:
        limit = int(limit_str)
    except (ValueError, TypeError):
        limit = -1

    # 应用限制：按时间段均匀采样
    if limit > 0 and len(comments_data) > limit:
        # 检查缓存
        cache_key = f"sampled_{episodeId}_{limit}"
        current_time = time.time()

        # 清理过期缓存
        expired_keys = [
            key for key, (_, timestamp) in sampled_comments_cache.items()
            if current_time - timestamp > SAMPLED_CACHE_TTL
        ]
        for key in expired_keys:
            del sampled_comments_cache[key]
            logger.debug(f"清理过期采样缓存: {key}")

        # 尝试从缓存获取
        if cache_key in sampled_comments_cache:
            cached_comments, cached_time = sampled_comments_cache[cache_key]
            if current_time - cached_time <= SAMPLED_CACHE_TTL:
                logger.info(f"使用缓存的采样结果: episodeId={episodeId}, limit={limit}, 缓存时间={int(current_time - cached_time)}秒前")
                comments_data = cached_comments
            else:
                # 缓存过期,重新采样
                logger.info(f"弹幕数量 {len(comments_data)} 超过限制 {limit}，开始均匀采样 (缓存已过期)")
                from .utils import sample_comments_evenly
                original_count = len(comments_data)
                comments_data = sample_comments_evenly(comments_data, limit)
                logger.info(f"弹幕采样完成: {original_count} -> {len(comments_data)} 条")

                # 更新缓存
                sampled_comments_cache[cache_key] = (comments_data, current_time)
        else:
            # 无缓存,执行采样
            logger.info(f"弹幕数量 {len(comments_data)} 超过限制 {limit}，开始均匀采样")
            from .utils import sample_comments_evenly
            original_count = len(comments_data)
            comments_data = sample_comments_evenly(comments_data, limit)
            logger.info(f"弹幕采样完成: {original_count} -> {len(comments_data)} 条")

            # 存入缓存
            sampled_comments_cache[cache_key] = (comments_data, current_time)
            logger.debug(f"采样结果已缓存: {cache_key}")

    # UA 已由 get_token_from_path 依赖项记录
    logger.debug(f"弹幕接口响应 (episodeId: {episodeId}): 总计 {len(comments_data)} 条弹幕")

    # 修正：使用统一的弹幕处理函数，以确保输出格式符合 dandanplay 客户端规范
    processed_comments = _process_comments_for_dandanplay(comments_data)

    return models.CommentResponse(count=len(processed_comments), comments=processed_comments)

# --- 路由挂载 ---
# 将实现路由挂载到主路由上，以支持两种URL结构。

# 2. 挂载以支持兼容路径: /{token}/api/v2/...
dandan_router.include_router(implementation_router, prefix="/{token}/api/v2")
# 1. 挂载以支持直接路径: /{token}/...
dandan_router.include_router(implementation_router, prefix="/{token}")