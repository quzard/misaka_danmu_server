import logging
import secrets
import uuid
from typing import List, Optional, Dict, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import APIKeyQuery
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, tasks
from ..config_manager import ConfigManager
from ..database import get_db_session
from ..metadata_manager import MetadataSourceManager
from ..scraper_manager import ScraperManager
from ..task_manager import TaskManager, TaskSuccess

logger = logging.getLogger(__name__)
router = APIRouter()

# --- 依赖项 ---

def get_scraper_manager(request: Request) -> ScraperManager:
    """依赖项：从应用状态获取 Scraper 管理器"""
    return request.app.state.scraper_manager

def get_metadata_manager(request: Request) -> MetadataSourceManager:
    """依赖项：从应用状态获取元数据源管理器"""
    return request.app.state.metadata_manager

def get_task_manager(request: Request) -> TaskManager:
    """依赖项：从应用状态获取任务管理器"""
    return request.app.state.task_manager

def get_config_manager(request: Request) -> ConfigManager:
    """依赖项：从应用状态获取配置管理器"""
    return request.app.state.config_manager

# 新增：定义API Key的安全方案，这将自动在Swagger UI中生成“Authorize”按钮
api_key_scheme = APIKeyQuery(name="api_key", auto_error=False, description="用于所有外部控制API的访问密钥。")

async def verify_api_key(
    request: Request,
    api_key: str = Depends(api_key_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> str:
    """依赖项：验证API密钥并记录请求。如果验证成功，返回 API Key。"""
    endpoint = request.url.path
    ip_address = request.client.host

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: API Key is missing.",
        )

    stored_key = await crud.get_config_value(session, "external_api_key", "")

    if not stored_key or not secrets.compare_digest(api_key, stored_key):
        await crud.create_external_api_log(
            session, ip_address, endpoint, status.HTTP_401_UNAUTHORIZED, "无效的API密钥"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的API密钥"
        )
    return api_key

# --- Pydantic 模型 ---

class ControlActionResponse(BaseModel):
    """通用操作成功响应模型"""
    message: str

class ControlSearchResultItem(models.ProviderSearchInfo):
    result_index: int = Field(..., description="结果在列表中的顺序索引，从0开始")

class ControlSearchResponse(BaseModel):
    searchId: str = Field(..., description="本次搜索操作的唯一ID，用于后续操作")
    results: List[ControlSearchResultItem] = Field(..., description="搜索结果列表")

class ControlDirectImportRequest(BaseModel):
    searchId: str = Field(..., description="来自搜索响应的searchId")
    result_index: int = Field(..., ge=0, description="要导入的结果的索引 (从0开始)")
    # Optional fields to override or provide metadata IDs during import
    tmdbId: Optional[str] = Field(None, alias="tmdb_id", description="强制指定TMDB ID")
    tvdbId: Optional[str] = Field(None, alias="tvdb_id", description="强制指定TVDB ID")
    bangumiId: Optional[str] = Field(None, alias="bangumi_id", description="强制指定Bangumi ID")
    imdbId: Optional[str] = Field(None, alias="imdb_id", description="强制指定IMDb ID")
    doubanId: Optional[str] = Field(None, alias="douban_id", description="强制指定豆瓣 ID")

    class Config:
        populate_by_name = True

class ControlEditedImportRequest(BaseModel):
    searchId: str = Field(..., description="来自搜索响应的searchId")
    result_index: int = Field(..., ge=0, description="要编辑的结果的索引 (从0开始)")
    title: Optional[str] = Field(None, description="覆盖原始标题")
    tmdbId: Optional[str] = Field(None, alias="tmdb_id", description="强制指定TMDB ID")
    tmdbEpisodeGroupId: Optional[str] = Field(None, alias="tmdb_episode_group_id", description="强制指定TMDB剧集组ID")
    tvdbId: Optional[str] = Field(None, alias="tvdb_id", description="强制指定TVDB ID")
    bangumiId: Optional[str] = Field(None, alias="bangumi_id", description="强制指定Bangumi ID")
    imdbId: Optional[str] = Field(None, alias="imdb_id", description="强制指定IMDb ID")
    doubanId: Optional[str] = Field(None, alias="douban_id", description="强制指定豆瓣 ID")
    episodes: List[models.ProviderEpisodeInfo] = Field(..., description="编辑后的分集列表")

    class Config:
        populate_by_name = True

class ControlUrlImportRequest(BaseModel):
    url: str = Field(..., description="要导入的作品的URL (例如B站番剧主页)")
    # Optional fields to override or provide metadata IDs during import
    title: Optional[str] = Field(None, description="强制覆盖从URL页面获取的标题")
    season: Optional[int] = Field(None, description="强制覆盖从URL页面获取的季度")
    tmdb_id: Optional[str] = Field(None, description="强制指定TMDB ID")
    tvdb_id: Optional[str] = Field(None, description="强制指定TVDB ID")
    bangumi_id: Optional[str] = Field(None, description="强制指定Bangumi ID")
    imdb_id: Optional[str] = Field(None, description="强制指定IMDb ID")
    douban_id: Optional[str] = Field(None, description="强制指定豆瓣 ID")

class DanmakuOutputSettings(BaseModel):
    limit_per_source: int
    aggregation_enabled: bool

class ControlAnimeDetailsResponse(BaseModel):
    """用于外部API的番剧详情响应模型，不包含冗余的anime_id。"""
    title: str
    type: str
    season: int
    episode_count: Optional[int] = None
    local_image_path: Optional[str] = None
    image_url: Optional[str] = None
    tmdb_id: Optional[str] = None
    tmdb_episode_group_id: Optional[str] = None
    bangumi_id: Optional[str] = None
    tvdb_id: Optional[str] = None
    douban_id: Optional[str] = None
    imdb_id: Optional[str] = None
    name_en: Optional[str] = None
    name_jp: Optional[str] = None
    name_romaji: Optional[str] = None
    alias_cn_1: Optional[str] = None
    alias_cn_2: Optional[str] = None
    alias_cn_3: Optional[str] = None

# --- API 路由 ---

@router.get("/search", response_model=ControlSearchResponse, summary="搜索媒体")
async def search_media(
    keyword: str,
    season: Optional[int] = Query(None, description="要搜索的季度 (可选)"),
    episode: Optional[int] = Query(None, description="要搜索的集数 (可选)"),
    session: AsyncSession = Depends(get_db_session),
    manager: ScraperManager = Depends(get_scraper_manager),
    api_key: str = Depends(verify_api_key),
):
    """
    根据关键词从所有启用的源搜索媒体。
    - 如果提供了`season`，则只搜索电视剧。
    - 如果只提供`episode`而没有`season`，则会返回错误。
    """
    if episode is not None and season is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="指定集数时必须同时提供季度信息。"
        )

    if not await manager.acquire_search_lock(api_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A search is already in progress for this API key. Please wait for it to complete."
        )
    try:
        try:
            episode_info = None
            if season is not None or episode is not None:
                episode_info = {"season": season, "episode": episode}

            results = await manager.search_all([keyword], episode_info=episode_info)
            
            # 新增：如果指定了季度，则假定是电视剧搜索并进行过滤
            if season is not None:
                results = [r for r in results if r.type == 'tv_series']
                logger.info(f"已将结果过滤为电视剧类型，剩余 {len(results)} 个结果。")

            search_id = str(uuid.uuid4())
            
            # Add index to each result
            indexed_results = [
                ControlSearchResultItem(**r.model_dump(), result_index=i)
                for i, r in enumerate(results)
            ]
            
            # Cache the full results with the search_id. Use a short TTL.
            await crud.set_cache(session, f"control_search_{search_id}", [r.model_dump() for r in results], 600) # 10 minutes TTL
            
            await crud.create_external_api_log(session, "N/A", "/search", 200, f"搜索 '{keyword}' 成功，找到 {len(results)} 个结果。Search ID: {search_id}")
            
            return ControlSearchResponse(searchId=search_id, results=indexed_results)
        except Exception as e:
            await crud.create_external_api_log(session, "N/A", "/search", 500, f"搜索 '{keyword}' 失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    finally:
        await manager.release_search_lock(api_key)

@router.post("/import/direct", status_code=status.HTTP_202_ACCEPTED, summary="直接导入搜索结果")
async def direct_import(
    payload: ControlDirectImportRequest,
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager),
    manager: ScraperManager = Depends(get_scraper_manager),
    api_key: str = Depends(verify_api_key),
):
    """通过 search_id 和 result_index 从缓存的搜索结果中选择一个进行导入。"""
    cache_key = f"control_search_{payload.searchId}"
    cached_results_raw = await crud.get_cache(session, cache_key)
    
    if cached_results_raw is None:
        raise HTTPException(status_code=404, detail="搜索会话已过期或无效，请重新搜索。")
    
    try:
        cached_results = [models.ProviderSearchInfo.model_validate(r) for r in cached_results_raw]
    except Exception:
        raise HTTPException(status_code=500, detail="无法解析缓存的搜索结果。")

    if not (0 <= payload.result_index < len(cached_results)):
        raise HTTPException(status_code=400, detail="提供的 result_index 无效。")
        
    item_to_import = cached_results[payload.result_index]

    task_title = f"外部API导入: {item_to_import.title} ({item_to_import.provider})"
    task_coro = lambda session, cb: tasks.generic_import_task(
        provider=item_to_import.provider, media_id=item_to_import.mediaId,
        anime_title=item_to_import.title, media_type=item_to_import.type,
        season=item_to_import.season, current_episode_index=item_to_import.currentEpisodeIndex,
        image_url=item_to_import.imageUrl, douban_id=payload.doubanId,
        tmdb_id=payload.tmdbId,
        imdb_id=payload.imdbId,
        tvdb_id=payload.tvdbId,
        bangumi_id=payload.bangumiId,
        progress_callback=cb, session=session, manager=manager, task_manager=task_manager
    )
    task_id, _ = await task_manager.submit_task(task_coro, task_title)
    return {"message": "导入任务已提交", "task_id": task_id}

@router.get("/episodes", response_model=List[models.ProviderEpisodeInfo], summary="获取搜索结果的分集列表")
async def get_episodes(
    searchId: str = Query(..., description="来自/search接口的searchId"),
    result_index: int = Query(..., ge=0, description="要获取分集的结果的索引"),
    session: AsyncSession = Depends(get_db_session),
    manager: ScraperManager = Depends(get_scraper_manager),
    api_key: str = Depends(verify_api_key),
):
    """通过 search_id 和 result_index 获取一个搜索结果的完整分集列表，用于编辑后导入。"""
    cache_key = f"control_search_{searchId}"
    cached_results_raw = await crud.get_cache(session, cache_key)
    
    if cached_results_raw is None:
        raise HTTPException(status_code=404, detail="搜索会话已过期或无效，请重新搜索。")
    
    try:
        cached_results = [models.ProviderSearchInfo.model_validate(r) for r in cached_results_raw]
    except Exception:
        raise HTTPException(status_code=500, detail="无法解析缓存的搜索结果。")

    if not (0 <= result_index < len(cached_results)):
        raise HTTPException(status_code=400, detail="提供的 result_index 无效。")
        
    item_to_fetch = cached_results[result_index]
    
    scraper = manager.get_scraper(item_to_fetch.provider)
    return await scraper.get_episodes(item_to_fetch.mediaId, db_media_type=item_to_fetch.type)

@router.post("/import/edited", status_code=status.HTTP_202_ACCEPTED, summary="导入编辑后的分集列表")
async def edited_import(
    payload: ControlEditedImportRequest,
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager),
    manager: ScraperManager = Depends(get_scraper_manager),
    api_key: str = Depends(verify_api_key),
):
    """通过 search_id 和 result_index 导入一个经过编辑的分集列表。"""
    cache_key = f"control_search_{payload.searchId}"
    cached_results_raw = await crud.get_cache(session, cache_key)
    
    if cached_results_raw is None:
        raise HTTPException(status_code=404, detail="搜索会话已过期或无效，请重新搜索。")
    
    try:
        cached_results = [models.ProviderSearchInfo.model_validate(r) for r in cached_results_raw]
    except Exception:
        raise HTTPException(status_code=500, detail="无法解析缓存的搜索结果。")

    if not (0 <= payload.result_index < len(cached_results)):
        raise HTTPException(status_code=400, detail="提供的 result_index 无效。")
        
    item_info = cached_results[payload.result_index]

    # Construct the full EditedImportRequest for the task
    task_payload = models.EditedImportRequest(
        provider=item_info.provider,
        mediaId=item_info.mediaId,
        animeTitle=payload.title or item_info.title,
        mediaType=item_info.type,
        season=item_info.season,
        imageUrl=item_info.imageUrl,
        doubanId=payload.doubanId,
        tmdbId=payload.tmdbId,
        imdbId=payload.imdbId,
        tvdbId=payload.tvdbId,
        bangumiId=payload.bangumiId,
        tmdbEpisodeGroupId=payload.tmdbEpisodeGroupId,
        episodes=payload.episodes
    )

    task_title = f"外部API编辑后导入: {task_payload.animeTitle} ({task_payload.provider})"
    task_coro = lambda session, cb: tasks.edited_import_task(
        request_data=task_payload, progress_callback=cb, session=session, manager=manager
    )
    task_id, _ = await task_manager.submit_task(task_coro, task_title)
    return {"message": "编辑后导入任务已提交", "task_id": task_id}

@router.post("/import/url", status_code=status.HTTP_202_ACCEPTED, summary="从URL导入整个作品")
async def url_import(
    payload: ControlUrlImportRequest,
    task_manager: TaskManager = Depends(get_task_manager),
    manager: ScraperManager = Depends(get_scraper_manager),
    api_key: str = Depends(verify_api_key),
):
    """从一个作品的URL（例如B站番剧主页）导入其所有分集的弹幕。"""
    scraper = manager.get_scraper_by_domain(payload.url)
    if not scraper:
        raise HTTPException(status_code=400, detail="不支持的URL或视频源。")

    # This is the new method we need to implement for each scraper
    media_info = await scraper.get_info_from_url(payload.url)
    if not media_info:
        raise HTTPException(status_code=404, detail="无法从提供的URL中获取有效的作品信息。")

    # Allow user to override scraped info
    final_title = payload.title or media_info.title
    final_season = payload.season if payload.season is not None else media_info.season

    task_title = f"外部API URL导入: {final_title} ({scraper.provider_name})"
    
    task_coro = lambda session, cb: tasks.generic_import_task(
        provider=scraper.provider_name,
        media_id=media_info.mediaId,
        anime_title=final_title,
        media_type=media_info.type,
        season=final_season,
        current_episode_index=None, # Import all episodes
        image_url=media_info.imageUrl,
        douban_id=payload.douban_id, tmdb_id=payload.tmdb_id, imdb_id=payload.imdb_id,
        tvdb_id=payload.tvdb_id, bangumi_id=payload.bangumi_id,
        progress_callback=cb, session=session, manager=manager, task_manager=task_manager
    )
    task_id, _ = await task_manager.submit_task(task_coro, task_title)
    return {"message": "URL导入任务已提交", "task_id": task_id}

# --- 媒体库管理 ---
library_router = APIRouter(prefix="/library", dependencies=[Depends(verify_api_key)])

@library_router.get("", response_model=List[models.LibraryAnimeInfo], summary="获取媒体库列表")
async def get_library(session: AsyncSession = Depends(get_db_session)):
    db_results = await crud.get_library_anime(session)
    return [models.LibraryAnimeInfo.model_validate(item) for item in db_results]

@library_router.get("/anime/{animeId}", response_model=ControlAnimeDetailsResponse, summary="获取作品详情")
async def get_anime_details(animeId: int, session: AsyncSession = Depends(get_db_session)):
    details = await crud.get_anime_full_details(session, animeId)
    if not details: raise HTTPException(404, "作品未找到")
    return ControlAnimeDetailsResponse.model_validate(details)

@library_router.get("/anime/{animeId}/sources", response_model=List[models.SourceInfo], summary="获取作品的所有数据源")
async def get_anime_sources(animeId: int, session: AsyncSession = Depends(get_db_session)):
    """获取指定作品关联的所有数据源列表。"""
    # First, check if the anime exists to provide a proper 404.
    anime_exists = await crud.get_anime_full_details(session, animeId)
    if not anime_exists:
        raise HTTPException(status_code=404, detail="作品未找到")
    return await crud.get_anime_sources(session, animeId)

@library_router.put("/anime/{animeId}", response_model=ControlActionResponse, summary="编辑作品信息")
async def edit_anime(animeId: int, payload: models.AnimeDetailUpdate, session: AsyncSession = Depends(get_db_session)):
    if not await crud.update_anime_details(session, animeId, payload):
        raise HTTPException(404, "作品未找到")
    return {"message": "作品信息更新成功。"}

@library_router.delete("/anime/{animeId}", status_code=202, summary="删除作品")
async def delete_anime(animeId: int, session: AsyncSession = Depends(get_db_session), task_manager: TaskManager = Depends(get_task_manager)):
    details = await crud.get_anime_full_details(session, animeId)
    if not details: raise HTTPException(404, "作品未找到")
    task_id, _ = await task_manager.submit_task(
        lambda s, cb: tasks.delete_anime_task(animeId, s, cb),
        f"外部API删除作品: {details['title']}"
    )
    return {"message": "删除作品任务已提交", "task_id": task_id}

@library_router.delete("/source/{sourceId}", status_code=202, summary="删除数据源")
async def delete_source(sourceId: int, session: AsyncSession = Depends(get_db_session), task_manager: TaskManager = Depends(get_task_manager)):
    info = await crud.get_anime_source_info(session, sourceId)
    if not info: raise HTTPException(404, "数据源未找到")
    task_id, _ = await task_manager.submit_task(
        lambda s, cb: tasks.delete_source_task(sourceId, s, cb),
        f"外部API删除源: {info['title']} ({info['provider_name']})"
    )
    return {"message": "删除源任务已提交", "task_id": task_id}

@library_router.put("/source/{sourceId}/favorite", response_model=ControlActionResponse, summary="精确标记数据源")
async def favorite_source(sourceId: int, session: AsyncSession = Depends(get_db_session)):
    new_status = await crud.toggle_source_favorite_status(session, sourceId)
    if new_status is None:
        raise HTTPException(404, "数据源未找到")
    message = "数据源已标记为精确。" if new_status else "数据源已取消精确标记。"
    return {"message": message}

@library_router.get("/source/{sourceid}/episodes", response_model=List[models.EpisodeDetail], summary="获取源的分集列表")
async def get_source_episodes(sourceid: int, session: AsyncSession = Depends(get_db_session)):
    return await crud.get_episodes_for_source(session, sourceid)

@library_router.put("/episode/{episodeid}", response_model=ControlActionResponse, summary="编辑分集信息")
async def edit_episode(episodeid: int, payload: models.EpisodeInfoUpdate, session: AsyncSession = Depends(get_db_session)):
    if not await crud.update_episode_info(session, episodeid, payload):
        raise HTTPException(404, "分集未找到")
    return {"message": "分集信息更新成功。"}

@library_router.post("/episode/{episodeId}/refresh", status_code=202, summary="刷新分集弹幕")
async def refresh_episode(episodeId: int, session: AsyncSession = Depends(get_db_session), task_manager: TaskManager = Depends(get_task_manager), manager: ScraperManager = Depends(get_scraper_manager)):
    info = await crud.get_episode_for_refresh(session, episodeId)
    if not info: raise HTTPException(404, "分集未找到")
    task_id, _ = await task_manager.submit_task(
        lambda s, cb: tasks.refresh_episode_task(episodeId, s, manager, cb),
        f"外部API刷新分集: {info['title']}"
    )
    return {"message": "刷新分集任务已提交", "task_id": task_id}

@library_router.delete("/episode/{episodeId}", status_code=202, summary="删除分集")
async def delete_episode(episodeId: int, session: AsyncSession = Depends(get_db_session), task_manager: TaskManager = Depends(get_task_manager)):
    info = await crud.get_episode_for_refresh(session, episodeId)
    if not info: raise HTTPException(404, "分集未找到")
    task_id, _ = await task_manager.submit_task(
        lambda s, cb: tasks.delete_episode_task(episodeId, s, cb),
        f"外部API删除分集: {info['title']}"
    )
    return {"message": "删除分集任务已提交", "task_id": task_id}

# --- 弹幕管理 ---
danmaku_router = APIRouter(prefix="/danmaku", dependencies=[Depends(verify_api_key)])

@danmaku_router.get("/{episodeId}", response_model=models.CommentResponse, summary="获取弹幕")
async def get_danmaku(episodeId: int, session: AsyncSession = Depends(get_db_session)):
    if not await crud.check_episode_exists(session, episodeId): raise HTTPException(404, "分集未找到")
    comments = await crud.fetch_comments(session, episodeId)
    return models.CommentResponse(count=len(comments), comments=[models.Comment.model_validate(c) for c in comments])

@danmaku_router.post("/{episodeId}", status_code=202, summary="覆盖弹幕")
async def overwrite_danmaku(episodeId: int, payload: models.DanmakuUpdateRequest, task_manager: TaskManager = Depends(get_task_manager)):
    async def overwrite_task(session: AsyncSession, cb: Callable):
        await cb(10, "清空中...")
        await crud.clear_episode_comments(session, episodeId)
        await cb(50, f"插入 {len(payload.comments)} 条新弹幕...")
        added = await crud.bulk_insert_comments(session, episodeId, [c.model_dump() for c in payload.comments])
        raise TaskSuccess(f"弹幕覆盖完成，新增 {added} 条。")
    task_id, _ = await task_manager.submit_task(overwrite_task, f"外部API覆盖弹幕 (分集ID: {episodeId})")
    return {"message": "弹幕覆盖任务已提交", "task_id": task_id}

# --- Token 管理 ---
token_router = APIRouter(prefix="/tokens", dependencies=[Depends(verify_api_key)])

@token_router.get("", response_model=List[models.ApiTokenInfo], summary="获取所有Token")
async def get_tokens(session: AsyncSession = Depends(get_db_session)):
    tokens = await crud.get_all_api_tokens(session)
    return [models.ApiTokenInfo.model_validate(t) for t in tokens]

@token_router.post("", response_model=models.ApiTokenInfo, status_code=201, summary="创建Token")
async def create_token(payload: models.ApiTokenCreate, session: AsyncSession = Depends(get_db_session)):
    token_str = secrets.token_urlsafe(16)
    try:
        token_id = await crud.create_api_token(session, payload.name, token_str, payload.validity_period)
        new_token = await crud.get_api_token_by_id(session, token_id)
        return models.ApiTokenInfo.model_validate(new_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

@token_router.get("/{tokenId}", response_model=models.ApiTokenInfo, summary="获取单个Token详情")
async def get_token(tokenId: int, session: AsyncSession = Depends(get_db_session)):
    token = await crud.get_api_token_by_id(session, tokenId)
    if not token: raise HTTPException(404, "Token未找到")
    return models.ApiTokenInfo.model_validate(token)

@token_router.get("/{tokenId}/logs", response_model=List[models.TokenAccessLog], summary="获取Token访问日志")
async def get_token_logs(tokenId: int, session: AsyncSession = Depends(get_db_session)):
    logs = await crud.get_token_access_logs(session, tokenId)
    return [models.TokenAccessLog.model_validate(log) for log in logs]

@token_router.put("/{tokenId}/toggle", response_model=ControlActionResponse, summary="启用/禁用Token")
async def toggle_token(tokenId: int, session: AsyncSession = Depends(get_db_session)):
    if not await crud.toggle_api_token(session, tokenId):
        raise HTTPException(404, "Token未找到")
    return {"message": "Token 状态已切换。"}

@token_router.delete("/{tokenId}", response_model=ControlActionResponse, summary="删除Token")
async def delete_token(tokenId: int, session: AsyncSession = Depends(get_db_session)):
    if not await crud.delete_api_token(session, tokenId):
        raise HTTPException(404, "Token未找到")
    return {"message": "Token 删除成功。"}

# --- 设置管理 ---
settings_router = APIRouter(prefix="/settings", dependencies=[Depends(verify_api_key)])

@settings_router.get("/danmaku-output", response_model=DanmakuOutputSettings, summary="获取弹幕输出设置")
async def get_danmaku_output_settings(session: AsyncSession = Depends(get_db_session)):
    limit = await crud.get_config_value(session, 'danmaku_output_limit_per_source', '-1')
    enabled = await crud.get_config_value(session, 'danmaku_aggregation_enabled', 'true')
    return DanmakuOutputSettings(limit_per_source=int(limit), aggregation_enabled=(enabled.lower() == 'true'))

@settings_router.put("/danmaku-output", response_model=ControlActionResponse, summary="更新弹幕输出设置")
async def update_danmaku_output_settings(payload: DanmakuOutputSettings, session: AsyncSession = Depends(get_db_session), config_manager: ConfigManager = Depends(get_config_manager)):
    await crud.update_config_value(session, 'danmaku_output_limit_per_source', str(payload.limit_per_source))
    await crud.update_config_value(session, 'danmaku_aggregation_enabled', str(payload.aggregation_enabled).lower())
    config_manager.invalidate('danmaku_output_limit_per_source')
    config_manager.invalidate('danmaku_aggregation_enabled')
    return {"message": "弹幕输出设置已更新。"}

# --- 注册所有子路由 ---
router.include_router(library_router)
router.include_router(danmaku_router)
router.include_router(token_router)
router.include_router(settings_router)
