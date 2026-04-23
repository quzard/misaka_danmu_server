"""Webhook 删除联动任务模块

当媒体服务（Emby/Jellyfin）发送删除事件时，根据预存的三级 ID 匹配弹幕库记录并删除。
"""
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sa_delete

from src.db import orm_models, crud, ConfigManager
from src.db.orm_models import AnimeMetadata, Episode, AnimeSource, Anime
from src.db.crud.danmaku import _get_fs_path_from_web_path
from src.tasks.delete import _cleanup_empty_parent_directories, _determine_cleanup_stop_dir

logger = logging.getLogger(__name__)


async def handle_webhook_delete(
    session: AsyncSession,
    config_manager: ConfigManager,
    server_type: str,
    item_type: str,
    item_id: str,
    series_id: Optional[str] = None,
    season_id: Optional[str] = None,
    season_number: Optional[int] = None,
    title: Optional[str] = None,
):
    """
    处理媒体服务的删除事件。

    Args:
        server_type: 媒体服务类型 ("emby" / "jellyfin")
        item_type: 被删除的 Item 类型 ("Episode" / "Season" / "Series" / "Movie")
        item_id: 被删除的 Item ID
        series_id: Series 级别 ID（删除 Episode/Season 时可能有）
        season_id: Season 级别 ID（删除 Episode 时可能有）
        season_number: 季号（用于 Season 删除时精确匹配）
        title: 标题（用于日志）
    """
    server_type = (server_type or "").strip().lower()

    # 检查删除联动开关
    enabled = (await config_manager.get("webhookDeleteSyncEnabled", "false")).lower() == "true"
    if not enabled:
        logger.info(f"Webhook 删除联动已禁用，忽略 {server_type} 的 {item_type} 删除事件 (ItemId={item_id})")
        return

    display_title = title or item_id
    logger.info(f"📛 Webhook 删除联动: {server_type} {item_type} 删除 - '{display_title}' (ItemId={item_id})")

    if item_type == "Episode":
        await _delete_by_episode_id(session, server_type, item_id, display_title)
    elif item_type == "Season":
        await _delete_by_season_id(session, server_type, season_id or item_id, season_number, display_title)
    elif item_type in ("Series", "Movie"):
        await _delete_by_series_id(session, server_type, series_id or item_id, display_title)
    else:
        logger.info(f"Webhook 删除联动: 忽略未知的 Item 类型 '{item_type}'")


async def _delete_by_episode_id(session: AsyncSession, server_type: str, episode_id: str, title: str):
    """根据 Episode 级别 ID 删除单集。"""
    stmt = (
        select(Episode)
        .join(AnimeSource, Episode.sourceId == AnimeSource.id)
        .join(Anime, AnimeSource.animeId == Anime.id)
        .join(AnimeMetadata, AnimeMetadata.animeId == Anime.id)
        .where(
            Episode.mediaServerEpisodeId == episode_id,
            AnimeMetadata.mediaServerType == server_type,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    episode = result.scalar_one_or_none()

    if not episode:
        logger.info(f"Webhook 删除联动: 未找到 server_type={server_type}, mediaServerEpisodeId={episode_id} 对应的分集，跳过")
        return

    logger.info(f"Webhook 删除联动: 找到匹配分集 id={episode.id}, episodeIndex={episode.episodeIndex}, 正在删除...")
    fs_path = _get_fs_path_from_web_path(episode.danmakuFilePath) if episode.danmakuFilePath else None

    try:
        await session.delete(episode)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.error(f"Webhook 删除联动: 删除分集 id={episode.id} ('{title}') 时失败", exc_info=True)
        raise

    if fs_path:
        try:
            if fs_path.is_file():
                fs_path.unlink(missing_ok=True)
                _cleanup_empty_parent_directories(fs_path, _determine_cleanup_stop_dir(fs_path))
        except Exception as e:
            logger.warning(f"Webhook 删除联动: 清理分集弹幕文件失败 {fs_path}: {e}")

    logger.info(f"✓ Webhook 删除联动: 已删除分集 id={episode.id} ('{title}' 第{episode.episodeIndex}集)")


async def _delete_by_season_id(session: AsyncSession, server_type: str, season_id: str, season_number: Optional[int], title: str):
    """根据 Season 级别 ID 删除整季。"""
    stmt = select(AnimeMetadata).where(
        AnimeMetadata.mediaServerType == server_type,
        AnimeMetadata.mediaServerSeasonId == season_id
    )
    result = await session.execute(stmt)
    metadata_records = result.scalars().all()

    if season_number is not None:
        logger.info(f"Webhook 删除联动: season_id={season_id} 同时带有 season_number={season_number}，当前以 season_id 为主进行精确匹配")

    if not metadata_records:
        logger.info(f"Webhook 删除联动: 未找到 mediaServerSeasonId={season_id} 对应的作品，跳过")
        return

    for metadata in metadata_records:
        anime_id = metadata.animeId
        logger.info(f"Webhook 删除联动: 找到匹配作品 animeId={anime_id}, 正在删除整季...")
        await _delete_anime_and_episodes(session, anime_id, title)


async def _delete_by_series_id(session: AsyncSession, server_type: str, series_id: str, title: str):
    """根据 Series 级别 ID 删除整剧（可能涉及多季）。"""
    stmt = select(AnimeMetadata).where(
        AnimeMetadata.mediaServerType == server_type,
        AnimeMetadata.mediaServerSeriesId == series_id
    )
    result = await session.execute(stmt)
    metadata_records = result.scalars().all()

    if not metadata_records:
        logger.info(f"Webhook 删除联动: 未找到 mediaServerSeriesId={series_id} 对应的作品，跳过")
        return

    logger.info(f"Webhook 删除联动: 找到 {len(metadata_records)} 个匹配作品（可能是多季），正在删除...")
    for metadata in metadata_records:
        await _delete_anime_and_episodes(session, metadata.animeId, title)


async def _delete_anime_and_episodes(session: AsyncSession, anime_id: int, title: str):
    """删除一个 Anime 下的所有 Episode（含弹幕文件）、AnimeSource、以及 Anime 本身。"""
    file_paths_to_cleanup = []
    deleted_ep_count = 0

    try:
        # 1. 收集所有 Episode 及其文件路径
        sources_stmt = select(AnimeSource).where(AnimeSource.animeId == anime_id)
        sources_result = await session.execute(sources_stmt)
        sources = sources_result.scalars().all()

        for source in sources:
            ep_stmt = select(Episode).where(Episode.sourceId == source.id)
            ep_result = await session.execute(ep_stmt)
            episodes = ep_result.scalars().all()
            for ep in episodes:
                if ep.danmakuFilePath:
                    fs_path = _get_fs_path_from_web_path(ep.danmakuFilePath)
                    if fs_path:
                        file_paths_to_cleanup.append(fs_path)
                await session.delete(ep)
                deleted_ep_count += 1

        # 2. 删除 Anime（级联删除 AnimeSource、AnimeMetadata、AnimeAlias）
        anime = await session.get(Anime, anime_id)
        if anime:
            await session.delete(anime)

        await session.commit()
    except Exception:
        await session.rollback()
        logger.error(f"Webhook 删除联动: 删除作品 animeId={anime_id} ('{title}') 时失败", exc_info=True)
        raise

    # 3. 数据库删除成功后，再尽力清理物理文件，避免半删半留
    for fs_path in file_paths_to_cleanup:
        try:
            if fs_path.is_file():
                fs_path.unlink(missing_ok=True)
                _cleanup_empty_parent_directories(fs_path, _determine_cleanup_stop_dir(fs_path))
        except Exception as e:
            logger.warning(f"Webhook 删除联动: 清理弹幕文件失败 {fs_path}: {e}")

    logger.info(f"✓ Webhook 删除联动: 已删除作品 animeId={anime_id} ('{title}'), 共删除 {deleted_ep_count} 个分集")
