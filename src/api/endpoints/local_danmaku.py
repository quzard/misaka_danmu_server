"""
本地弹幕扫描相关API端点
"""
import logging
import os
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ... import models, security
from ...database import get_db_session
from ...crud import local_danmaku as crud
from ...local_danmaku_scanner import LocalDanmakuScanner
from ...task_manager import TaskManager
from ...config_manager import ConfigManager
from ..dependencies import get_config_manager


router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== Pydantic Models ====================

class LocalScanRequest(BaseModel):
    scanPath: str


class LocalItemUpdate(BaseModel):
    title: Optional[str] = None
    mediaType: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    year: Optional[int] = None
    tmdbId: Optional[str] = None
    tvdbId: Optional[str] = None
    imdbId: Optional[str] = None
    posterUrl: Optional[str] = None


class LocalItemsImportRequest(BaseModel):
    itemIds: Optional[List[int]] = None
    shows: Optional[List[Dict[str, Any]]] = None
    seasons: Optional[List[Dict[str, Any]]] = None


# ==================== API Endpoints ====================

@router.get("/local-scan/directories", summary="获取可用的扫描目录列表")
async def get_available_directories(
    config_manager: ConfigManager = Depends(get_config_manager),
    current_user: models.User = Depends(security.get_current_user)
):
    """
    获取可用的本地弹幕扫描目录列表

    从配置中读取预设的目录列表,并检查目录是否存在
    """
    try:
        # 从配置中获取预设目录列表
        directories_config = await config_manager.get("local_scan_directories", "[]")
        import json
        directories = json.loads(directories_config) if isinstance(directories_config, str) else directories_config

        # 如果配置为空,返回一些默认示例
        if not directories:
            directories = [
                "/mnt/media/danmaku",
                "/mnt/media/anime",
                "D:\\Media\\Danmaku",
                "D:\\Media\\Anime"
            ]

        # 检查目录是否存在并构建返回列表
        result = []
        for dir_path in directories:
            exists = os.path.exists(dir_path) and os.path.isdir(dir_path)
            result.append({
                "label": dir_path,
                "value": dir_path,
                "exists": exists
            })

        return {
            "directories": result
        }
    except Exception as e:
        logger.error(f"获取目录列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取目录列表失败: {str(e)}")


@router.post("/local-scan", status_code=202, summary="扫描本地弹幕文件")
async def scan_local_danmaku(
    payload: LocalScanRequest,
    request: Request,
    current_user: models.User = Depends(security.get_current_user)
):
    """
    扫描指定目录下的所有.xml弹幕文件

    扫描逻辑:
    1. 递归查找所有.xml文件
    2. 尝试从nfo文件读取元数据(TMDB ID等)
    3. 从文件名和目录结构推断标题、季集信息
    4. 存入local_danmaku_items表
    """
    try:
        # 从app.state获取session_factory
        session_factory = request.app.state.db_session_factory
        scanner = LocalDanmakuScanner(session_factory)

        # 执行扫描(同步执行,因为通常不会太慢)
        result = await scanner.scan_directory(payload.scanPath)

        logger.info(f"用户 '{current_user.username}' 扫描了本地目录: {payload.scanPath}, 结果: {result}")

        return {
            "message": f"扫描完成: 找到 {result['total']} 个文件, 成功 {result['success']} 个",
            "result": result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"扫描本地弹幕失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"扫描失败: {str(e)}")


@router.get("/local-items", response_model=Dict[str, Any], summary="获取本地弹幕项列表")
async def get_local_items(
    is_imported: Optional[bool] = Query(None),
    media_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """获取本地弹幕项列表,支持过滤和分页"""
    result = await crud.get_local_items(
        session,
        is_imported=is_imported,
        media_type=media_type,
        page=page,
        page_size=page_size
    )
    return result


@router.get("/local-works", response_model=Dict[str, Any], summary="获取本地作品列表(按作品分组)")
async def get_local_works(
    is_imported: Optional[bool] = Query(None),
    media_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """获取本地作品列表(电影+电视剧组),按作品计数"""
    result = await crud.get_local_works(
        session,
        is_imported=is_imported,
        media_type=media_type,
        page=page,
        page_size=page_size
    )
    return result


@router.get("/local-shows/{title}/seasons", response_model=List[Dict[str, Any]], summary="获取本地剧集的季度信息")
async def get_local_show_seasons(
    title: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """获取本地剧集的所有季度"""
    seasons = await crud.get_show_seasons(session, title)
    return seasons


@router.get("/local-shows/{title}/seasons/{season}/episodes", response_model=Dict[str, Any], summary="获取本地某一季的分集列表")
async def get_local_season_episodes(
    title: str,
    season: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """获取本地某一季的所有集"""
    result = await crud.get_season_episodes(
        session,
        title,
        season,
        page,
        page_size
    )
    return result


@router.put("/local-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="更新本地弹幕项")
async def update_local_item(
    item_id: int,
    payload: LocalItemUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """更新本地弹幕项的元数据"""
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的字段")

    success = await crud.update_local_item(session, item_id, **update_data)
    if not success:
        raise HTTPException(status_code=404, detail="本地弹幕项不存在")

    logger.info(f"用户 '{current_user.username}' 更新了本地弹幕项 {item_id}")
    return


@router.delete("/local-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除本地弹幕项")
async def delete_local_item(
    item_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """删除单个本地弹幕项"""
    success = await crud.delete_local_item(session, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="本地弹幕项不存在")

    logger.info(f"用户 '{current_user.username}' 删除了本地弹幕项 {item_id}")
    return


@router.post("/local-items/batch-delete", status_code=status.HTTP_204_NO_CONTENT, summary="批量删除本地弹幕项")
async def batch_delete_local_items(
    payload: Dict[str, List[int]],
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """批量删除本地弹幕项"""
    item_ids = payload.get("itemIds", [])
    if not item_ids:
        raise HTTPException(status_code=400, detail="没有要删除的项目")

    deleted_count = await crud.batch_delete_local_items(session, item_ids)
    logger.info(f"用户 '{current_user.username}' 批量删除了 {deleted_count} 个本地弹幕项")
    return


@router.post("/local-items/import", status_code=202, summary="导入本地弹幕")
async def import_local_items(
    payload: LocalItemsImportRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: models.User = Depends(security.get_current_user)
):
    """
    导入选中的本地弹幕项到弹幕库
    
    TODO: 实现导入逻辑
    1. 读取.xml文件内容
    2. 解析弹幕数据
    3. 创建anime/episode记录
    4. 批量插入comment记录
    5. 标记isImported=true
    """
    # 收集所有要导入的item_ids
    all_item_ids = set()

    if payload.itemIds:
        all_item_ids.update(payload.itemIds)

    if payload.shows:
        for show in payload.shows:
            episode_ids = await crud.get_episode_ids_by_show(session, show['title'])
            all_item_ids.update(episode_ids)

    if payload.seasons:
        for season in payload.seasons:
            episode_ids = await crud.get_episode_ids_by_season(
                session,
                season['title'],
                season['season']
            )
            all_item_ids.update(episode_ids)

    if not all_item_ids:
        return {"message": "没有要导入的项目"}

    # TODO: 实现实际的导入逻辑
    # 目前仅标记为已导入
    for item_id in all_item_ids:
        await crud.update_local_item(session, item_id, isImported=True)

    logger.info(f"用户 '{current_user.username}' 导入了 {len(all_item_ids)} 个本地弹幕项")

    return {
        "message": f"已提交导入任务,共 {len(all_item_ids)} 个项目",
        "count": len(all_item_ids)
    }

