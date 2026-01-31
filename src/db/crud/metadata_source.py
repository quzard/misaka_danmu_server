"""
元数据源(Metadata Source)相关的CRUD操作
"""

import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from ..orm_models import MetadataSource
from .. import models

logger = logging.getLogger(__name__)


async def sync_metadata_sources_to_db(session: AsyncSession, provider_names: List[str]):
    """同步元数据源到数据库(仅添加新的,不删除旧的)"""
    if not provider_names:
        return

    existing_stmt = select(MetadataSource.providerName)
    existing_providers = set((await session.execute(existing_stmt)).scalars().all())

    new_providers = [name for name in provider_names if name not in existing_providers]
    if not new_providers:
        return

    max_order_stmt = select(func.max(MetadataSource.displayOrder))
    max_order = (await session.execute(max_order_stmt)).scalar_one_or_none() or 0

    session.add_all([
        MetadataSource(
            providerName=name,
            displayOrder=max_order + i + 1,
            isAuxSearchEnabled=(name == 'tmdb'),
            useProxy=True
        )
        for i, name in enumerate(new_providers)
    ])
    await session.commit()


async def get_all_metadata_source_settings(session: AsyncSession) -> List[Dict[str, Any]]:
    """获取所有元数据源的设置"""
    stmt = select(MetadataSource).order_by(MetadataSource.displayOrder)
    result = await session.execute(stmt)
    return [
        {
            "providerName": s.providerName,
            "isEnabled": s.isEnabled,
            "isAuxSearchEnabled": s.isAuxSearchEnabled,
            "displayOrder": s.displayOrder,
            "useProxy": s.useProxy,
            "isFailoverEnabled": s.isFailoverEnabled,
            "logRawResponses": s.logRawResponses
        }
        for s in result.scalars()
    ]


async def get_metadata_source_setting_by_name(
    session: AsyncSession,
    provider_name: str
) -> Optional[Dict[str, Any]]:
    """获取单个元数据源的设置"""
    source = await session.get(MetadataSource, provider_name)
    if source:
        return {
            "useProxy": source.useProxy,
            "logRawResponses": source.logRawResponses
        }
    return None


async def update_metadata_sources_settings(
    session: AsyncSession,
    settings: List['models.MetadataSourceSettingUpdate']
):
    """批量更新元数据源设置"""
    for s in settings:
        is_aux_enabled = True if s.providerName == 'tmdb' else s.isAuxSearchEnabled
        await session.execute(
            update(MetadataSource)
            .where(MetadataSource.providerName == s.providerName)
            .values(isAuxSearchEnabled=is_aux_enabled, displayOrder=s.displayOrder)
        )
    await session.commit()


async def update_metadata_source_specific_settings(
    session: AsyncSession,
    provider_name: str,
    settings: Dict[str, Any]
):
    """更新单个元数据源的特定设置(如 logRawResponses)"""
    await session.execute(
        update(MetadataSource)
        .where(MetadataSource.providerName == provider_name)
        .values(**settings)
    )


async def get_enabled_aux_metadata_sources(session: AsyncSession) -> List[Dict[str, Any]]:
    """获取所有已启用辅助搜索的元数据源"""
    stmt = (
        select(MetadataSource)
        .where(MetadataSource.isAuxSearchEnabled == True)
        .order_by(MetadataSource.displayOrder)
    )
    result = await session.execute(stmt)
    return [
        {
            "providerName": s.providerName,
            "isEnabled": s.isEnabled,
            "isAuxSearchEnabled": s.isAuxSearchEnabled,
            "displayOrder": s.displayOrder,
            "useProxy": s.useProxy,
            "isFailoverEnabled": s.isFailoverEnabled
        }
        for s in result.scalars()
    ]


async def get_enabled_failover_sources(session: AsyncSession) -> List[Dict[str, Any]]:
    """获取所有已启用故障转移的元数据源"""
    stmt = (
        select(MetadataSource)
        .where(MetadataSource.isFailoverEnabled == True)
        .order_by(MetadataSource.displayOrder)
    )
    result = await session.execute(stmt)
    return [
        {
            "providerName": s.providerName,
            "isEnabled": s.isEnabled,
            "displayOrder": s.displayOrder,
            "useProxy": s.useProxy
        }
        for s in result.scalars()
    ]

