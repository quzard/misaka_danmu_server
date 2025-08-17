import logging
import secrets
from typing import List, Optional, Dict, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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

async def verify_api_key(
    request: Request,
    api_key: str = Query(..., description="外部访问API密钥"),
    session: AsyncSession = Depends(get_db_session),
):
    """依赖项：验证API密钥并记录请求。"""
    endpoint = request.url.path
    ip_address = request.client.host
    stored_key = await crud.get_config_value(session, "external_api_key", "")

    if not stored_key or api_key != stored_key:
        await crud.create_external_api_log(
            session, ip_address, endpoint, status.HTTP_401_UNAUTHORIZED, "无效的API密钥"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的API密钥"
        )
    # 验证成功，在请求处理完成后记录
    yield

# --- Pydantic 模型 ---

class ControlDirectImportRequest(BaseModel):
    provider: str
    media_id: str
    anime_title: str
    media_type: str
    season: int
    image_url: Optional[str] = None
    tmdb_id: Optional[str] = None
    tvdb_id: Optional[str] = None
    bangumi_id: Optional[str] = None

class ControlUrlImportRequest(BaseModel):
    url: str
    provider: str

class DanmakuOutputSettings(BaseModel):
    limit_per_source: int
    aggregation_enabled: bool

# --- API 路由 ---

@router.get("/search", response_model=List[models.ProviderSearchInfo], summary="搜索媒体")
async def search_media(
    keyword: str,
    session: AsyncSession = Depends(get_db_session),
    manager: ScraperManager = Depends(get_scraper_manager),
    _: Any = Depends(verify_api_key),
):
    """根据关键词从所有启用的源搜索媒体。"""
    try:
        results = await manager.search_all([keyword])
        await crud.create_external_api_log(session, "N/A", "/search", 200, f"搜索 '{keyword}' 成功，找到 {len(results)} 个结果。")
        return results
    except Exception as e:
        await crud.create_external_api_log(session, "N/A", "/search", 500, f"搜索 '{keyword}' 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import/direct", status_code=status.HTTP_202_ACCEPTED, summary="直接导入搜索结果")
async def direct_import(
    payload: ControlDirectImportRequest,
    task_manager: TaskManager = Depends(get_task_manager),
    manager: ScraperManager = Depends(get_scraper_manager),
    _: Any = Depends(verify_api_key),
):
    """直接导入一个指定的搜索结果。"""
    task_title = f"外部API导入: {payload.anime_title} ({payload.provider})"
    task_coro = lambda session, cb: tasks.generic_import_task(
        provider=payload.provider, media_id=payload.media_id,
        anime_title=payload.anime_title, media_type=payload.media_type,
        season=payload.season, current_episode_index=None,
        image_url=payload.image_url, douban_id=None,
        tmdb_id=payload.tmdb_id, imdb_id=None, tvdb_id=payload.tvdb_id,
        progress_callback=cb, session=session, manager=manager, task_manager=task_manager
    )
    task_id, _ = await task_manager.submit_task(task_coro, task_title)
    return {"message": "导入任务已提交", "task_id": task_id}

@router.get("/episodes", response_model=List[models.ProviderEpisodeInfo], summary="获取搜索结果的分集列表")
async def get_episodes(
    provider: str, media_id: str, media_type: str,
    manager: ScraperManager = Depends(get_scraper_manager),
    _: Any = Depends(verify_api_key),
):
    """获取一个搜索结果的完整分集列表，用于编辑后导入。"""
    scraper = manager.get_scraper(provider)
    return await scraper.get_episodes(media_id, db_media_type=media_type)

@router.post("/import/edited", status_code=status.HTTP_202_ACCEPTED, summary="导入编辑后的分集列表")
async def edited_import(
    payload: models.EditedImportRequest,
    task_manager: TaskManager = Depends(get_task_manager),
    manager: ScraperManager = Depends(get_scraper_manager),
    _: Any = Depends(verify_api_key),
):
    """导入一个经过编辑的分集列表。"""
    task_title = f"外部API编辑后导入: {payload.anime_title} ({payload.provider})"
    task_coro = lambda session, cb: tasks.edited_import_task(
        request_data=payload, progress_callback=cb, session=session, manager=manager
    )
    task_id, _ = await task_manager.submit_task(task_coro, task_title)
    return {"message": "编辑后导入任务已提交", "task_id": task_id}

@router.post("/import/url", status_code=status.HTTP_202_ACCEPTED, summary="从URL导入")
async def url_import(
    payload: ControlUrlImportRequest,
    task_manager: TaskManager = Depends(get_task_manager),
    manager: ScraperManager = Depends(get_scraper_manager),
    _: Any = Depends(verify_api_key),
):
    """从视频URL直接导入弹幕。"""
    scraper = manager.get_scraper_by_domain(payload.url)
    if not scraper:
        raise HTTPException(status_code=400, detail="不支持的URL或视频源。")
    
    task_title = f"外部API URL导入: {payload.url}"
    task_coro = lambda session, cb: tasks.manual_import_task(
        source_id=0, # This will be determined inside the task
        title="从URL导入", episode_index=1, url=payload.url, provider_name=scraper.provider_name,
        progress_callback=cb, session=session, manager=manager
    )
    task_id, _ = await task_manager.submit_task(task_coro, task_title)
    return {"message": "URL导入任务已提交", "task_id": task_id}

# --- 媒体库管理 ---
library_router = APIRouter(prefix="/library", dependencies=[Depends(verify_api_key)])

@library_router.get("", response_model=List[models.LibraryAnimeInfo], summary="获取媒体库列表")
async def get_library(session: AsyncSession = Depends(get_db_session)):
    db_results = await crud.get_library_anime(session)
    return [models.LibraryAnimeInfo.model_validate(item) for item in db_results]

@library_router.get("/anime/{anime_id}", response_model=models.AnimeFullDetails, summary="获取作品详情")
async def get_anime_details(anime_id: int, session: AsyncSession = Depends(get_db_session)):
    details = await crud.get_anime_full_details(session, anime_id)
    if not details: raise HTTPException(404, "作品未找到")
    return models.AnimeFullDetails.model_validate(details)

@library_router.put("/anime/{anime_id}", status_code=204, summary="编辑作品信息")
async def edit_anime(anime_id: int, payload: models.AnimeDetailUpdate, session: AsyncSession = Depends(get_db_session)):
    if not await crud.update_anime_details(session, anime_id, payload):
        raise HTTPException(404, "作品未找到")

@library_router.delete("/anime/{anime_id}", status_code=202, summary="删除作品")
async def delete_anime(anime_id: int, session: AsyncSession = Depends(get_db_session), task_manager: TaskManager = Depends(get_task_manager)):
    details = await crud.get_anime_full_details(session, anime_id)
    if not details: raise HTTPException(404, "作品未找到")
    task_id, _ = await task_manager.submit_task(
        lambda s, cb: tasks.delete_anime_task(anime_id, s, cb),
        f"外部API删除作品: {details['title']}"
    )
    return {"message": "删除作品任务已提交", "task_id": task_id}

@library_router.delete("/source/{source_id}", status_code=202, summary="删除数据源")
async def delete_source(source_id: int, session: AsyncSession = Depends(get_db_session), task_manager: TaskManager = Depends(get_task_manager)):
    info = await crud.get_anime_source_info(session, source_id)
    if not info: raise HTTPException(404, "数据源未找到")
    task_id, _ = await task_manager.submit_task(
        lambda s, cb: tasks.delete_source_task(source_id, s, cb),
        f"外部API删除源: {info['title']} ({info['provider_name']})"
    )
    return {"message": "删除源任务已提交", "task_id": task_id}

@library_router.put("/source/{source_id}/favorite", status_code=204, summary="精确标记数据源")
async def favorite_source(source_id: int, session: AsyncSession = Depends(get_db_session)):
    if not await crud.toggle_source_favorite_status(session, source_id):
        raise HTTPException(404, "数据源未找到")

@library_router.get("/source/{source_id}/episodes", response_model=List[models.EpisodeDetail], summary="获取源的分集列表")
async def get_source_episodes(source_id: int, session: AsyncSession = Depends(get_db_session)):
    return await crud.get_episodes_for_source(session, source_id)

@library_router.put("/episode/{episode_id}", status_code=204, summary="编辑分集信息")
async def edit_episode(episode_id: int, payload: models.EpisodeInfoUpdate, session: AsyncSession = Depends(get_db_session)):
    if not await crud.update_episode_info(session, episode_id, payload):
        raise HTTPException(404, "分集未找到")

@library_router.post("/episode/{episode_id}/refresh", status_code=202, summary="刷新分集弹幕")
async def refresh_episode(episode_id: int, session: AsyncSession = Depends(get_db_session), task_manager: TaskManager = Depends(get_task_manager), manager: ScraperManager = Depends(get_scraper_manager)):
    info = await crud.get_episode_for_refresh(session, episode_id)
    if not info: raise HTTPException(404, "分集未找到")
    task_id, _ = await task_manager.submit_task(
        lambda s, cb: tasks.refresh_episode_task(episode_id, s, manager, cb),
        f"外部API刷新分集: {info['title']}"
    )
    return {"message": "刷新分集任务已提交", "task_id": task_id}

@library_router.delete("/episode/{episode_id}", status_code=202, summary="删除分集")
async def delete_episode(episode_id: int, session: AsyncSession = Depends(get_db_session), task_manager: TaskManager = Depends(get_task_manager)):
    info = await crud.get_episode_for_refresh(session, episode_id)
    if not info: raise HTTPException(404, "分集未找到")
    task_id, _ = await task_manager.submit_task(
        lambda s, cb: tasks.delete_episode_task(episode_id, s, cb),
        f"外部API删除分集: {info['title']}"
    )
    return {"message": "删除分集任务已提交", "task_id": task_id}

# --- 弹幕管理 ---
danmaku_router = APIRouter(prefix="/danmaku", dependencies=[Depends(verify_api_key)])

@danmaku_router.get("/{episode_id}", response_model=models.CommentResponse, summary="获取弹幕")
async def get_danmaku(episode_id: int, session: AsyncSession = Depends(get_db_session)):
    if not await crud.check_episode_exists(session, episode_id): raise HTTPException(404, "分集未找到")
    comments = await crud.fetch_comments(session, episode_id)
    return models.CommentResponse(count=len(comments), comments=[models.Comment.model_validate(c) for c in comments])

@danmaku_router.post("/{episode_id}", status_code=202, summary="覆盖弹幕")
async def overwrite_danmaku(episode_id: int, payload: models.DanmakuUpdateRequest, task_manager: TaskManager = Depends(get_task_manager)):
    async def overwrite_task(session: AsyncSession, cb: Callable):
        await cb(10, "清空中...")
        await crud.clear_episode_comments(session, episode_id)
        await cb(50, f"插入 {len(payload.comments)} 条新弹幕...")
        added = await crud.bulk_insert_comments(session, episode_id, [c.model_dump() for c in payload.comments])
        raise TaskSuccess(f"弹幕覆盖完成，新增 {added} 条。")
    task_id, _ = await task_manager.submit_task(overwrite_task, f"外部API覆盖弹幕 (分集ID: {episode_id})")
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
    token_id = await crud.create_api_token(session, payload.name, token_str, payload.validity_period)
    new_token = await crud.get_api_token_by_id(session, token_id)
    return models.ApiTokenInfo.model_validate(new_token)

@token_router.get("/{token_id}", response_model=models.ApiTokenInfo, summary="获取单个Token详情")
async def get_token(token_id: int, session: AsyncSession = Depends(get_db_session)):
    token = await crud.get_api_token_by_id(session, token_id)
    if not token: raise HTTPException(404, "Token未找到")
    return models.ApiTokenInfo.model_validate(token)

@token_router.get("/{token_id}/logs", response_model=List[models.TokenAccessLog], summary="获取Token访问日志")
async def get_token_logs(token_id: int, session: AsyncSession = Depends(get_db_session)):
    logs = await crud.get_token_access_logs(session, token_id)
    return [models.TokenAccessLog.model_validate(log) for log in logs]

@token_router.put("/{token_id}/toggle", status_code=204, summary="启用/禁用Token")
async def toggle_token(token_id: int, session: AsyncSession = Depends(get_db_session)):
    if not await crud.toggle_api_token(session, token_id):
        raise HTTPException(404, "Token未找到")

@token_router.delete("/{token_id}", status_code=204, summary="删除Token")
async def delete_token(token_id: int, session: AsyncSession = Depends(get_db_session)):
    if not await crud.delete_api_token(session, token_id):
        raise HTTPException(404, "Token未找到")

# --- 设置管理 ---
settings_router = APIRouter(prefix="/settings", dependencies=[Depends(verify_api_key)])

@settings_router.get("/danmaku-output", response_model=DanmakuOutputSettings, summary="获取弹幕输出设置")
async def get_danmaku_output_settings(session: AsyncSession = Depends(get_db_session)):
    limit = await crud.get_config_value(session, 'danmaku_output_limit_per_source', '-1')
    enabled = await crud.get_config_value(session, 'danmaku_aggregation_enabled', 'true')
    return DanmakuOutputSettings(limit_per_source=int(limit), aggregation_enabled=(enabled.lower() == 'true'))

@settings_router.put("/danmaku-output", status_code=204, summary="更新弹幕输出设置")
async def update_danmaku_output_settings(payload: DanmakuOutputSettings, session: AsyncSession = Depends(get_db_session), config_manager: ConfigManager = Depends(get_config_manager)):
    await crud.update_config_value(session, 'danmaku_output_limit_per_source', str(payload.limit_per_source))
    await crud.update_config_value(session, 'danmaku_aggregation_enabled', str(payload.aggregation_enabled).lower())
    config_manager.invalidate('danmaku_output_limit_per_source')
    config_manager.invalidate('danmaku_aggregation_enabled')

# --- 注册所有子路由 ---
router.include_router(library_router)
router.include_router(danmaku_router)
router.include_router(token_router)
router.include_router(settings_router)
