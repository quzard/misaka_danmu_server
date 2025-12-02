"""删除任务模块"""
import logging
import asyncio
import shutil
from typing import Callable, List, Optional
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from .. import orm_models
from ..crud import DANMAKU_BASE_DIR, _get_fs_path_from_web_path
from ..task_manager import TaskSuccess

logger = logging.getLogger(__name__)


def delete_danmaku_file(danmaku_file_path_str: Optional[str]):
    """根据数据库中存储的Web路径，安全地删除对应的弹幕文件。"""
    if not danmaku_file_path_str:
        return
    try:
        # 修正：使用 crud 中的辅助函数来获取正确的文件系统路径
        fs_path = _get_fs_path_from_web_path(danmaku_file_path_str)
        if fs_path and fs_path.is_file():
            fs_path.unlink(missing_ok=True)
    except (ValueError, FileNotFoundError):
        # 如果路径无效或文件不存在，则忽略
        pass
    except Exception as e:
        logger.error(f"删除弹幕文件 '{danmaku_file_path_str}' 时出错: {e}", exc_info=True)


async def delete_anime_task(animeId: int, session: AsyncSession, progress_callback: Callable, delete_files: bool = True):
    """Background task to delete an anime and all its related data.

    Args:
        animeId: 作品ID
        session: 数据库会话
        progress_callback: 进度回调函数
        delete_files: 是否同时删除弹幕XML文件，默认为True
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await progress_callback(0, f"开始删除 (尝试 {attempt + 1}/{max_retries})...")

            # 检查作品是否存在
            anime_stmt = select(orm_models.Anime).where(orm_models.Anime.id == animeId)
            anime_result = await session.execute(anime_stmt)
            anime_exists = anime_result.scalar_one_or_none()
            if not anime_exists:
                raise TaskSuccess("作品未找到，无需删除。")

            # 1. 删除关联的弹幕文件（支持自定义路径）
            if delete_files:
                await progress_callback(30, "正在删除关联的弹幕文件...")
                # 查询该作品下所有分集的弹幕文件路径
                from sqlalchemy.orm import selectinload
                sources_stmt = select(orm_models.AnimeSource).where(
                    orm_models.AnimeSource.animeId == animeId
                ).options(selectinload(orm_models.AnimeSource.episodes))
                sources_result = await session.execute(sources_stmt)
                sources = sources_result.scalars().all()

                deleted_files_count = 0
                for source in sources:
                    for episode in source.episodes:
                        if episode.danmakuFilePath:
                            delete_danmaku_file(episode.danmakuFilePath)
                            deleted_files_count += 1

                # 同时尝试删除默认目录（兼容旧数据）
                anime_danmaku_dir = DANMAKU_BASE_DIR / str(animeId)
                if anime_danmaku_dir.exists() and anime_danmaku_dir.is_dir():
                    shutil.rmtree(anime_danmaku_dir)
                    logger.info(f"已删除作品的弹幕目录: {anime_danmaku_dir}")

                logger.info(f"已删除作品 {animeId} 的 {deleted_files_count} 个弹幕文件")

            # 2. 删除作品本身 (数据库将通过级联删除所有关联记录)
            await progress_callback(90, "正在删除数据库记录...")
            await session.delete(anime_exists)

            await session.commit()
            msg = "删除成功。" if delete_files else "删除成功（保留了弹幕文件）。"
            raise TaskSuccess(msg)
        except OperationalError as e:
            await session.rollback()
            if "Lock wait timeout exceeded" in str(e) and attempt < max_retries - 1:
                wait_time = 2 ** (attempt + 1) # 2, 4, 8 seconds
                logger.warning(f"删除作品时遇到锁超时，将在 {wait_time} 秒后重试...")
                await progress_callback(0, f"数据库锁定，将在 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
                continue # Retry the loop
            else:
                logger.error(f"删除作品任务 (ID: {animeId}) 失败: {e}", exc_info=True)
                raise # Re-raise if it's not a lock error or retries are exhausted
        except TaskSuccess:
            raise # Propagate success exception
        except Exception as e:
            await session.rollback()
            logger.error(f"删除作品任务 (ID: {animeId}) 失败: {e}", exc_info=True)
            raise


async def delete_source_task(sourceId: int, session: AsyncSession, progress_callback: Callable, delete_files: bool = True):
    """Background task to delete a source and all its related data.

    Args:
        sourceId: 数据源ID
        session: 数据库会话
        progress_callback: 进度回调函数
        delete_files: 是否同时删除弹幕XML文件，默认为True
    """
    await progress_callback(0, "开始删除...")
    try:
        # 检查源是否存在
        source_stmt = select(orm_models.AnimeSource).where(orm_models.AnimeSource.id == sourceId)
        source_result = await session.execute(source_stmt)
        source_exists = source_result.scalar_one_or_none()
        if not source_exists:
            raise TaskSuccess("数据源未找到，无需删除。")

        # 在删除数据库记录前，先删除关联的物理文件
        if delete_files:
            await progress_callback(30, "正在删除关联的弹幕文件...")
            episodes_to_delete_res = await session.execute(
                select(orm_models.Episode.danmakuFilePath).where(orm_models.Episode.sourceId == sourceId)
            )
            for file_path in episodes_to_delete_res.scalars().all():
                delete_danmaku_file(file_path)

        # 删除源记录，数据库将级联删除其下的所有分集记录
        await progress_callback(80, "正在删除数据库记录...")
        await session.delete(source_exists)
        await session.commit()

        msg = "删除成功。" if delete_files else "删除成功（保留了弹幕文件）。"
        raise TaskSuccess(msg)
    except TaskSuccess:
        # 显式地重新抛出 TaskSuccess，以确保它被 TaskManager 正确处理
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"删除源任务 (ID: {sourceId}) 失败: {e}", exc_info=True)
        raise


async def delete_episode_task(episodeId: int, session: AsyncSession, progress_callback: Callable, delete_files: bool = True):
    """Background task to delete an episode and its comments.

    Args:
        episodeId: 分集ID
        session: 数据库会话
        progress_callback: 进度回调函数
        delete_files: 是否同时删除弹幕XML文件，默认为True
    """
    await progress_callback(0, "开始删除...")
    try:
        # 检查分集是否存在
        episode_stmt = select(orm_models.Episode).where(orm_models.Episode.id == episodeId)
        episode_result = await session.execute(episode_stmt)
        episode_exists = episode_result.scalar_one_or_none()
        if not episode_exists:
            raise TaskSuccess("分集未找到，无需删除。")

        # 在删除数据库记录前，先删除物理文件
        if delete_files:
            delete_danmaku_file(episode_exists.danmakuFilePath)

        await session.delete(episode_exists)
        await session.commit()
        msg = "删除成功。" if delete_files else "删除成功（保留了弹幕文件）。"
        raise TaskSuccess(msg)
    except TaskSuccess:
        # 显式地重新抛出 TaskSuccess，以确保它被 TaskManager 正确处理
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"删除分集任务 (ID: {episodeId}) 失败: {e}", exc_info=True)
        raise


async def delete_bulk_episodes_task(episodeIds: List[int], session: AsyncSession, progress_callback: Callable, delete_files: bool = True):
    """后台任务：批量删除多个分集。

    Args:
        episodeIds: 分集ID列表
        session: 数据库会话
        progress_callback: 进度回调函数
        delete_files: 是否同时删除弹幕XML文件，默认为True
    """
    total = len(episodeIds)
    await progress_callback(5, f"准备删除 {total} 个分集...")
    deleted_count = 0
    try:
        for i, episode_id in enumerate(episodeIds):
            progress = 5 + int(((i + 1) / total) * 90) if total > 0 else 95
            await progress_callback(progress, f"正在删除分集 {i+1}/{total} (ID: {episode_id}) 的数据...")

            episode_stmt = select(orm_models.Episode).where(orm_models.Episode.id == episode_id)
            episode_result = await session.execute(episode_stmt)
            episode = episode_result.scalar_one_or_none()
            if episode:
                if delete_files:
                    delete_danmaku_file(episode.danmakuFilePath)
                await session.delete(episode)
                deleted_count += 1

                # 3. 为每个分集提交一次事务，以尽快释放锁
                await session.commit()

                # 短暂休眠，以允许其他数据库操作有机会执行
                await asyncio.sleep(0.1)

        suffix = "" if delete_files else "（保留了弹幕文件）"
        raise TaskSuccess(f"批量删除完成，共处理 {total} 个，成功删除 {deleted_count} 个。{suffix}")
    except TaskSuccess:
        # 显式地重新抛出 TaskSuccess，以确保它被 TaskManager 正确处理
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"批量删除分集任务失败: {e}", exc_info=True)
        raise


async def delete_bulk_sources_task(sourceIds: List[int], session: AsyncSession, progress_callback: Callable, delete_files: bool = True):
    """Background task to delete multiple sources.

    Args:
        sourceIds: 数据源ID列表
        session: 数据库会话
        progress_callback: 进度回调函数
        delete_files: 是否同时删除弹幕XML文件，默认为True
    """
    total = len(sourceIds)
    deleted_count = 0
    for i, sourceId in enumerate(sourceIds):
        progress = int((i / total) * 100)
        await progress_callback(progress, f"正在删除源 {i+1}/{total} (ID: {sourceId})...")
        try:
            source_stmt = select(orm_models.AnimeSource).where(orm_models.AnimeSource.id == sourceId)
            source_result = await session.execute(source_stmt)
            source = source_result.scalar_one_or_none()
            if source:
                # 删除关联的弹幕文件
                if delete_files:
                    episodes_to_delete_res = await session.execute(
                        select(orm_models.Episode.danmakuFilePath).where(orm_models.Episode.sourceId == sourceId)
                    )
                    for file_path in episodes_to_delete_res.scalars().all():
                        delete_danmaku_file(file_path)

                await session.delete(source)
                await session.commit()
                deleted_count += 1
        except Exception as e:
            logger.error(f"批量删除源任务中，删除源 (ID: {sourceId}) 失败: {e}", exc_info=True)
            # Continue to the next one
    await session.commit()
    suffix = "" if delete_files else "（保留了弹幕文件）"
    raise TaskSuccess(f"批量删除完成，共处理 {total} 个，成功删除 {deleted_count} 个。{suffix}")

