"""
媒体服务器相关的CRUD操作
包括媒体服务器配置和媒体项管理
"""

import json
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func

from ..timezone import get_now
from .. import orm_models

logger = logging.getLogger(__name__)


# --- Media Server Configuration ---

async def get_all_media_servers(session: AsyncSession) -> List[Dict[str, Any]]:
    """获取所有媒体服务器配置"""
    stmt = select(orm_models.MediaServer).order_by(orm_models.MediaServer.createdAt)
    result = await session.execute(stmt)
    servers = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "providerName": s.providerName,
            "url": s.url,
            "apiToken": s.apiToken,
            "isEnabled": s.isEnabled,
            "selectedLibraries": json.loads(s.selectedLibraries) if s.selectedLibraries else [],
            "filterRules": json.loads(s.filterRules) if s.filterRules else {},
            "createdAt": s.createdAt,
            "updatedAt": s.updatedAt
        }
        for s in servers
    ]


async def get_media_server_by_id(session: AsyncSession, server_id: int) -> Optional[Dict[str, Any]]:
    """根据ID获取媒体服务器配置"""
    server = await session.get(orm_models.MediaServer, server_id)
    if not server:
        return None
    return {
        "id": server.id,
        "name": server.name,
        "providerName": server.providerName,
        "url": server.url,
        "apiToken": server.apiToken,
        "isEnabled": server.isEnabled,
        "selectedLibraries": json.loads(server.selectedLibraries) if server.selectedLibraries else [],
        "filterRules": json.loads(server.filterRules) if server.filterRules else {},
        "createdAt": server.createdAt,
        "updatedAt": server.updatedAt
    }


async def create_media_server(
    session: AsyncSession,
    name: str,
    provider_name: str,
    url: str,
    api_token: str,
    is_enabled: bool = True,
    selected_libraries: Optional[List[str]] = None,
    filter_rules: Optional[Dict[str, Any]] = None
) -> int:
    """创建新的媒体服务器配置"""
    new_server = orm_models.MediaServer(
        name=name,
        providerName=provider_name,
        url=url,
        apiToken=api_token,
        isEnabled=is_enabled,
        selectedLibraries=json.dumps(selected_libraries or []),
        filterRules=json.dumps(filter_rules or {}),
        createdAt=get_now(),
        updatedAt=get_now()
    )
    session.add(new_server)
    await session.flush()
    return new_server.id


async def update_media_server(
    session: AsyncSession,
    server_id: int,
    name: Optional[str] = None,
    provider_name: Optional[str] = None,
    url: Optional[str] = None,
    api_token: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    selected_libraries: Optional[List[str]] = None,
    filter_rules: Optional[Dict[str, Any]] = None
) -> bool:
    """更新媒体服务器配置"""
    server = await session.get(orm_models.MediaServer, server_id)
    if not server:
        return False

    if name is not None:
        server.name = name
    if provider_name is not None:
        server.providerName = provider_name
    if url is not None:
        server.url = url
    if api_token is not None:
        server.apiToken = api_token
    if is_enabled is not None:
        server.isEnabled = is_enabled
    if selected_libraries is not None:
        server.selectedLibraries = json.dumps(selected_libraries)
    if filter_rules is not None:
        server.filterRules = json.dumps(filter_rules)

    server.updatedAt = get_now()
    await session.flush()
    return True


async def delete_media_server(session: AsyncSession, server_id: int) -> bool:
    """删除媒体服务器配置(级联删除关联的媒体项)"""
    server = await session.get(orm_models.MediaServer, server_id)
    if not server:
        return False
    await session.delete(server)
    await session.flush()
    return True


# --- Media Items ---

async def get_media_items(
    session: AsyncSession,
    server_id: Optional[int] = None,
    is_imported: Optional[bool] = None,
    media_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 100
) -> Dict[str, Any]:
    """获取媒体项列表,支持过滤和分页"""
    stmt = select(orm_models.MediaItem)

    if server_id is not None:
        stmt = stmt.where(orm_models.MediaItem.serverId == server_id)
    if is_imported is not None:
        stmt = stmt.where(orm_models.MediaItem.isImported == is_imported)
    if media_type is not None:
        stmt = stmt.where(orm_models.MediaItem.mediaType == media_type)

    # 计算总数
    count_stmt = select(func.count()).select_from(stmt.alias("count_subquery"))
    total = (await session.execute(count_stmt)).scalar_one()

    # 分页查询
    stmt = stmt.order_by(orm_models.MediaItem.createdAt.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    items = result.scalars().all()

    return {
        "total": total,
        "list": [
            {
                "id": item.id,
                "serverId": item.serverId,
                "mediaId": item.mediaId,
                "libraryId": item.libraryId,
                "title": item.title,
                "mediaType": item.mediaType,
                "season": item.season,
                "episode": item.episode,
                "year": item.year,
                "tmdbId": item.tmdbId,
                "tvdbId": item.tvdbId,
                "imdbId": item.imdbId,
                "posterUrl": item.posterUrl,
                "isImported": item.isImported,
                "createdAt": item.createdAt,
                "updatedAt": item.updatedAt
            }
            for item in items
        ]
    }


async def get_media_works(
    session: AsyncSession,
    server_id: Optional[int] = None,
    is_imported: Optional[bool] = None,
    media_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 100
) -> Dict[str, Any]:
    """
    获取作品列表(电影+电视剧组),按作品计数
    - 电影: 直接返回
    - 电视剧: 按title分组,返回剧集组信息
    """
    works = []

    # 1. 获取电影
    if media_type is None or media_type == 'movie':
        movie_stmt = select(orm_models.MediaItem).where(orm_models.MediaItem.mediaType == 'movie')
        if server_id is not None:
            movie_stmt = movie_stmt.where(orm_models.MediaItem.serverId == server_id)
        if is_imported is not None:
            movie_stmt = movie_stmt.where(orm_models.MediaItem.isImported == is_imported)

        movie_stmt = movie_stmt.order_by(orm_models.MediaItem.createdAt.desc())
        movie_result = await session.execute(movie_stmt)
        movies = movie_result.scalars().all()

        for movie in movies:
            works.append({
                "type": "movie",
                "id": movie.id,
                "serverId": movie.serverId,
                "mediaId": movie.mediaId,
                "libraryId": movie.libraryId,
                "title": movie.title,
                "mediaType": "movie",
                "year": movie.year,
                "tmdbId": movie.tmdbId,
                "tvdbId": movie.tvdbId,
                "imdbId": movie.imdbId,
                "posterUrl": movie.posterUrl,
                "isImported": movie.isImported,
                "createdAt": movie.createdAt,
                "updatedAt": movie.updatedAt
            })

    # 2. 获取电视剧组(按title分组)
    if media_type is None or media_type == 'tv_series':
        tv_stmt = select(
            orm_models.MediaItem.title,
            orm_models.MediaItem.serverId,
            func.min(orm_models.MediaItem.year).label('year'),
            func.min(orm_models.MediaItem.tmdbId).label('tmdbId'),
            func.min(orm_models.MediaItem.tvdbId).label('tvdbId'),
            func.min(orm_models.MediaItem.imdbId).label('imdbId'),
            func.min(orm_models.MediaItem.posterUrl).label('posterUrl'),
            func.max(orm_models.MediaItem.createdAt).label('createdAt'),
            func.count(func.distinct(orm_models.MediaItem.season)).label('seasonCount'),
            func.count(orm_models.MediaItem.id).label('episodeCount')
        ).where(orm_models.MediaItem.mediaType == 'tv_series')

        if server_id is not None:
            tv_stmt = tv_stmt.where(orm_models.MediaItem.serverId == server_id)
        if is_imported is not None:
            tv_stmt = tv_stmt.where(orm_models.MediaItem.isImported == is_imported)

        tv_stmt = tv_stmt.group_by(orm_models.MediaItem.title, orm_models.MediaItem.serverId)
        tv_stmt = tv_stmt.order_by(func.max(orm_models.MediaItem.createdAt).desc())

        tv_result = await session.execute(tv_stmt)
        tv_shows = tv_result.all()

        for show in tv_shows:
            works.append({
                "type": "tv_show",
                "serverId": show.serverId,
                "title": show.title,
                "mediaType": "tv_show",
                "year": show.year,
                "tmdbId": show.tmdbId,
                "tvdbId": show.tvdbId,
                "imdbId": show.imdbId,
                "posterUrl": show.posterUrl,
                "createdAt": show.createdAt,
                "seasonCount": show.seasonCount,
                "episodeCount": show.episodeCount
            })

    # 3. 排序和分页
    works.sort(key=lambda x: x['createdAt'], reverse=True)
    total = len(works)
    start = (page - 1) * page_size
    end = start + page_size
    paginated_works = works[start:end]

    return {
        "total": total,
        "list": paginated_works
    }


async def get_show_seasons(
    session: AsyncSession,
    server_id: int,
    title: str
) -> List[Dict[str, Any]]:
    """获取某部剧集的所有季度信息"""
    stmt = select(
        orm_models.MediaItem.season,
        func.count(orm_models.MediaItem.id).label('episodeCount'),
        func.min(orm_models.MediaItem.year).label('year'),
        func.min(orm_models.MediaItem.posterUrl).label('posterUrl')
    ).where(
        orm_models.MediaItem.serverId == server_id,
        orm_models.MediaItem.title == title,
        orm_models.MediaItem.mediaType == 'tv_series'
    ).group_by(orm_models.MediaItem.season).order_by(orm_models.MediaItem.season)

    result = await session.execute(stmt)
    seasons = result.all()

    return [
        {
            "season": s.season,
            "episodeCount": s.episodeCount,
            "year": s.year,
            "posterUrl": s.posterUrl
        }
        for s in seasons
    ]


async def get_season_episodes(
    session: AsyncSession,
    server_id: int,
    title: str,
    season: int,
    page: int = 1,
    page_size: int = 100
) -> Dict[str, Any]:
    """获取某一季的所有集"""
    stmt = select(orm_models.MediaItem).where(
        orm_models.MediaItem.serverId == server_id,
        orm_models.MediaItem.title == title,
        orm_models.MediaItem.season == season,
        orm_models.MediaItem.mediaType == 'tv_series'
    )

    # 计算总数
    count_stmt = select(func.count()).select_from(stmt.alias("count_subquery"))
    total = (await session.execute(count_stmt)).scalar_one()

    # 分页查询
    stmt = stmt.order_by(orm_models.MediaItem.episode).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(stmt)
    episodes = result.scalars().all()

    return {
        "total": total,
        "list": [
            {
                "id": ep.id,
                "serverId": ep.serverId,
                "mediaId": ep.mediaId,
                "libraryId": ep.libraryId,
                "title": ep.title,
                "mediaType": ep.mediaType,
                "season": ep.season,
                "episode": ep.episode,
                "year": ep.year,
                "tmdbId": ep.tmdbId,
                "tvdbId": ep.tvdbId,
                "imdbId": ep.imdbId,
                "posterUrl": ep.posterUrl,
                "isImported": ep.isImported,
                "createdAt": ep.createdAt,
                "updatedAt": ep.updatedAt
            }
            for ep in episodes
        ]
    }


async def create_media_item(
    session: AsyncSession,
    server_id: int,
    media_id: str,
    library_id: Optional[str],
    title: str,
    media_type: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    year: Optional[int] = None,
    tmdb_id: Optional[str] = None,
    tvdb_id: Optional[str] = None,
    imdb_id: Optional[str] = None,
    poster_url: Optional[str] = None
) -> int:
    """创建媒体项(如果已存在则更新)"""
    # 检查是否已存在
    stmt = select(orm_models.MediaItem).where(
        orm_models.MediaItem.serverId == server_id,
        orm_models.MediaItem.mediaId == media_id
    )
    result = await session.execute(stmt)
    existing_item = result.scalar_one_or_none()

    if existing_item:
        # 更新现有项
        existing_item.title = title
        existing_item.mediaType = media_type
        existing_item.season = season
        existing_item.episode = episode
        existing_item.year = year
        existing_item.tmdbId = tmdb_id
        existing_item.tvdbId = tvdb_id
        existing_item.imdbId = imdb_id
        existing_item.posterUrl = poster_url
        existing_item.updatedAt = get_now()
        await session.flush()
        return existing_item.id
    else:
        # 创建新项
        new_item = orm_models.MediaItem(
            serverId=server_id,
            mediaId=media_id,
            libraryId=library_id,
            title=title,
            mediaType=media_type,
            season=season,
            episode=episode,
            year=year,
            tmdbId=tmdb_id,
            tvdbId=tvdb_id,
            imdbId=imdb_id,
            posterUrl=poster_url,
            isImported=False,
            createdAt=get_now(),
            updatedAt=get_now()
        )
        session.add(new_item)
        await session.flush()
        return new_item.id


async def update_media_item(
    session: AsyncSession,
    item_id: int,
    title: Optional[str] = None,
    media_type: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    year: Optional[int] = None,
    tmdb_id: Optional[str] = None,
    tvdb_id: Optional[str] = None,
    imdb_id: Optional[str] = None,
    poster_url: Optional[str] = None
) -> bool:
    """更新媒体项"""
    item = await session.get(orm_models.MediaItem, item_id)
    if not item:
        return False

    if title is not None:
        item.title = title
    if media_type is not None:
        item.mediaType = media_type
    if season is not None:
        item.season = season
    if episode is not None:
        item.episode = episode
    if year is not None:
        item.year = year
    if tmdb_id is not None:
        item.tmdbId = tmdb_id
    if tvdb_id is not None:
        item.tvdbId = tvdb_id
    if imdb_id is not None:
        item.imdbId = imdb_id
    if poster_url is not None:
        item.posterUrl = poster_url

    item.updatedAt = get_now()
    await session.flush()
    return True


async def delete_media_item(session: AsyncSession, item_id: int) -> bool:
    """删除单个媒体项"""
    item = await session.get(orm_models.MediaItem, item_id)
    if not item:
        return False
    await session.delete(item)
    await session.flush()
    return True


async def delete_media_items_batch(session: AsyncSession, item_ids: List[int]) -> int:
    """批量删除媒体项"""
    stmt = delete(orm_models.MediaItem).where(orm_models.MediaItem.id.in_(item_ids))
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount


async def get_episode_ids_by_show(session: AsyncSession, server_id: int, title: str) -> List[int]:
    """根据剧集名称获取所有集的ID"""
    stmt = select(orm_models.MediaItem.id).where(
        orm_models.MediaItem.serverId == server_id,
        orm_models.MediaItem.title == title,
        orm_models.MediaItem.mediaType == 'tv_series'
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def get_episode_ids_by_season(session: AsyncSession, server_id: int, title: str, season: int) -> List[int]:
    """根据剧集名称和季度获取所有集的ID"""
    stmt = select(orm_models.MediaItem.id).where(
        orm_models.MediaItem.serverId == server_id,
        orm_models.MediaItem.title == title,
        orm_models.MediaItem.season == season,
        orm_models.MediaItem.mediaType == 'tv_series'
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def mark_media_items_imported(session: AsyncSession, item_ids: List[int]) -> int:
    """标记媒体项为已导入"""
    stmt = update(orm_models.MediaItem).where(
        orm_models.MediaItem.id.in_(item_ids)
    ).values(isImported=True)
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount


async def clear_media_items_by_server(session: AsyncSession, server_id: int) -> int:
    """清空指定服务器的所有媒体项"""
    stmt = delete(orm_models.MediaItem).where(orm_models.MediaItem.serverId == server_id)
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount

