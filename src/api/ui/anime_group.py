"""
AnimeGroup 分组相关 API 端点
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src import security
from src.db import crud, models, get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


# ---- Pydantic 请求/响应模型 ----

class GroupCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class GroupRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class GroupReorderRequest(BaseModel):
    groupIds: List[int] = Field(..., description="按新顺序排列的分组 ID 列表")


class SetAnimeGroupRequest(BaseModel):
    groupId: Optional[int] = Field(None, description="目标分组 ID，null 表示移出分组")


class GroupInfo(BaseModel):
    id: int
    name: str
    sortOrder: int

    class Config:
        from_attributes = True


# ---- API 端点 ----

@router.get("/anime/groups", response_model=List[GroupInfo], summary="获取所有分组")
async def list_groups(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """获取所有分组，按 sortOrder 排序。"""
    groups = await crud.get_all_groups(session)
    return groups


@router.post("/anime/groups", response_model=GroupInfo, status_code=201, summary="创建分组")
async def create_group(
    payload: GroupCreateRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """创建新分组。"""
    group = await crud.create_group(session, name=payload.name)
    await session.commit()
    return group


@router.patch("/anime/groups/reorder", summary="批量更新分组排序")
async def reorder_groups(
    payload: GroupReorderRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """按传入的 groupIds 顺序批量更新 sortOrder。"""
    await crud.reorder_groups(session, group_ids=payload.groupIds)
    await session.commit()
    return {"success": True}


@router.patch("/anime/groups/{group_id}", response_model=GroupInfo, summary="重命名分组")
async def rename_group(
    group_id: int,
    payload: GroupRenameRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """重命名指定分组。"""
    success = await crud.rename_group(session, group_id=group_id, name=payload.name)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    await session.commit()
    group = await crud.get_group_by_id(session, group_id)
    return group


@router.delete("/anime/groups/{group_id}", status_code=204, summary="删除分组")
async def delete_group(
    group_id: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """删除分组。关联条目的 groupId 自动置 null（ON DELETE SET NULL）。"""
    success = await crud.delete_group(session, group_id=group_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    await session.commit()


@router.patch("/anime/{anime_id}/group", summary="设置或清除条目的分组")
async def set_anime_group(
    anime_id: int,
    payload: SetAnimeGroupRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """将条目加入分组或移出分组（groupId=null）。"""
    success = await crud.set_anime_group(session, anime_id=anime_id, group_id=payload.groupId)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="条目不存在")
    await session.commit()
    return {"success": True, "animeId": anime_id, "groupId": payload.groupId}

