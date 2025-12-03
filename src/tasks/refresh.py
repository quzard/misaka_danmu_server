"""刷新任务模块"""
import logging
import asyncio
from typing import Callable, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, orm_models
from ..rate_limiter import RateLimiter, RateLimitExceededError
from ..scraper_manager import ScraperManager
from ..metadata_manager import MetadataSourceManager
from ..task_manager import TaskManager, TaskSuccess, TaskPauseForRateLimit
from ..config_manager import ConfigManager
from ..title_recognition import TitleRecognitionManager
from .delete import delete_danmaku_file
from .utils import generate_episode_range_string

logger = logging.getLogger(__name__)

# 延迟导入以避免循环依赖
def _get_download_concurrent():
    from .download_helpers import _download_episode_comments_concurrent
    return _download_episode_comments_concurrent

def _get_import_iteratively():
    from .download_helpers import _import_episodes_iteratively
    return _import_episodes_iteratively

def _get_generic_import():
    from .import_core import generic_import_task
    return generic_import_task


async def full_refresh_task(sourceId: int, session: AsyncSession, scraper_manager: ScraperManager, task_manager: TaskManager, rate_limiter: RateLimiter, progress_callback: Callable, metadata_manager: MetadataSourceManager, config_manager = None):
    """
    后台任务：全量刷新一个已存在的番剧，采用先获取后删除的安全策略。
    """
    logger.info(f"开始刷新源 ID: {sourceId}")
    try:
        source_info = await crud.get_anime_source_info(session, sourceId)
        if not source_info:
            raise ValueError(f"找不到源ID {sourceId} 的信息。")

        scraper = scraper_manager.get_scraper(source_info["providerName"])

        # 步骤 1: 获取新分集列表的元数据
        await progress_callback(10, "正在获取新分集列表...")
        current_media_id = source_info["mediaId"]

        # 对于优酷源,传入 is_full_refresh 参数
        if source_info["providerName"] == "youku":
            new_episodes_meta = await scraper.get_episodes(current_media_id, db_media_type=source_info.get("type"), is_full_refresh=True)
        else:
            new_episodes_meta = await scraper.get_episodes(current_media_id, db_media_type=source_info.get("type"))

        # --- 故障转移逻辑 ---
        if not new_episodes_meta:
            logger.info(f"主源 '{source_info['providerName']}' 未能找到分集，尝试故障转移...")
            await progress_callback(15, "主源未找到分集，尝试故障转移...")
            new_media_id = await metadata_manager.find_new_media_id(source_info)
            if new_media_id and new_media_id != current_media_id:
                logger.info(f"通过故障转移为 '{source_info['title']}' 找到新的 mediaId: '{new_media_id}'，将重试。")
                await progress_callback(18, f"找到新的媒体ID，正在重试...")
                await crud.update_source_media_id(session, sourceId, new_media_id)
                await session.commit() # 提交 mediaId 的更新

                # 对于优酷源,传入 is_full_refresh 参数
                if source_info["providerName"] == "youku":
                    new_episodes_meta = await scraper.get_episodes(new_media_id, is_full_refresh=True)
                else:
                    new_episodes_meta = await scraper.get_episodes(new_media_id)

        if not new_episodes_meta:
            raise TaskSuccess("刷新失败：未能从源获取任何分集信息。旧数据已保留。")

        # 步骤 2: 迭代地导入/更新分集
        _import_episodes_iteratively = _get_import_iteratively()
        total_comments_added, successful_indices, skipped_indices, failed_count, failed_details = await _import_episodes_iteratively(
            session=session,
            scraper=scraper,
            rate_limiter=rate_limiter,
            progress_callback=progress_callback,
            episodes=new_episodes_meta,
            anime_id=source_info["animeId"],
            source_id=sourceId,
            config_manager=config_manager,
            smart_refresh=True  # 全量刷新时启用智能比较模式
        )

        # 步骤 3: 在所有导入/更新操作完成后，清理过时的分集
        await progress_callback(95, "正在清理过时分集...")
        new_provider_ids = {ep.episodeId for ep in new_episodes_meta}
        old_episodes_res = await session.execute(
            select(orm_models.Episode).where(orm_models.Episode.sourceId == sourceId)
        )
        episodes_to_delete = [ep for ep in old_episodes_res.scalars().all() if ep.providerEpisodeId not in new_provider_ids]

        if episodes_to_delete:
            logger.info(f"全量刷新：找到 {len(episodes_to_delete)} 个过时的分集，正在删除...")
            for ep in episodes_to_delete:
                delete_danmaku_file(ep.danmakuFilePath)
                await session.delete(ep)
            await session.commit()
            logger.info("过时的分集已删除。")

        # 步骤 4: 构造最终的成功消息
        episode_range_str = generate_episode_range_string(successful_indices)
        final_message = f"全量刷新完成，处理了 {len(new_episodes_meta)} 个分集，新增 {total_comments_added} 条弹幕。"
        if failed_count > 0:
            # 添加失败详情
            failure_details = []
            for ep_index, error_msg in sorted(failed_details.items()):
                failure_details.append(f"第{ep_index}集: {error_msg}")
            final_message += f"\n失败 {failed_count} 集:\n" + "\n".join(failure_details)
        if episodes_to_delete:
            final_message += f" 删除了 {len(episodes_to_delete)} 个过时分集。"
        raise TaskSuccess(final_message)

    except TaskSuccess:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"全量刷新任务 (源ID: {sourceId}) 失败: {e}", exc_info=True)
        raise


async def refresh_episode_task(episodeId: int, session: AsyncSession, manager: ScraperManager, rate_limiter: RateLimiter, progress_callback: Callable, config_manager = None):
    """后台任务：刷新单个分集的弹幕"""
    logger.info(f"开始刷新分集 ID: {episodeId}")
    try:
        await progress_callback(0, "正在获取分集信息...")
        # 1. 获取分集的源信息
        info = await crud.get_episode_provider_info(session, episodeId)
        if not info or not info.get("providerName") or not info.get("providerEpisodeId"):
            logger.error(f"刷新失败：在数据库中找不到分集 ID: {episodeId} 的源信息")
            await progress_callback(100, "失败: 找不到源信息")
            return

        provider_name = info["providerName"]
        provider_episode_id = info["providerEpisodeId"]

        # 调试信息：检查获取到的信息
        logger.info(f"刷新分集 {episodeId}: provider_name='{provider_name}', provider_episode_id='{provider_episode_id}'")

        if not provider_name:
            raise ValueError(f"分集 {episodeId} 的 provider_name 为空")
        if not provider_episode_id:
            raise ValueError(f"分集 {episodeId} 的 provider_episode_id 为空")

        scraper = manager.get_scraper(provider_name)
        try:
            await rate_limiter.check(provider_name)
        except RuntimeError as e:
            # 配置错误（如速率限制配置验证失败），直接失败
            if "配置验证失败" in str(e):
                raise TaskSuccess(f"配置错误，任务已终止: {str(e)}")
            # 其他 RuntimeError 也应该失败
            raise
        except RateLimitExceededError as e:
            # 抛出暂停异常，让任务管理器处理
            logger.warning(f"刷新分集任务因达到速率限制而暂停: {e}")
            raise TaskPauseForRateLimit(
                retry_after_seconds=e.retry_after_seconds,
                message=f"速率受限，将在 {e.retry_after_seconds:.0f} 秒后自动重试..."
            )

        await progress_callback(30, "正在从源获取新弹幕...")

        # 使用三线程下载模式获取弹幕
        # 创建一个虚拟的分集对象用于并发下载
        from ..models import ProviderEpisodeInfo
        virtual_episode = ProviderEpisodeInfo(
            provider=provider_name,
            episodeIndex=1,
            title=f"刷新分集 {episodeId}",
            episodeId=provider_episode_id,
            url=""
        )

        async def sub_progress_callback(danmaku_progress: int, danmaku_description: str):
            # 30% for setup, 65% for download, 5% for db write
            current_total_progress = 30 + (danmaku_progress / 100) * 65
            await progress_callback(current_total_progress, danmaku_description)

        # 使用并发下载获取弹幕（三线程模式）
        _download_episode_comments_concurrent = _get_download_concurrent()
        download_results = await _download_episode_comments_concurrent(
            scraper, [virtual_episode], rate_limiter, sub_progress_callback
        )

        # 提取弹幕数据
        all_comments_from_source = None
        if download_results and len(download_results) > 0:
            _, comments = download_results[0]  # 忽略episode_index
            all_comments_from_source = comments

        if not all_comments_from_source:
            await crud.update_episode_fetch_time(session, episodeId)
            raise TaskSuccess("未找到任何弹幕。")

        await rate_limiter.increment(provider_name)

        await progress_callback(96, f"正在写入 {len(all_comments_from_source)} 条新弹幕...")

        # 获取 animeId 用于文件路径
        anime_id = info["animeId"]
        added_count = await crud.save_danmaku_for_episode(session, episodeId, all_comments_from_source, config_manager)

        await session.commit()
        raise TaskSuccess(f"刷新完成，新增 {added_count} 条弹幕。")
    except TaskSuccess:
        # 任务成功完成，直接重新抛出，由 TaskManager 处理
        raise
    except Exception as e:
        logger.error(f"刷新分集 ID: {episodeId} 时发生严重错误: {e}", exc_info=True)
        raise # Re-raise so the task manager catches it and marks as FAILED


async def refresh_bulk_episodes_task(episodeIds: List[int], session: AsyncSession, manager: ScraperManager, rate_limiter: RateLimiter, progress_callback: Callable, config_manager = None):
    """后台任务：批量刷新多个分集的弹幕"""
    total = len(episodeIds)
    logger.info(f"开始批量刷新 {total} 个分集")
    await progress_callback(5, f"准备刷新 {total} 个分集...")

    success_episodes = []  # 存储 (episodeNumber, episodeId) 元组
    failed_episodes = []   # 存储 (episodeNumber, episodeId) 元组
    total_added_comments = 0

    def format_episode_ranges(episodes: List[tuple]) -> str:
        """将集数列表格式化为区间字符串，如 <1,3,5,7-9>"""
        if not episodes:
            return "<无>"

        # 按集数排序
        sorted_episodes = sorted(episodes, key=lambda x: x[0])
        episode_numbers = [ep[0] for ep in sorted_episodes]

        ranges = []
        start = episode_numbers[0]
        end = episode_numbers[0]

        for i in range(1, len(episode_numbers)):
            if episode_numbers[i] == end + 1:
                end = episode_numbers[i]
            else:
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{end}")
                start = episode_numbers[i]
                end = episode_numbers[i]

        # 添加最后一个区间
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")

        return "<" + ",".join(ranges) + ">"

    try:
        _download_episode_comments_concurrent = _get_download_concurrent()

        for i, episode_id in enumerate(episodeIds):
            progress = 5 + int(((i + 1) / total) * 90) if total > 0 else 95
            await progress_callback(progress, f"正在刷新分集 {i+1}/{total} (ID: {episode_id})...")

            try:
                # 1. 获取分集的源信息
                info = await crud.get_episode_provider_info(session, episode_id)
                if not info or not info.get("providerName") or not info.get("providerEpisodeId"):
                    logger.warning(f"分集 ID {episode_id} 的源信息不完整，跳过")
                    # 如果没有集数信息，使用ID作为fallback
                    episode_index = info.get("episodeIndex", episode_id) if info else episode_id
                    failed_episodes.append((episode_index, episode_id))
                    continue

                provider_name = info["providerName"]
                provider_episode_id = info["providerEpisodeId"]
                episode_index = info.get("episodeIndex", episode_id)

                scraper = manager.get_scraper(provider_name)

                # 2. 检查流控
                try:
                    await rate_limiter.check(provider_name)
                except RuntimeError as e:
                    # 配置错误（如速率限制配置验证失败），跳过当前分集
                    if "配置验证失败" in str(e):
                        logger.error(f"配置错误，跳过分集 {episode_id}: {str(e)}")
                        failed_episodes.append((episode_index, episode_id))
                        continue
                    # 其他 RuntimeError 也应该跳过
                    logger.error(f"运行时错误，跳过分集 {episode_id}: {str(e)}")
                    failed_episodes.append((episode_index, episode_id))
                    continue
                except RateLimitExceededError as e:
                    # 达到流控限制，抛出暂停异常让任务管理器处理
                    # 这样可以释放 worker 去处理其他源的任务，而不是阻塞等待
                    logger.warning(f"批量刷新遇到速率限制: {e}")
                    raise TaskPauseForRateLimit(
                        retry_after_seconds=e.retry_after_seconds,
                        message=f"速率受限，将在 {e.retry_after_seconds:.0f} 秒后自动重试..."
                    )

                # 3. 下载弹幕
                from ..models import ProviderEpisodeInfo
                virtual_episode = ProviderEpisodeInfo(
                    provider=provider_name,
                    episodeIndex=1,
                    title=f"批量刷新分集 {episode_id}",
                    episodeId=provider_episode_id,
                    url=""
                )

                download_results = await _download_episode_comments_concurrent(
                    scraper, [virtual_episode], rate_limiter, lambda p, d: asyncio.sleep(0)
                )

                all_comments_from_source = None
                if download_results and len(download_results) > 0:
                    _, comments = download_results[0]
                    all_comments_from_source = comments

                if not all_comments_from_source:
                    await crud.update_episode_fetch_time(session, episode_id)
                    logger.warning(f"分集 {episode_id} 未找到任何弹幕")
                    failed_episodes.append((episode_index, episode_id))
                    continue

                await rate_limiter.increment(provider_name)

                # 4. 保存弹幕
                added_count = await crud.save_danmaku_for_episode(session, episode_id, all_comments_from_source, config_manager)
                total_added_comments += added_count
                success_episodes.append((episode_index, episode_id))

                # 提交事务，释放锁
                await session.commit()

                # 短暂休眠，允许其他操作执行
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"刷新分集 ID {episode_id} 时发生错误: {e}", exc_info=True)
                # 尝试获取集数，如果失败则使用ID
                try:
                    info = await crud.get_episode_provider_info(session, episode_id)
                    ep_idx = info.get("episodeIndex", episode_id) if info else episode_id
                except:
                    ep_idx = episode_id
                failed_episodes.append((ep_idx, episode_id))
                continue

        success_count = len(success_episodes)
        failed_count = len(failed_episodes)

        success_ranges = format_episode_ranges(success_episodes)
        failed_ranges = format_episode_ranges(failed_episodes)

        message = f"批量刷新完成，共处理 {total} 个，成功 {success_count} 个 {success_ranges}，失败 {failed_count} 个 {failed_ranges}，新增 {total_added_comments} 条弹幕。"
        raise TaskSuccess(message)
    except TaskSuccess:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"批量刷新分集任务失败: {e}", exc_info=True)
        raise


async def incremental_refresh_task(sourceId: int, nextEpisodeIndex: int, session: AsyncSession, manager: ScraperManager, task_manager: TaskManager, config_manager: ConfigManager, rate_limiter: RateLimiter, metadata_manager: MetadataSourceManager, progress_callback: Callable, animeTitle: str, title_recognition_manager: TitleRecognitionManager):
    """后台任务：增量刷新一个已存在的番剧。"""
    logger.info(f"开始增量刷新源 ID: {sourceId}，尝试获取第{nextEpisodeIndex}集")
    source_info = await crud.get_anime_source_info(session, sourceId)
    if not source_info:
        await progress_callback(100, "失败: 找不到源信息")
        logger.error(f"刷新失败：在数据库中找不到源 ID: {sourceId}")
        return
    try:
        # 重新执行通用导入逻辑, 只导入指定的一集
        generic_import_task = _get_generic_import()
        await generic_import_task(
            provider=source_info["providerName"], mediaId=source_info["mediaId"],
            animeTitle=animeTitle, mediaType=source_info["type"],
            season=source_info.get("season", 1), year=source_info.get("year"),
            currentEpisodeIndex=nextEpisodeIndex, imageUrl=source_info.get("imageUrl"),
            doubanId=None, tmdbId=source_info.get("tmdbId"), config_manager=config_manager, metadata_manager=metadata_manager,
            imdbId=None, tvdbId=None, bangumiId=source_info.get("bangumiId"),
            progress_callback=progress_callback,
            session=session,
            manager=manager, # type: ignore
            task_manager=task_manager,
            rate_limiter=rate_limiter,
            title_recognition_manager=title_recognition_manager)
    except TaskSuccess:
        # 显式地重新抛出 TaskSuccess，以确保它被 TaskManager 正确处理
        raise
    except Exception as e:
        logger.error(f"增量刷新源任务 (ID: {sourceId}) 失败: {e}", exc_info=True)
        raise

