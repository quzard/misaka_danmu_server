"""
搜索源(Scraper)相关的CRUD操作
"""

import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func

from ..orm_models import Scraper
from .. import models

logger = logging.getLogger(__name__)


async def sync_scrapers_to_db(session: AsyncSession, provider_names: List[str]):
    """同步搜索源到数据库(仅添加新的,不删除旧的)"""
    if not provider_names:
        return

    existing_stmt = select(Scraper.providerName)
    existing_providers = set((await session.execute(existing_stmt)).scalars().all())

    new_providers = [name for name in provider_names if name not in existing_providers]
    if not new_providers:
        return

    max_order_stmt = select(func.max(Scraper.displayOrder))
    max_order = (await session.execute(max_order_stmt)).scalar_one_or_none() or 0

    session.add_all([
        Scraper(providerName=name, displayOrder=max_order + i + 1, useProxy=False)
        for i, name in enumerate(new_providers)
    ])
    await session.commit()


async def get_scraper_setting_by_name(session: AsyncSession, provider_name: str) -> Optional[Dict[str, Any]]:
    """获取单个搜索源的设置"""
    scraper = await session.get(Scraper, provider_name)
    if scraper:
        return {
            "providerName": scraper.providerName,
            "isEnabled": scraper.isEnabled,
            "displayOrder": scraper.displayOrder,
            "useProxy": scraper.useProxy
        }
    return None


async def get_all_scraper_settings(session: AsyncSession) -> List[Dict[str, Any]]:
    """获取所有搜索源的设置"""
    stmt = select(Scraper).order_by(Scraper.displayOrder)
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


async def update_scraper_proxy(session: AsyncSession, provider_name: str, use_proxy: bool) -> bool:
    """更新单个搜索源的代理设置"""
    stmt = update(Scraper).where(Scraper.providerName == provider_name).values(useProxy=use_proxy)
    result = await session.execute(stmt)
    return result.rowcount > 0


async def update_scrapers_settings(session: AsyncSession, settings: List[models.ScraperSetting]):
    """批量更新搜索源设置"""
    for s in settings:
        await session.execute(
            update(Scraper)
            .where(Scraper.providerName == s.providerName)
            .values(isEnabled=s.isEnabled, displayOrder=s.displayOrder, useProxy=s.useProxy)
        )
    await session.commit()


async def remove_stale_scrapers(session: AsyncSession, discovered_providers: List[str]):
    """删除不再存在的搜索源"""
    if not discovered_providers:
        logger.warning("发现的搜索源列表为空,跳过清理过时源的操作。")
        return
    stmt = delete(Scraper).where(Scraper.providerName.notin_(discovered_providers))
    await session.execute(stmt)
    await session.commit()

