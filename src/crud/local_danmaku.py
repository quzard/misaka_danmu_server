"""
本地弹幕扫描相关的数据库操作
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, func, and_, or_
from sqlalchemy.orm import selectinload

from ..orm_models import LocalDanmakuItem


async def create_local_item(
    session: AsyncSession,
    file_path: str,
    title: str,
    media_type: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    year: Optional[int] = None,
    tmdb_id: Optional[str] = None,
    tvdb_id: Optional[str] = None,
    imdb_id: Optional[str] = None,
    poster_url: Optional[str] = None,
    nfo_path: Optional[str] = None
) -> LocalDanmakuItem:
    """创建本地弹幕项"""
    item = LocalDanmakuItem(
        filePath=file_path,
        title=title,
        mediaType=media_type,
        season=season,
        episode=episode,
        year=year,
        tmdbId=tmdb_id,
        tvdbId=tvdb_id,
        imdbId=imdb_id,
        posterUrl=poster_url,
        nfoPath=nfo_path
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def get_local_items(
    session: AsyncSession,
    is_imported: Optional[bool] = None,
    media_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 100
) -> Dict[str, Any]:
    """分页获取本地弹幕项"""
    # 构建查询条件
    conditions = []
    if is_imported is not None:
        conditions.append(LocalDanmakuItem.isImported == is_imported)
    if media_type:
        conditions.append(LocalDanmakuItem.mediaType == media_type)

    # 查询总数
    count_stmt = select(func.count()).select_from(LocalDanmakuItem)
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # 分页查询
    stmt = select(LocalDanmakuItem)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(LocalDanmakuItem.createdAt.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    items = result.scalars().all()

    return {
        "list": [
            {
                "id": item.id,
                "filePath": item.filePath,
                "title": item.title,
                "mediaType": item.mediaType,
                "season": item.season,
                "episode": item.episode,
                "year": item.year,
                "tmdbId": item.tmdbId,
                "tvdbId": item.tvdbId,
                "imdbId": item.imdbId,
                "posterUrl": item.posterUrl,
                "nfoPath": item.nfoPath,
                "isImported": item.isImported,
                "createdAt": item.createdAt.isoformat() if item.createdAt else None,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


async def get_local_works(
    session: AsyncSession,
    is_imported: Optional[bool] = None,
    media_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 100
) -> Dict[str, Any]:
    """按作品分组获取本地弹幕项"""
    # 构建查询条件
    conditions = []
    if is_imported is not None:
        conditions.append(LocalDanmakuItem.isImported == is_imported)
    if media_type:
        conditions.append(LocalDanmakuItem.mediaType == media_type)

    # 查询作品列表(按title分组,同时获取每组的ID列表)
    # 只按 title, mediaType, year 分组,其他字段取第一个非空值
    stmt = select(
        LocalDanmakuItem.title,
        LocalDanmakuItem.mediaType,
        LocalDanmakuItem.year,
        func.max(LocalDanmakuItem.tmdbId).label('tmdbId'),  # 取第一个非空值
        func.max(LocalDanmakuItem.tvdbId).label('tvdbId'),
        func.max(LocalDanmakuItem.imdbId).label('imdbId'),
        func.max(LocalDanmakuItem.posterUrl).label('posterUrl'),
        func.count(LocalDanmakuItem.id).label('itemCount'),
        func.max(LocalDanmakuItem.season).label('seasonCount'),
        func.max(LocalDanmakuItem.episode).label('episodeCount'),
        func.group_concat(LocalDanmakuItem.id).label('ids')  # 收集所有ID(MySQL使用GROUP_CONCAT)
    )
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.group_by(
        LocalDanmakuItem.title,
        LocalDanmakuItem.mediaType,
        LocalDanmakuItem.year
    )
    stmt = stmt.order_by(LocalDanmakuItem.title)

    # 分页
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    works = result.all()

    return {
        "list": [
            {
                "title": work.title,
                "type": "movie" if work.mediaType == "movie" else "tv_show",
                "mediaType": work.mediaType,
                "year": work.year,
                "tmdbId": work.tmdbId,
                "tvdbId": work.tvdbId,
                "imdbId": work.imdbId,
                "posterUrl": work.posterUrl,
                "itemCount": work.itemCount,
                "seasonCount": work.seasonCount if work.mediaType == "tv_series" else None,
                "episodeCount": work.episodeCount if work.mediaType == "tv_series" else None,
                "ids": [int(id_str) for id_str in work.ids.split(',')] if work.ids else [],  # 将逗号分隔的字符串转为整数数组
            }
            for work in works
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


async def get_show_seasons(
    session: AsyncSession,
    title: str
) -> List[Dict[str, Any]]:
    """获取剧集的季度信息"""
    stmt = select(
        LocalDanmakuItem.season,
        LocalDanmakuItem.year,
        LocalDanmakuItem.posterUrl,
        func.count(LocalDanmakuItem.id).label('episodeCount'),
        func.group_concat(LocalDanmakuItem.id).label('ids')  # 收集所有ID(MySQL使用GROUP_CONCAT)
    ).where(
        and_(
            LocalDanmakuItem.title == title,
            LocalDanmakuItem.mediaType == "tv_series",
            LocalDanmakuItem.season.isnot(None)
        )
    ).group_by(
        LocalDanmakuItem.season,
        LocalDanmakuItem.year,
        LocalDanmakuItem.posterUrl
    ).order_by(LocalDanmakuItem.season)

    result = await session.execute(stmt)
    seasons = result.all()

    return [
        {
            "season": s.season,
            "year": s.year,
            "posterUrl": s.posterUrl,
            "episodeCount": s.episodeCount,
            "ids": [int(id_str) for id_str in s.ids.split(',')] if s.ids else []  # 将逗号分隔的字符串转为整数数组
        }
        for s in seasons
    ]


async def get_season_episodes(
    session: AsyncSession,
    title: str,
    season: int,
    page: int = 1,
    page_size: int = 100
) -> Dict[str, Any]:
    """获取某一季的分集列表"""
    # 查询总数
    count_stmt = select(func.count()).select_from(LocalDanmakuItem).where(
        and_(
            LocalDanmakuItem.title == title,
            LocalDanmakuItem.season == season
        )
    )
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # 分页查询
    stmt = select(LocalDanmakuItem).where(
        and_(
            LocalDanmakuItem.title == title,
            LocalDanmakuItem.season == season
        )
    ).order_by(LocalDanmakuItem.episode).offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    episodes = result.scalars().all()

    return {
        "list": [
            {
                "id": ep.id,
                "filePath": ep.filePath,
                "title": ep.title,
                "season": ep.season,
                "episode": ep.episode,
                "year": ep.year,
                "tmdbId": ep.tmdbId,
                "tvdbId": ep.tvdbId,
                "imdbId": ep.imdbId,
                "posterUrl": ep.posterUrl,
                "nfoPath": ep.nfoPath,
                "isImported": ep.isImported,
            }
            for ep in episodes
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


async def get_local_item_by_id(
    session: AsyncSession,
    item_id: int
) -> Optional[LocalDanmakuItem]:
    """根据ID获取本地弹幕项"""
    stmt = select(LocalDanmakuItem).where(LocalDanmakuItem.id == item_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_local_item(
    session: AsyncSession,
    item_id: int,
    **kwargs
) -> bool:
    """更新本地弹幕项"""
    stmt = update(LocalDanmakuItem).where(LocalDanmakuItem.id == item_id).values(**kwargs)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0


async def delete_local_item(
    session: AsyncSession,
    item_id: int
) -> bool:
    """删除本地弹幕项"""
    stmt = delete(LocalDanmakuItem).where(LocalDanmakuItem.id == item_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0


async def batch_delete_local_items(
    session: AsyncSession,
    item_ids: List[int]
) -> int:
    """批量删除本地弹幕项(根据ID)"""
    stmt = delete(LocalDanmakuItem).where(LocalDanmakuItem.id.in_(item_ids))
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


async def delete_local_items_by_title(
    session: AsyncSession,
    title: str,
    media_type: str
) -> int:
    """根据标题和类型删除本地弹幕项"""
    stmt = delete(LocalDanmakuItem).where(
        and_(
            LocalDanmakuItem.title == title,
            LocalDanmakuItem.mediaType == media_type
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


async def delete_local_items_by_season(
    session: AsyncSession,
    title: str,
    season: int
) -> int:
    """根据标题和季度删除本地弹幕项"""
    stmt = delete(LocalDanmakuItem).where(
        and_(
            LocalDanmakuItem.title == title,
            LocalDanmakuItem.season == season
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


async def clear_all_local_items(session: AsyncSession) -> int:
    """清空所有本地弹幕项"""
    stmt = delete(LocalDanmakuItem)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


async def get_episode_ids_by_show(
    session: AsyncSession,
    title: str
) -> List[int]:
    """获取剧集所有集的ID"""
    stmt = select(LocalDanmakuItem.id).where(
        and_(
            LocalDanmakuItem.title == title,
            LocalDanmakuItem.mediaType == "tv_series"
        )
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def get_episode_ids_by_season(
    session: AsyncSession,
    title: str,
    season: int
) -> List[int]:
    """获取某一季所有集的ID"""
    stmt = select(LocalDanmakuItem.id).where(
        and_(
            LocalDanmakuItem.title == title,
            LocalDanmakuItem.season == season
        )
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]

