"""
AnimeGroup 分组相关 CRUD 操作
"""

import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from ..orm_models import AnimeGroup, Anime

logger = logging.getLogger(__name__)


async def get_all_groups(session: AsyncSession) -> List[Dict[str, Any]]:
    """获取所有分组，按 sortOrder 升序排列"""
    stmt = select(AnimeGroup).order_by(AnimeGroup.sortOrder, AnimeGroup.createdAt)
    result = await session.execute(stmt)
    groups = result.scalars().all()
    return [
        {
            "id": g.id,
            "name": g.name,
            "sortOrder": g.sortOrder,
            "createdAt": g.createdAt,
        }
        for g in groups
    ]


async def create_group(session: AsyncSession, name: str) -> Dict[str, Any]:
    """创建新分组"""
    # 计算当前最大 sortOrder
    max_order_stmt = select(AnimeGroup.sortOrder).order_by(AnimeGroup.sortOrder.desc()).limit(1)
    max_order = (await session.execute(max_order_stmt)).scalar()
    next_order = (max_order or 0) + 1

    group = AnimeGroup(name=name, sortOrder=next_order)
    session.add(group)
    await session.flush()
    await session.refresh(group)
    return {
        "id": group.id,
        "name": group.name,
        "sortOrder": group.sortOrder,
        "createdAt": group.createdAt,
    }


async def rename_group(session: AsyncSession, group_id: int, name: str) -> bool:
    """重命名分组，返回是否成功"""
    stmt = (
        update(AnimeGroup)
        .where(AnimeGroup.id == group_id)
        .values(name=name)
    )
    result = await session.execute(stmt)
    return result.rowcount > 0


async def delete_group(session: AsyncSession, group_id: int) -> bool:
    """
    删除分组。
    由于 FK 设置了 ON DELETE SET NULL，
    删除后关联的 Anime.groupId 自动置为 null。
    """
    stmt = delete(AnimeGroup).where(AnimeGroup.id == group_id)
    result = await session.execute(stmt)
    return result.rowcount > 0


async def set_anime_group(
    session: AsyncSession,
    anime_id: int,
    group_id: Optional[int],
) -> bool:
    """
    设置或清除条目的分组。
    group_id=None 时表示从分组中移除（ungrouped）。
    """
    stmt = (
        update(Anime)
        .where(Anime.id == anime_id)
        .values(groupId=group_id)
    )
    result = await session.execute(stmt)
    return result.rowcount > 0


async def reorder_groups(session: AsyncSession, group_ids: List[int]) -> bool:
    """
    批量更新分组排序。
    group_ids 为前端传来的有序列表，index 即为新的 sortOrder。
    """
    for order, group_id in enumerate(group_ids):
        stmt = (
            update(AnimeGroup)
            .where(AnimeGroup.id == group_id)
            .values(sortOrder=order)
        )
        await session.execute(stmt)
    return True


async def get_group_by_id(session: AsyncSession, group_id: int) -> Optional[Dict[str, Any]]:
    """按 ID 获取分组"""
    stmt = select(AnimeGroup).where(AnimeGroup.id == group_id)
    result = await session.execute(stmt)
    group = result.scalar_one_or_none()
    if group is None:
        return None
    return {
        "id": group.id,
        "name": group.name,
        "sortOrder": group.sortOrder,
        "createdAt": group.createdAt,
    }

