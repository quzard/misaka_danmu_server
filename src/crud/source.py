"""
Source相关的CRUD操作
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, case, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from ..orm_models import Anime, AnimeSource, Episode, Scraper
from .. import models
from ..timezone import get_now

logger = logging.getLogger(__name__)


async def check_source_exists_by_media_id(session: AsyncSession, provider_name: str, media_id: str) -> bool:
    """检查具有给定提供商和媒体ID的源是否已存在。"""
    stmt = select(AnimeSource.id).where(
        AnimeSource.providerName == provider_name,
        AnimeSource.mediaId == media_id
    ).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_anime_id_by_source_media_id(session: AsyncSession, provider_name: str, media_id: str) -> Optional[int]:
    """通过数据源的provider和media_id获取对应的anime_id。"""
    stmt = select(AnimeSource.animeId).where(
        AnimeSource.providerName == provider_name,
        AnimeSource.mediaId == media_id
    ).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def link_source_to_anime(session: AsyncSession, anime_id: int, provider_name: str, media_id: str) -> int:
    """将一个外部数据源关联到一个番剧条目，如果关联已存在则直接返回其ID。"""
    # 修正：在链接源之前，确保该提供商在 scrapers 表中存在。
    # 这修复了当创建 'custom' 等非文件型源时，因 scrapers 表中缺少对应条目而导致后续查询失败的问题。
    # 这是比 LEFT JOIN 更根本的解决方案。
    scraper_entry = await session.get(Scraper, provider_name)
    if not scraper_entry:
        logger.info(f"提供商 '{provider_name}' 在 scrapers 表中不存在，将为其创建新条目。")
        max_order_stmt = select(func.max(Scraper.displayOrder))
        max_order = (await session.execute(max_order_stmt)).scalar_one_or_none() or 0
        new_scraper_entry = Scraper(
            providerName=provider_name,
            displayOrder=max_order + 1,
            isEnabled=True, # 自定义源默认启用
            useProxy=False
        )
        session.add(new_scraper_entry)
        await session.flush() # Flush to make it available within the transaction
    stmt = select(AnimeSource.id).where(
        AnimeSource.animeId == anime_id,
        AnimeSource.providerName == provider_name,
        AnimeSource.mediaId == media_id
    )
    result = await session.execute(stmt)
    existing_id = result.scalar_one_or_none()
    if existing_id:
        return existing_id

    # 如果源不存在，则创建一个新的，并为其分配一个持久的、唯一的顺序号
    # 查找此作品当前最大的 sourceOrder
    max_order_stmt = select(func.max(AnimeSource.sourceOrder)).where(AnimeSource.animeId == anime_id)
    max_order_result = await session.execute(max_order_stmt)
    current_max_order = max_order_result.scalar_one_or_none() or 0

    new_source = AnimeSource(
        animeId=anime_id,
        providerName=provider_name,
        mediaId=media_id,
        sourceOrder=current_max_order + 1,
        createdAt=get_now()
    )
    session.add(new_source)
    await session.flush() # 使用 flush 获取新ID，但不提交事务
    return new_source.id


async def update_source_media_id(session: AsyncSession, source_id: int, new_media_id: str):
    """更新指定源的 mediaId。"""
    stmt = update(AnimeSource).where(AnimeSource.id == source_id).values(mediaId=new_media_id)
    await session.execute(stmt)
    # 注意：这里不 commit，由调用方（任务）来决定何时提交事务


async def get_anime_source_info(session: AsyncSession, source_id: int) -> Optional[Dict[str, Any]]:
    stmt = (
        select(
            AnimeSource.id.label("sourceId"), AnimeSource.animeId.label("animeId"), AnimeSource.providerName.label("providerName"),
            AnimeSource.mediaId.label("mediaId"), AnimeSource.sourceOrder.label("sourceOrder"), Anime.year,
            Anime.title, Anime.type, Anime.season, AnimeMetadata.tmdbId.label("tmdbId"), AnimeMetadata.bangumiId.label("bangumiId")
        )
        .join(Anime, AnimeSource.animeId == Anime.id)
        .join(AnimeMetadata, Anime.id == AnimeMetadata.animeId, isouter=True)
        .where(AnimeSource.id == source_id)
    )
    result = await session.execute(stmt)
    row = result.mappings().first()
    return dict(row) if row else None


async def get_anime_sources(session: AsyncSession, anime_id: int) -> List[Dict[str, Any]]:
    """获取指定作品的所有数据源，并高效地计算每个源的分集数。"""
    # 步骤1: 创建一个子查询，用于高效地计算每个 source_id 对应的分集数量。
    # 这种方式比在主查询中直接 JOIN 和 COUNT 更快，尤其是在 episode 表很大的情况下。
    episode_count_subquery = (
        select(
            Episode.sourceId,
            func.count(Episode.id).label("episode_count")
        )
        .group_by(Episode.sourceId)
        .subquery()
    )

    # 步骤2: 构建主查询，LEFT JOIN 上面的子查询来获取分集数。
    stmt = (
        select(
            AnimeSource.id.label("sourceId"),
            AnimeSource.providerName.label("providerName"),
            AnimeSource.mediaId.label("mediaId"),
            AnimeSource.isFavorited.label("isFavorited"),
            AnimeSource.incrementalRefreshEnabled.label("incrementalRefreshEnabled"),
            AnimeSource.createdAt.label("createdAt"),
            # 使用 coalesce 确保即使没有分集的源也返回 0 而不是 NULL
            func.coalesce(episode_count_subquery.c.episode_count, 0).label("episodeCount")
        )
        .outerjoin(episode_count_subquery, AnimeSource.id == episode_count_subquery.c.sourceId)
        .where(AnimeSource.animeId == anime_id)
        .order_by(AnimeSource.createdAt)
    )
    result = await session.execute(stmt)
    return [dict(row) for row in result.mappings()]


async def get_episodes_for_source(session: AsyncSession, source_id: int, page: int = 1, page_size: int = 5000) -> Dict[str, Any]:
    """获取指定源的分集列表，支持分页。"""
    # 首先，获取总的分集数量，用于前端分页控件
    count_stmt = select(func.count(Episode.id)).where(Episode.sourceId == source_id)
    total_count = (await session.execute(count_stmt)).scalar_one()

    # 然后，根据分页参数查询特定页的数据
    # 修正：确保返回一个包含完整信息的字典列表，以修复UI中的TypeError
    offset = (page - 1) * page_size
    stmt = (
        select(
            Episode.id.label("episodeId"),
            Episode.title,
            Episode.episodeIndex.label("episodeIndex"),
            Episode.sourceUrl.label("sourceUrl"),
            Episode.fetchedAt.label("fetchedAt"),
            Episode.commentCount.label("commentCount")
        )
        .where(Episode.sourceId == source_id)
        .order_by(Episode.episodeIndex).offset(offset).limit(page_size)
    )
    result = await session.execute(stmt)
    episodes = [dict(row) for row in result.mappings()]
    
    return {"total": total_count, "episodes": episodes}


async def clear_source_data(session: AsyncSession, source_id: int):
    """Deletes all episodes and their danmaku files for a given source."""
    source = await session.get(AnimeSource, source_id)
    if not source:
        return
    
    # 修正：逐个删除文件，而不是删除一个不存在的目录，以提高健壮性
    episodes_to_delete_res = await session.execute(
        select(Episode.danmakuFilePath).where(Episode.sourceId == source_id)
    )
    for file_path_str in episodes_to_delete_res.scalars().all():
        if fs_path := _get_fs_path_from_web_path(file_path_str):
            if fs_path.is_file():
                fs_path.unlink(missing_ok=True)

    await session.execute(delete(Episode).where(Episode.sourceId == source_id))
    await session.commit()


async def delete_anime_source(session: AsyncSession, source_id: int) -> bool:
    source = await session.get(AnimeSource, source_id)
    if source:
        # 修正：逐个删除文件，而不是删除整个目录，以提高健壮性并与 tasks.py 保持一致
        episodes_to_delete_res = await session.execute(
            select(Episode.danmakuFilePath).where(Episode.sourceId == source_id)
        )
        for file_path_str in episodes_to_delete_res.scalars().all():
            if fs_path := _get_fs_path_from_web_path(file_path_str):
                if fs_path.is_file():
                    fs_path.unlink(missing_ok=True)

        await session.delete(source)
        await session.commit()
        return True
    return False


async def toggle_source_favorite_status(session: AsyncSession, source_id: int) -> Optional[bool]:
    """
    Toggles the favorite status of a source.
    Returns the new favorite status (True/False) on success, or None if not found.
    """
    source = await session.get(AnimeSource, source_id)
    if not source:
        return None

    # Toggle the target source
    source.isFavorited = not source.isFavorited
    
    # If it was favorited, unfavorite all others for the same anime
    if source.isFavorited:
        stmt = (
            update(AnimeSource)
            .where(AnimeSource.animeId == source.animeId, AnimeSource.id != source_id)
            .values(isFavorited=False)
        )
        await session.execute(stmt)
    
    await session.commit()
    return source.isFavorited


async def toggle_source_incremental_refresh(session: AsyncSession, source_id: int) -> bool:
    source = await session.get(AnimeSource, source_id)
    if not source:
        return False
    source.incrementalRefreshEnabled = not source.incrementalRefreshEnabled
    await session.commit()
    return True


async def increment_incremental_refresh_failures(session: AsyncSession, source_id: int) -> int:
    source = await session.get(AnimeSource, source_id)
    if not source:
        return 0
    source.incrementalRefreshFailures += 1
    await session.commit()
    return source.incrementalRefreshFailures


async def reset_incremental_refresh_failures(session: AsyncSession, source_id: int):
    await session.execute(update(AnimeSource).where(AnimeSource.id == source_id).values(incrementalRefreshFailures=0))
    await session.commit()


async def disable_incremental_refresh(session: AsyncSession, source_id: int) -> bool:
    result = await session.execute(update(AnimeSource).where(AnimeSource.id == source_id).values(incrementalRefreshEnabled=False))
    await session.commit()
    return result.rowcount > 0

# --- OAuth State Management ---


async def get_sources_with_incremental_refresh_enabled(session: AsyncSession) -> List[int]:
    stmt = select(AnimeSource.id).where(AnimeSource.incrementalRefreshEnabled == True)
    result = await session.execute(stmt)
    return result.scalars().all()

# --- Scheduled Tasks ---


async def _assign_source_order_if_missing(session: AsyncSession, anime_id: int, source_id: int) -> int:
    """一个辅助函数，用于为没有 sourceOrder 的旧记录分配一个新的、持久的序号。"""
    async with session.begin_nested(): # 使用嵌套事务确保操作的原子性
        max_order_stmt = select(func.max(AnimeSource.sourceOrder)).where(AnimeSource.animeId == anime_id)
        max_order_res = await session.execute(max_order_stmt)
        current_max_order = max_order_res.scalar_one_or_none() or 0
        new_order = current_max_order + 1
        
        await session.execute(update(AnimeSource).where(AnimeSource.id == source_id).values(sourceOrder=new_order))
        return new_order

