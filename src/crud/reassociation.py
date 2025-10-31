"""
Reassociation相关的CRUD操作
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, case, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from ..orm_models import Anime, AnimeSource, Episode
from .. import models
from ..timezone import get_now
from .danmaku import _get_fs_path_from_web_path

logger = logging.getLogger(__name__)


async def check_reassociation_conflicts(
    session: AsyncSession,
    source_anime_id: int,
    target_anime_id: int
) -> models.ReassociationConflictResponse:
    """检测关联操作是否存在冲突"""

    # 1. 加载数据
    source_anime_stmt = select(Anime).where(Anime.id == source_anime_id).options(
        selectinload(Anime.sources).selectinload(AnimeSource.episodes)
    )
    target_anime_stmt = select(Anime).where(Anime.id == target_anime_id).options(
        selectinload(Anime.sources).selectinload(AnimeSource.episodes)
    )
    source_anime = (await session.execute(source_anime_stmt)).scalar_one_or_none()
    target_anime = (await session.execute(target_anime_stmt)).scalar_one_or_none()

    if not source_anime or not target_anime:
        return models.ReassociationConflictResponse(hasConflict=False, conflicts=[])

    # 2. 检测冲突
    target_sources_map = {s.providerName: s for s in target_anime.sources}
    conflicts = []

    for source_to_check in source_anime.sources:
        provider = source_to_check.providerName
        if provider in target_sources_map:
            target_source = target_sources_map[provider]

            # 找出冲突的分集
            target_episode_map = {ep.episodeIndex: ep for ep in target_source.episodes}
            conflict_episodes = []

            for source_ep in source_to_check.episodes:
                if source_ep.episodeIndex in target_episode_map:
                    target_ep = target_episode_map[source_ep.episodeIndex]
                    conflict_episodes.append(models.ConflictEpisode(
                        episodeIndex=source_ep.episodeIndex,
                        sourceEpisodeId=source_ep.id,
                        targetEpisodeId=target_ep.id,
                        sourceDanmakuCount=source_ep.commentCount or 0,
                        targetDanmakuCount=target_ep.commentCount or 0,
                        sourceLastFetchTime=source_ep.fetchedAt,
                        targetLastFetchTime=target_ep.fetchedAt
                    ))

            if conflict_episodes:
                conflicts.append(models.ProviderConflict(
                    providerName=provider,
                    sourceSourceId=source_to_check.id,
                    targetSourceId=target_source.id,
                    conflictEpisodes=conflict_episodes
                ))

    return models.ReassociationConflictResponse(
        hasConflict=len(conflicts) > 0,
        conflicts=conflicts
    )


async def reassociate_anime_sources(session: AsyncSession, source_anime_id: int, target_anime_id: int) -> bool:
    """
    将一个番剧的所有源智能地合并到另一个番剧，然后删除原始番剧。
    - 如果目标番剧已存在相同提供商的源，则合并其下的分集，而不是直接删除。
    - 移动不冲突的源，并同时移动其下的弹幕文件。
    - 在合并后重新为目标番剧的所有源编号，以确保顺序正确。
    """
    if source_anime_id == target_anime_id:
        return False  # 不能将一个作品与它自己合并

    # 1. 高效地预加载所有需要的数据，包括目标作品的分集
    source_anime_stmt = select(Anime).where(Anime.id == source_anime_id).options(
        selectinload(Anime.sources).selectinload(AnimeSource.episodes)
    )
    target_anime_stmt = select(Anime).where(Anime.id == target_anime_id).options(
        selectinload(Anime.sources).selectinload(AnimeSource.episodes)
    )
    source_anime = (await session.execute(source_anime_stmt)).scalar_one_or_none()
    target_anime = (await session.execute(target_anime_stmt)).scalar_one_or_none()

    if not source_anime or not target_anime:
        logger.error(f"重新关联失败：源番剧(ID: {source_anime_id})或目标番剧(ID: {target_anime_id})未找到。")
        return False

    # 2. 识别目标番剧已有的提供商及其源对象，用于冲突检测和分集合并
    target_sources_map = {s.providerName: s for s in target_anime.sources}
    logger.info(f"目标番剧 (ID: {target_anime_id}) 已有源: {list(target_sources_map.keys())}")

    # 3. 遍历源番剧的源，处理冲突或移动
    for source_to_process in list(source_anime.sources):  # 使用副本进行迭代
        provider = source_to_process.providerName
        if provider in target_sources_map:
            # 冲突：合并分集
            target_source = target_sources_map[provider]
            logger.warning(f"发现冲突源: 提供商 '{provider}'。将尝试合并分集到目标源 {target_source.id}。")
            
            target_episode_indices = {ep.episodeIndex for ep in target_source.episodes}

            for episode_to_move in list(source_to_process.episodes):
                if episode_to_move.episodeIndex not in target_episode_indices:
                    # 移动不重复的分集
                    logger.info(f"正在移动分集 {episode_to_move.episodeIndex} (ID: {episode_to_move.id}) 到目标源 {target_source.id}")
                    
                    # 移动弹幕文件
                    if episode_to_move.danmakuFilePath:
                        old_path = _get_fs_path_from_web_path(episode_to_move.danmakuFilePath)
                        new_web_path = f"/app/config/danmaku/{target_anime_id}/{episode_to_move.id}.xml"
                        new_fs_path = _get_fs_path_from_web_path(new_web_path)
                        if old_path and old_path.exists() and new_fs_path:
                            new_fs_path.parent.mkdir(parents=True, exist_ok=True)
                            old_path.rename(new_fs_path)
                            episode_to_move.danmakuFilePath = new_web_path
                    
                    episode_to_move.sourceId = target_source.id
                    target_source.episodes.append(episode_to_move)
                else:
                    # 删除重复的分集
                    logger.info(f"分集 {episode_to_move.episodeIndex} 在目标源中已存在，将删除源分集 {episode_to_move.id}")
                    if episode_to_move.danmakuFilePath:
                        fs_path = _get_fs_path_from_web_path(episode_to_move.danmakuFilePath)
                        if fs_path and fs_path.is_file():
                            fs_path.unlink(missing_ok=True)
                    await session.delete(episode_to_move)
            
            # 删除现已为空的源
            await session.delete(source_to_process)
        else:
            # 不冲突：移动此源及其弹幕文件
            logger.info(f"正在将源 '{provider}' (ID: {source_to_process.id}) 移动到目标番剧 (ID: {target_anime_id})。")
            for ep in source_to_process.episodes:
                if ep.danmakuFilePath:
                    old_path = _get_fs_path_from_web_path(ep.danmakuFilePath)
                    new_web_path = f"/app/config/danmaku/{target_anime_id}/{ep.id}.xml"
                    new_fs_path = _get_fs_path_from_web_path(new_web_path)
                    if old_path and old_path.exists() and new_fs_path:
                        new_fs_path.parent.mkdir(parents=True, exist_ok=True)
                        old_path.rename(new_fs_path)
                        ep.danmakuFilePath = new_web_path
            source_to_process.animeId = target_anime_id
            target_anime.sources.append(source_to_process)

    # 4. 重新编号目标番剧的所有源的 sourceOrder
    sorted_sources = sorted(target_anime.sources, key=lambda s: s.sourceOrder)
    logger.info(f"正在为目标番剧 (ID: {target_anime_id}) 的 {len(sorted_sources)} 个源重新编号...")

    # 先将所有源的 sourceOrder 设置为负数,避免唯一约束冲突
    for i, source in enumerate(sorted_sources):
        source.sourceOrder = -(i + 1)
    await session.flush()

    # 再设置为正确的顺序
    for i, source in enumerate(sorted_sources):
        source.sourceOrder = i + 1
    await session.flush()

    # 5. 删除现已为空的源番剧
    logger.info(f"正在删除现已为空的源番剧 (ID: {source_anime_id})。")
    await session.delete(source_anime)
    await session.commit()
    logger.info("番剧源重新关联成功。")
    return True


async def reassociate_anime_sources_with_resolution(
    session: AsyncSession,
    source_anime_id: int,
    request: models.ReassociationResolveRequest
) -> bool:
    """根据用户选择执行关联操作"""

    # 1. 加载数据
    source_anime_stmt = select(Anime).where(Anime.id == source_anime_id).options(
        selectinload(Anime.sources).selectinload(AnimeSource.episodes)
    )
    target_anime_stmt = select(Anime).where(Anime.id == request.targetAnimeId).options(
        selectinload(Anime.sources).selectinload(AnimeSource.episodes)
    )
    source_anime = (await session.execute(source_anime_stmt)).scalar_one_or_none()
    target_anime = (await session.execute(target_anime_stmt)).scalar_one_or_none()

    if not source_anime or not target_anime:
        logger.error(f"重新关联失败：源番剧(ID: {source_anime_id})或目标番剧(ID: {request.targetAnimeId})未找到。")
        return False

    # 2. 构建解决方案映射
    resolution_map = {r.providerName: r for r in request.resolutions}
    target_sources_map = {s.providerName: s for s in target_anime.sources}

    # 3. 处理每个源
    for source_to_process in list(source_anime.sources):
        provider = source_to_process.providerName

        if provider in target_sources_map:
            # 有冲突,使用用户选择的解决方案
            target_source = target_sources_map[provider]
            resolution = resolution_map.get(provider)

            if not resolution:
                logger.warning(f"提供商 '{provider}' 没有解决方案,跳过")
                continue

            # 应用集数偏移
            offset = resolution.sourceOffset

            # 构建用户选择映射: {集数: 是否保留源分集}
            keep_source_map = {r.episodeIndex: r.keepSource for r in resolution.episodeResolutions}

            target_episode_map = {ep.episodeIndex: ep for ep in target_source.episodes}

            for episode_to_process in list(source_to_process.episodes):
                # 应用偏移
                adjusted_index = episode_to_process.episodeIndex + offset

                if episode_to_process.episodeIndex in keep_source_map:
                    # 这是一个冲突分集
                    keep_source = keep_source_map[episode_to_process.episodeIndex]

                    if adjusted_index in target_episode_map:
                        target_episode = target_episode_map[adjusted_index]

                        if keep_source:
                            # 保留源分集,删除目标分集
                            logger.info(f"保留源分集 {episode_to_process.episodeIndex},删除目标分集 {adjusted_index}")

                            # 删除目标分集的弹幕文件
                            if target_episode.danmakuFilePath:
                                fs_path = _get_fs_path_from_web_path(target_episode.danmakuFilePath)
                                if fs_path and fs_path.is_file():
                                    fs_path.unlink(missing_ok=True)
                            await session.delete(target_episode)

                            # 移动源分集
                            if episode_to_process.danmakuFilePath:
                                old_path = _get_fs_path_from_web_path(episode_to_process.danmakuFilePath)
                                new_web_path = f"/app/config/danmaku/{request.targetAnimeId}/{episode_to_process.id}.xml"
                                new_fs_path = _get_fs_path_from_web_path(new_web_path)
                                if old_path and old_path.exists() and new_fs_path:
                                    new_fs_path.parent.mkdir(parents=True, exist_ok=True)
                                    old_path.rename(new_fs_path)
                                    episode_to_process.danmakuFilePath = new_web_path

                            episode_to_process.episodeIndex = adjusted_index
                            episode_to_process.sourceId = target_source.id
                            target_source.episodes.append(episode_to_process)
                        else:
                            # 保留目标分集,删除源分集
                            logger.info(f"保留目标分集 {adjusted_index},删除源分集 {episode_to_process.episodeIndex}")

                            if episode_to_process.danmakuFilePath:
                                fs_path = _get_fs_path_from_web_path(episode_to_process.danmakuFilePath)
                                if fs_path and fs_path.is_file():
                                    fs_path.unlink(missing_ok=True)
                            await session.delete(episode_to_process)
                    else:
                        # 目标没有这个集数,直接移动
                        logger.info(f"移动源分集 {episode_to_process.episodeIndex} → {adjusted_index} (目标无此集)")

                        if episode_to_process.danmakuFilePath:
                            old_path = _get_fs_path_from_web_path(episode_to_process.danmakuFilePath)
                            new_web_path = f"/app/config/danmaku/{request.targetAnimeId}/{episode_to_process.id}.xml"
                            new_fs_path = _get_fs_path_from_web_path(new_web_path)
                            if old_path and old_path.exists() and new_fs_path:
                                new_fs_path.parent.mkdir(parents=True, exist_ok=True)
                                old_path.rename(new_fs_path)
                                episode_to_process.danmakuFilePath = new_web_path

                        episode_to_process.episodeIndex = adjusted_index
                        episode_to_process.sourceId = target_source.id
                        target_source.episodes.append(episode_to_process)
                else:
                    # 非冲突分集,直接移动
                    if adjusted_index not in target_episode_map:
                        logger.info(f"移动非冲突分集 {episode_to_process.episodeIndex} → {adjusted_index}")

                        if episode_to_process.danmakuFilePath:
                            old_path = _get_fs_path_from_web_path(episode_to_process.danmakuFilePath)
                            new_web_path = f"/app/config/danmaku/{request.targetAnimeId}/{episode_to_process.id}.xml"
                            new_fs_path = _get_fs_path_from_web_path(new_web_path)
                            if old_path and old_path.exists() and new_fs_path:
                                new_fs_path.parent.mkdir(parents=True, exist_ok=True)
                                old_path.rename(new_fs_path)
                                episode_to_process.danmakuFilePath = new_web_path

                        episode_to_process.episodeIndex = adjusted_index
                        episode_to_process.sourceId = target_source.id
                        target_source.episodes.append(episode_to_process)
                    else:
                        # 偏移后产生新的冲突,删除源分集
                        logger.warning(f"偏移后产生冲突: 源分集 {episode_to_process.episodeIndex} → {adjusted_index},删除源分集")
                        if episode_to_process.danmakuFilePath:
                            fs_path = _get_fs_path_from_web_path(episode_to_process.danmakuFilePath)
                            if fs_path and fs_path.is_file():
                                fs_path.unlink(missing_ok=True)
                        await session.delete(episode_to_process)

            # 删除源
            await session.delete(source_to_process)
        else:
            # 无冲突,直接移动
            logger.info(f"移动无冲突源 '{provider}'")
            for ep in source_to_process.episodes:
                if ep.danmakuFilePath:
                    old_path = _get_fs_path_from_web_path(ep.danmakuFilePath)
                    new_web_path = f"/app/config/danmaku/{request.targetAnimeId}/{ep.id}.xml"
                    new_fs_path = _get_fs_path_from_web_path(new_web_path)
                    if old_path and old_path.exists() and new_fs_path:
                        new_fs_path.parent.mkdir(parents=True, exist_ok=True)
                        old_path.rename(new_fs_path)
                        ep.danmakuFilePath = new_web_path
            source_to_process.animeId = request.targetAnimeId
            target_anime.sources.append(source_to_process)

    # 4. 重新编号
    sorted_sources = sorted(target_anime.sources, key=lambda s: s.sourceOrder)
    logger.info(f"正在为目标番剧 (ID: {request.targetAnimeId}) 的 {len(sorted_sources)} 个源重新编号...")
    for i, source in enumerate(sorted_sources):
        new_order = i + 1
        if source.sourceOrder != new_order:
            source.sourceOrder = new_order

    # 5. 删除源番剧
    logger.info(f"正在删除现已为空的源番剧 (ID: {source_anime_id})。")
    await session.delete(source_anime)
    await session.commit()
    logger.info("番剧源重新关联成功(带冲突解决)。")
    return True

