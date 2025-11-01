"""
媒体服务器(Media Server)相关的API端点
"""

import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ... import crud, models, security
from ...database import get_db_session
from ...task_manager import TaskManager
from ... import tasks
from ..dependencies import get_task_manager

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== Pydantic Models ====================

class MediaServerCreate(BaseModel):
    name: str
    providerName: str
    url: str
    apiToken: str
    isEnabled: bool = True
    selectedLibraries: List[str] = []
    filterRules: Dict[str, Any] = {}


class MediaServerUpdate(BaseModel):
    name: Optional[str] = None
    providerName: Optional[str] = None
    url: Optional[str] = None
    apiToken: Optional[str] = None
    isEnabled: Optional[bool] = None
    selectedLibraries: Optional[List[str]] = None
    filterRules: Optional[Dict[str, Any]] = None


class MediaServerResponse(BaseModel):
    id: int
    name: str
    providerName: str
    url: str
    apiToken: str
    isEnabled: bool
    selectedLibraries: List[str]
    filterRules: Dict[str, Any]
    createdAt: datetime
    updatedAt: datetime


class MediaServerTestResponse(BaseModel):
    success: bool
    message: str
    serverInfo: Optional[Dict[str, Any]] = None


class MediaLibraryInfo(BaseModel):
    id: str
    name: str
    type: str


class MediaItemResponse(BaseModel):
    id: int
    serverId: int
    mediaId: str
    libraryId: Optional[str]
    title: str
    mediaType: str
    season: Optional[int]
    episode: Optional[int]
    year: Optional[int]
    tmdbId: Optional[str]
    tvdbId: Optional[str]
    imdbId: Optional[str]
    posterUrl: Optional[str]
    isImported: bool
    createdAt: datetime


class MediaItemUpdate(BaseModel):
    title: Optional[str] = None
    mediaType: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    year: Optional[int] = None
    tmdbId: Optional[str] = None
    tvdbId: Optional[str] = None
    imdbId: Optional[str] = None
    posterUrl: Optional[str] = None


class MediaItemsImportRequest(BaseModel):
    itemIds: List[int]


class MediaServerScanRequest(BaseModel):
    """媒体服务器扫描请求"""
    library_ids: Optional[List[str]] = None


# ==================== Media Server Endpoints ====================

@router.get("/media-servers", response_model=List[MediaServerResponse], summary="获取所有媒体服务器")
async def get_media_servers(
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """获取所有媒体服务器配置"""
    servers = await crud.get_all_media_servers(session)
    return servers


@router.post("/media-servers", response_model=MediaServerResponse, status_code=201, summary="添加媒体服务器")
async def create_media_server(
    payload: MediaServerCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """创建新的媒体服务器配置"""
    server_id = await crud.create_media_server(
        session,
        name=payload.name,
        provider_name=payload.providerName,
        url=payload.url,
        api_token=payload.apiToken,
        is_enabled=payload.isEnabled,
        selected_libraries=payload.selectedLibraries,
        filter_rules=payload.filterRules
    )
    await session.commit()
    
    # 返回创建的服务器
    server = await crud.get_media_server_by_id(session, server_id)
    if not server:
        raise HTTPException(status_code=500, detail="创建媒体服务器后无法获取")
    
    return server


@router.put("/media-servers/{server_id}", response_model=MediaServerResponse, summary="更新媒体服务器")
async def update_media_server(
    server_id: int,
    payload: MediaServerUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """更新媒体服务器配置"""
    success = await crud.update_media_server(
        session,
        server_id,
        name=payload.name,
        provider_name=payload.providerName,
        url=payload.url,
        api_token=payload.apiToken,
        is_enabled=payload.isEnabled,
        selected_libraries=payload.selectedLibraries,
        filter_rules=payload.filterRules
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="媒体服务器不存在")
    
    await session.commit()
    
    # 返回更新后的服务器
    server = await crud.get_media_server_by_id(session, server_id)
    if not server:
        raise HTTPException(status_code=500, detail="更新媒体服务器后无法获取")
    
    return server


@router.delete("/media-servers/{server_id}", status_code=204, summary="删除媒体服务器")
async def delete_media_server(
    server_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """删除媒体服务器配置(级联删除关联的媒体项)"""
    success = await crud.delete_media_server(session, server_id)
    if not success:
        raise HTTPException(status_code=404, detail="媒体服务器不存在")
    await session.commit()


@router.post("/media-servers/{server_id}/test", response_model=MediaServerTestResponse, summary="测试媒体服务器连接")
async def test_media_server_connection(
    server_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """测试媒体服务器连接"""
    from ...media_server_manager import get_media_server_manager
    manager = get_media_server_manager()

    try:
        server = manager.servers.get(server_id)
        if not server:
            raise HTTPException(status_code=404, detail="媒体服务器不存在")
        
        server_info = await server.test_connection()
        return MediaServerTestResponse(success=True, message="连接成功", serverInfo=server_info)
    except Exception as e:
        logger.error(f"测试媒体服务器连接失败: {e}", exc_info=True)
        return MediaServerTestResponse(success=False, message=str(e))


@router.get("/media-servers/{server_id}/libraries", response_model=List[MediaLibraryInfo], summary="获取媒体库列表")
async def get_media_server_libraries(
    server_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """获取媒体服务器的媒体库列表"""
    from ...media_server_manager import get_media_server_manager
    manager = get_media_server_manager()

    server = manager.servers.get(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="媒体服务器不存在")

    try:
        libraries = await server.get_libraries()
        return libraries
    except Exception as e:
        logger.error(f"获取媒体库列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取媒体库列表失败: {str(e)}")


@router.post("/media-servers/{server_id}/scan", status_code=202, summary="扫描媒体库")
async def scan_media_server_library(
    server_id: int,
    payload: MediaServerScanRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """扫描媒体服务器的媒体库"""
    from ...media_server_manager import get_media_server_manager
    from ... import crud as media_crud

    manager = get_media_server_manager()

    server_instance = manager.servers.get(server_id)
    if not server_instance:
        raise HTTPException(status_code=404, detail="媒体服务器不存在")

    # 从数据库获取服务器配置以获取名称
    server_config = await media_crud.get_media_server_by_id(session, server_id)
    server_name = server_config.get('name', f'服务器{server_id}') if server_config else f'服务器{server_id}'

    # 创建协程工厂函数
    def create_scan_task(s: AsyncSession, cb: Callable):
        return tasks.scan_media_server_library(
            server_id=server_id,
            library_ids=payload.library_ids,
            session=s,
            progress_callback=cb
        )

    # 提交扫描任务
    task_id, _ = await task_manager.submit_task(
        create_scan_task,
        title=f"扫描媒体服务器: {server_name}"
    )

    return {"message": "扫描任务已提交", "taskId": task_id}


# ==================== Media Item Endpoints ====================

@router.get("/media-items", response_model=Dict[str, Any], summary="获取媒体项列表")
async def get_media_items(
    server_id: Optional[int] = Query(None),
    is_imported: Optional[bool] = Query(None),
    media_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """获取媒体项列表,支持过滤和分页"""
    result = await crud.get_media_items(
        session,
        server_id=server_id,
        is_imported=is_imported,
        media_type=media_type,
        page=page,
        page_size=page_size
    )
    return result


@router.put("/media-items/{item_id}", response_model=MediaItemResponse, summary="更新媒体项")
async def update_media_item(
    item_id: int,
    payload: MediaItemUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """更新媒体项信息"""
    success = await crud.update_media_item(
        session,
        item_id,
        title=payload.title,
        media_type=payload.mediaType,
        season=payload.season,
        episode=payload.episode,
        year=payload.year,
        tmdb_id=payload.tmdbId,
        tvdb_id=payload.tvdbId,
        imdb_id=payload.imdbId,
        poster_url=payload.posterUrl
    )

    if not success:
        raise HTTPException(status_code=404, detail="媒体项不存在")

    await session.commit()

    # 返回更新后的媒体项
    result = await crud.get_media_items(session, page=1, page_size=1)
    items = result.get('items', [])
    if not items:
        raise HTTPException(status_code=500, detail="更新媒体项后无法获取")

    return items[0]


@router.delete("/media-items/{item_id}", status_code=204, summary="删除媒体项")
async def delete_media_item(
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """删除单个媒体项"""
    success = await crud.delete_media_item(session, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="媒体项不存在")
    await session.commit()


@router.post("/media-items/batch-delete", status_code=200, summary="批量删除媒体项")
async def batch_delete_media_items(
    item_ids: List[int],
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """批量删除媒体项"""
    count = await crud.delete_media_items_batch(session, item_ids)
    await session.commit()
    return {"message": f"成功删除 {count} 个媒体项"}


@router.post("/media-items/import", status_code=202, summary="导入选中的媒体项")
async def import_media_items(
    payload: MediaItemsImportRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """导入选中的媒体项(触发webhook式搜索和弹幕下载)"""
    # 提交导入任务
    task_id = await task_manager.submit_task(
        tasks.import_media_items,
        item_ids=payload.itemIds,
        task_name=f"导入媒体项: {len(payload.itemIds)}个"
    )

    return {"message": "媒体项导入任务已提交", "taskId": task_id}

