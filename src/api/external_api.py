import logging
from typing import List, Optional, Dict, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, tasks
from ..database import get_db_session
from ..metadata_manager import MetadataSourceManager
from ..scraper_manager import ScraperManager
from ..task_manager import TaskManager, TaskSuccess

logger = logging.getLogger(__name__)
router = APIRouter()


def get_scraper_manager(request: Request) -> ScraperManager:
    """依赖项：从应用状态获取 Scraper 管理器"""
    return request.app.state.scraper_manager

def get_metadata_manager(request: Request) -> MetadataSourceManager:
    """依赖项：从应用状态获取元数据源管理器"""
    return request.app.state.metadata_manager

def get_task_manager(request: Request) -> TaskManager:
    """依赖项：从应用状态获取任务管理器"""
    return request.app.state.task_manager

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
    # 验证成功，暂不记录，在请求处理完成后记录
    yield


class ExternalImportRequest(BaseModel):
    keyword: Optional[str] = Field(None, description="用于搜索的关键词")
    tmdb_id: Optional[str] = Field(None, description="TMDB ID")
    tvdb_id: Optional[str] = Field(None, description="TVDB ID")
    bangumi_id: Optional[str] = Field(None, description="Bangumi ID")

    @model_validator(mode='after')
    def check_at_least_one_field(self):
        if not any([self.keyword, self.tmdb_id, self.tvdb_id, self.bangumi_id]):
            raise ValueError("必须提供 'keyword', 'tmdb_id', 'tvdb_id', 或 'bangumi_id' 中的至少一个。")
        return self


@router.post("/import", status_code=status.HTTP_202_ACCEPTED, summary="搜索并导入弹幕")
async def external_import(
    request: Request,
    payload: ExternalImportRequest,
    session: AsyncSession = Depends(get_db_session),
    manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    task_manager: TaskManager = Depends(get_task_manager),
    _: Any = Depends(verify_api_key),
):
    """
    通过关键词或外部ID（TMDB/TVDB/Bangumi）搜索媒体，并自动选择最佳匹配源进行全量导入。
    这是一个异步任务，会返回一个任务ID。
    """
    try:
        # 此处可以添加更复杂的逻辑，例如先通过ID获取标准标题，再用标题去搜索
        # 为简化，我们目前直接使用关键词或ID作为搜索依据
        search_term = payload.keyword or payload.tmdb_id or payload.tvdb_id or payload.bangumi_id
        
        # 查找最佳匹配
        provider, search_results = await manager.search_sequentially(search_term)
        if not provider or not search_results:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到任何匹配的媒体。")

        best_match = search_results[0]

        # 提交导入任务
        task_coro = lambda session, cb: tasks.generic_import_task(
            provider=best_match.provider, media_id=best_match.mediaId,
            anime_title=best_match.title, media_type=best_match.type,
            season=best_match.season, current_episode_index=None,
            image_url=best_match.imageUrl, douban_id=None,
            tmdb_id=payload.tmdb_id, imdb_id=None, tvdb_id=payload.tvdb_id,
            progress_callback=cb, session=session, manager=manager, task_manager=task_manager
        )
        task_title = f"外部API导入: {best_match.title} (源: {best_match.provider})"
        task_id, _ = await task_manager.submit_task(task_coro, task_title)
        
        message = f"已为 '{best_match.title}' 创建导入任务 (ID: {task_id})。"
        await crud.create_external_api_log(session, request.client.host, request.url.path, status.HTTP_202_ACCEPTED, message)
        return {"message": message, "task_id": task_id}

    except HTTPException as e:
        await crud.create_external_api_log(session, request.client.host, request.url.path, e.status_code, e.detail)
        raise e
    except Exception as e:
        await crud.create_external_api_log(session, request.client.host, request.url.path, status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/danmaku/{episode_id}", response_model=models.CommentResponse, summary="获取指定分集的弹幕")
async def get_danmaku(
    request: Request,
    episode_id: int,
    session: AsyncSession = Depends(get_db_session),
    _: Any = Depends(verify_api_key),
):
    """根据内部数据库的 episode_id 获取原始弹幕数据。"""
    try:
        if not await crud.check_episode_exists(session, episode_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分集未找到。")

        comments_data = await crud.fetch_comments(session, episode_id)
        comments = [models.Comment.model_validate(c) for c in comments_data]
        
        await crud.create_external_api_log(session, request.client.host, request.url.path, status.HTTP_200_OK, f"成功获取 {len(comments)} 条弹幕。")
        return models.CommentResponse(count=len(comments), comments=comments)
    except HTTPException as e:
        await crud.create_external_api_log(session, request.client.host, request.url.path, e.status_code, e.detail)
        raise e


class DanmakuUpdateRequest(BaseModel):
    comments: List[models.Comment]


@router.post("/danmaku/{episode_id}", status_code=status.HTTP_202_ACCEPTED, summary="覆盖指定分集的弹幕")
async def overwrite_danmaku(
    request: Request,
    episode_id: int,
    payload: DanmakuUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager),
    _: Any = Depends(verify_api_key),
):
    """
    完全覆盖指定分集的弹幕。此操作会先删除所有旧弹幕，然后插入新提供的弹幕。
    这是一个异步任务。
    """
    try:
        if not await crud.check_episode_exists(session, episode_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分集未找到。")

        # 将 Pydantic 模型转换为字典列表
        comments_to_insert = [c.model_dump() for c in payload.comments]

        async def overwrite_task(session: AsyncSession, progress_callback: Callable):
            await progress_callback(10, "正在清空旧弹幕...")
            await crud.clear_episode_comments(session, episode_id)
            await progress_callback(50, f"正在插入 {len(comments_to_insert)} 条新弹幕...")
            added_count = await crud.bulk_insert_comments(session, episode_id, comments_to_insert)
            await progress_callback(100, "完成。")
            raise TaskSuccess(f"弹幕覆盖完成，共新增 {added_count} 条弹幕。")

        task_title = f"外部API覆盖弹幕 (分集ID: {episode_id})"
        task_id, _ = await task_manager.submit_task(overwrite_task, task_title)
        
        message = f"已为分集 {episode_id} 创建弹幕覆盖任务 (ID: {task_id})。"
        await crud.create_external_api_log(session, request.client.host, request.url.path, status.HTTP_202_ACCEPTED, message)
        return {"message": message, "task_id": task_id}
    
    except HTTPException as e:
        await crud.create_external_api_log(session, request.client.host, request.url.path, e.status_code, e.detail)
        raise e
    except Exception as e:
        await crud.create_external_api_log(session, request.client.host, request.url.path, status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
