"""
元数据源(Metadata Source)相关的API端点
"""

import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body, status
from pydantic import BaseModel

from src.db import models
from src import security
from src.services import MetadataSourceManager
from src.api.dependencies import get_metadata_manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/metadata-sources", response_model=List[models.MetadataSourceStatusResponse], summary="获取所有元数据源的设置")
async def get_metadata_source_settings(
    current_user: models.User = Depends(security.get_current_user),
    manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """获取所有元数据源及其当前状态(配置、连接性等)"""
    return await manager.get_sources_with_status()


@router.put("/metadata-sources", status_code=status.HTTP_204_NO_CONTENT, summary="更新元数据源的设置")
async def update_metadata_source_settings(
    settings: List[models.MetadataSourceSettingUpdate],
    current_user: models.User = Depends(security.get_current_user),
    manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """批量更新元数据源的启用状态、辅助搜索状态和显示顺序"""
    await manager.update_source_settings(settings)
    logger.info(f"用户 '{current_user.username}' 更新了元数据源设置,已重新加载。")


@router.get("/metadata-sources/{providerName}/config", response_model=Dict[str, Any], summary="获取指定元数据源的配置")
async def get_metadata_source_config(
    providerName: str,
    current_user: models.User = Depends(security.get_current_user),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """获取单个元数据源的详细配置"""
    try:
        return await metadata_manager.getProviderConfig(providerName)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("/metadata-sources/{providerName}/config", status_code=status.HTTP_204_NO_CONTENT, summary="更新指定元数据源的配置")
async def update_metadata_source_config(
    providerName: str,
    payload: Dict[str, Any],
    current_user: models.User = Depends(security.get_current_user),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """更新指定元数据源的配置"""
    try:
        await metadata_manager.updateProviderConfig(providerName, payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"更新元数据源 '{providerName}' 配置时发生未知错误: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新配置时发生内部错误。")


@router.get("/metadata/{provider}/search", response_model=List[models.MetadataDetailsResponse], summary="从元数据源搜索")
async def search_metadata(
    provider: str,
    keyword: str,
    mediaType: Optional[str] = Query(None),
    current_user: models.User = Depends(security.get_current_user),
    manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """从指定元数据源搜索内容"""
    return await manager.search(provider, keyword, current_user, mediaType=mediaType)


@router.get("/metadata/{provider}/details/{item_id}", response_model=models.MetadataDetailsResponse, summary="获取元数据详情")
async def get_metadata_details(
    provider: str,
    item_id: str,
    mediaType: Optional[str] = Query(None),
    current_user: models.User = Depends(security.get_current_user),
    manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """获取指定元数据源的详情"""
    details = await manager.get_details(provider, item_id, current_user, mediaType=mediaType)
    if not details:
        raise HTTPException(status_code=404, detail="未找到详情")
    return details


@router.get("/metadata/{provider}/details/{mediaType}/{item_id}", response_model=models.MetadataDetailsResponse, summary="获取元数据详情 (带媒体类型)", include_in_schema=False)
async def get_metadata_details_with_type(
    provider: str,
    mediaType: str,
    item_id: str,
    current_user: models.User = Depends(security.get_current_user),
    manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """
    一个兼容性路由,允许将 mediaType 作为路径的一部分
    """
    details = await manager.get_details(provider, item_id, current_user, mediaType=mediaType)
    if not details:
        raise HTTPException(status_code=404, detail="未找到详情")
    return details


@router.post("/metadata/{provider}/actions/{action_name}", summary="执行元数据源的自定义操作")
async def execute_metadata_action(
    provider: str,
    action_name: str,
    request: Request,
    payload: Optional[Dict[str, Any]] = Body(None),
    current_user: models.User = Depends(security.get_current_user),
    manager: MetadataSourceManager = Depends(get_metadata_manager)
):
    """执行指定元数据源的自定义操作"""
    try:
        return await manager.execute_action(provider, action_name, payload or {}, current_user, request=request)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

