import logging
from typing import Callable, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from . import crud, models, orm_models
from .image_utils import download_image
from .scraper_manager import ScraperManager
from .task_manager import TaskManager, TaskSuccess

logger = logging.getLogger(__name__)


async def delete_anime_task(anime_id: int, session: AsyncSession, progress_callback: Callable):
    """Background task to delete an anime and all its related data."""
    await progress_callback(0, "开始删除...")
    try:
        anime = await session.get(orm_models.Anime, anime_id)
        if not anime:
            raise TaskSuccess("作品未找到，无需删除。")

        await session.delete(anime)
        await session.commit()
        raise TaskSuccess("删除成功。")
    except Exception as e:
        await session.rollback()
        logger.error(f"删除作品任务 (ID: {anime_id}) 失败: {e}", exc_info=True)
        raise

async def delete_source_task(source_id: int, session: AsyncSession, progress_callback: Callable):
    """Background task to delete a source and all its related data."""
    progress_callback(0, "开始删除...")
    try:
        source = await session.get(orm_models.AnimeSource, source_id)
        if not source:
            raise TaskSuccess("数据源未找到，无需删除。")
        await session.delete(source)
        await session.commit()
        raise TaskSuccess("删除成功。")
    except Exception as e:
        logger.error(f"删除源任务 (ID: {source_id}) 失败: {e}", exc_info=True)
        raise

async def delete_episode_task(episode_id: int, session: AsyncSession, progress_callback: Callable):
    """Background task to delete an episode and its comments."""
    progress_callback(0, "开始删除...")
    try:
        episode = await session.get(orm_models.Episode, episode_id)
        if not episode:
            raise TaskSuccess("分集未找到，无需删除。")
        await session.delete(episode)
        await session.commit()
        raise TaskSuccess("删除成功。")
    except Exception as e:
        logger.error(f"删除分集任务 (ID: {episode_id}) 失败: {e}", exc_info=True)
        raise

async def delete_bulk_episodes_task(episode_ids: List[int], session: AsyncSession, progress_callback: Callable):
    """后台任务：批量删除多个分集。"""
    total = len(episode_ids)
    deleted_count = 0
    for i, episode_id in enumerate(episode_ids):
        progress = int((i / total) * 100)
        await progress_callback(progress, f"正在删除分集 {i+1}/{total} (ID: {episode_id})...")
        try:
            episode = await session.get(orm_models.Episode, episode_id)
            if episode:
                await session.delete(episode)
                await session.commit()
                deleted_count += 1
        except Exception as e:
            logger.error(f"批量删除分集任务中，删除分集 (ID: {episode_id}) 失败: {e}", exc_info=True)
    raise TaskSuccess(f"批量删除完成，共处理 {total} 个，成功删除 {deleted_count} 个。")

async def generic_import_task(
    provider: str, # noqa: F821
    media_id: str,
    anime_title: str,
    media_type: str,
    season: int,
    current_episode_index: Optional[int],
    image_url: Optional[str],
    douban_id: Optional[str],
    tmdb_id: Optional[str],
    imdb_id: Optional[str],
    tvdb_id: Optional[str],
    progress_callback: Callable,
    session: AsyncSession,
    manager: ScraperManager, 
    task_manager: TaskManager
):
    """
    后台任务：执行从指定数据源导入弹幕的完整流程。
    """
    # 重构导入逻辑以避免创建空条目
    scraper = manager.get_scraper(provider)
    normalized_title = anime_title.replace(":", "：")

    await progress_callback(10, "正在获取分集列表...")
    episodes = await scraper.get_episodes(
        media_id,
        target_episode_index=current_episode_index,
        db_media_type=media_type
    )
    if not episodes:
        msg = f"未能找到第 {current_episode_index} 集。" if current_episode_index else "未能获取到任何分集。"
        logger.warning(f"任务终止: {msg} (provider='{provider}', media_id='{media_id}')")
        raise TaskSuccess(msg)

    if media_type == "movie" and episodes:
        logger.info(f"检测到媒体类型为电影，将只处理第一个分集 '{episodes[0].title}'。")
        episodes = episodes[:1]

    anime_id: Optional[int] = None
    source_id: Optional[int] = None
    total_comments_added = 0
    total_episodes = len(episodes)

    for i, episode in enumerate(episodes):
        logger.info(f"--- 开始处理分集 {i+1}/{total_episodes}: '{episode.title}' (ID: {episode.episodeId}) ---")
        base_progress = 10 + int((i / total_episodes) * 85)
        await progress_callback(base_progress, f"正在处理: {episode.title} ({i+1}/{total_episodes})")

        async def sub_progress_callback(danmaku_progress: int, danmaku_description: str):
            current_total_progress = base_progress + (danmaku_progress / 100) * (85 / total_episodes)
            await progress_callback(current_total_progress, f"处理: {episode.title} - {danmaku_description}")

        comments = await scraper.get_comments(episode.episodeId, progress_callback=sub_progress_callback)

        if comments and anime_id is None:
            logger.info("首次成功获取弹幕，正在创建数据库主条目...")
            await progress_callback(base_progress + 1, "正在创建数据库主条目...")
            local_image_path = await download_image(image_url, session, provider)
            anime_id = await crud.get_or_create_anime(session, normalized_title, media_type, season, image_url, local_image_path)
            await crud.update_metadata_if_empty(session, anime_id, tmdb_id, imdb_id, tvdb_id, douban_id)
            source_id = await crud.link_source_to_anime(session, anime_id, provider, media_id)
            logger.info(f"主条目创建完成 (Anime ID: {anime_id}, Source ID: {source_id})。")

        if anime_id and source_id:
            episode_db_id = await crud.create_episode_if_not_exists(session, anime_id, source_id, episode.episodeIndex, episode.title, episode.url, episode.episodeId)
            if not comments:
                logger.info(f"分集 '{episode.title}' (DB ID: {episode_db_id}) 未找到弹幕，但已创建分集记录。")
                continue
            added_count = await crud.bulk_insert_comments(session, episode_db_id, comments)
            total_comments_added += added_count
            logger.info(f"分集 '{episode.title}' (DB ID: {episode_db_id}) 新增 {added_count} 条弹幕。")
        else:
            logger.info(f"分集 '{episode.title}' 未找到弹幕，跳过创建主条目。")

    if total_comments_added == 0:
        raise TaskSuccess("导入完成，但未找到任何新弹幕。")
    else:
        raise TaskSuccess(f"导入完成，共新增 {total_comments_added} 条弹幕。")
    
async def edited_import_task(
    request_data: "models.EditedImportRequest",
    progress_callback: Callable,
    session: AsyncSession,
    manager: ScraperManager
):
    """后台任务：处理编辑后的导入请求。"""
    scraper = manager.get_scraper(request_data.provider)
    normalized_title = request_data.anime_title.replace(":", "：")
    
    episodes = request_data.episodes
    if not episodes:
        raise TaskSuccess("没有提供任何分集，任务结束。")

    anime_id: Optional[int] = None
    source_id: Optional[int] = None
    total_comments_added = 0
    total_episodes = len(episodes)

    for i, episode in enumerate(episodes):
        await progress_callback(10 + int((i / total_episodes) * 85), f"正在处理: {episode.title} ({i+1}/{total_episodes})")
        comments = await scraper.get_comments(episode.episodeId)

        if comments and anime_id is None:
            local_image_path = await download_image(request_data.image_url, session, request_data.provider)
            anime_id = await crud.get_or_create_anime(session, normalized_title, request_data.media_type, request_data.season, request_data.image_url, local_image_path)
            await crud.update_metadata_if_empty(session, anime_id, request_data.tmdb_id, None, None, request_data.douban_id)
            source_id = await crud.link_source_to_anime(session, anime_id, request_data.provider, request_data.media_id)

        if anime_id and source_id:
            episode_db_id = await crud.create_episode_if_not_exists(session, anime_id, source_id, episode.episodeIndex, episode.title, episode.url, episode.episodeId)
            if comments:
                total_comments_added += await crud.bulk_insert_comments(session, episode_db_id, comments)

    if total_comments_added == 0: raise TaskSuccess("导入完成，但未找到任何新弹幕。")
    else: raise TaskSuccess(f"导入完成，共新增 {total_comments_added} 条弹幕。")

async def full_refresh_task(source_id: int, session: AsyncSession, manager: ScraperManager, task_manager: TaskManager, progress_callback: Callable):
    """
    后台任务：全量刷新一个已存在的番剧。
    """
    logger.info(f"开始刷新源 ID: {source_id}")
    source_info = await crud.get_anime_source_info(session, source_id)
    if not source_info:
        progress_callback(100, "失败: 找不到源信息")
        logger.error(f"刷新失败：在数据库中找不到源 ID: {source_id}")
        return
    
    anime_id = source_info["anime_id"]
    # 1. 清空旧数据
    await progress_callback(10, "正在清空旧数据...")
    await crud.clear_source_data(session, source_id)
    logger.info(f"已清空源 ID: {source_id} 的旧分集和弹幕。") # image_url 在这里不会被传递，因为刷新时我们不希望覆盖已有的海报
    # 2. 重新执行通用导入逻辑
    await generic_import_task(
        provider=source_info["provider_name"],
        media_id=source_info["media_id"],
        anime_title=source_info["title"],
        media_type=source_info["type"],
        season=source_info.get("season", 1),
        current_episode_index=None,
        image_url=None,
        douban_id=None, tmdb_id=source_info.get("tmdb_id"), 
        imdb_id=None, tvdb_id=None,
        progress_callback=progress_callback,
        session=session,
        manager=manager,
        task_manager=task_manager)

async def delete_bulk_sources_task(source_ids: List[int], session: AsyncSession, progress_callback: Callable):
    """Background task to delete multiple sources."""
    total = len(source_ids)
    deleted_count = 0
    for i, source_id in enumerate(source_ids):
        progress = int((i / total) * 100)
        await progress_callback(progress, f"正在删除源 {i+1}/{total} (ID: {source_id})...")
        try:
            source = await session.get(orm_models.AnimeSource, source_id)
            if source:
                await session.delete(source)
                await session.commit()
                deleted_count += 1
        except Exception as e:
            logger.error(f"批量删除源任务中，删除源 (ID: {source_id}) 失败: {e}", exc_info=True)
            # Continue to the next one
    raise TaskSuccess(f"批量删除完成，共处理 {total} 个，成功删除 {deleted_count} 个。")

async def refresh_episode_task(episode_id: int, session: AsyncSession, manager: ScraperManager, progress_callback: Callable):
    """后台任务：刷新单个分集的弹幕"""
    logger.info(f"开始刷新分集 ID: {episode_id}")
    try:
        await progress_callback(0, "正在获取分集信息...")
        # 1. 获取分集的源信息
        info = await crud.get_episode_provider_info(session, episode_id)
        if not info or not info.get("provider_name") or not info.get("provider_episode_id"):
            logger.error(f"刷新失败：在数据库中找不到分集 ID: {episode_id} 的源信息")
            progress_callback(100, "失败: 找不到源信息")
            return

        provider_name = info["provider_name"]
        provider_episode_id = info["provider_episode_id"]
        scraper = manager.get_scraper(provider_name)

        # 3. 获取新弹幕并插入
        await progress_callback(30, "正在从源获取新弹幕...")
        
        async def sub_progress_callback(danmaku_progress: int, danmaku_description: str):
            # 30% for setup, 65% for download, 5% for db write
            current_total_progress = 30 + (danmaku_progress / 100) * 65
            await progress_callback(current_total_progress, danmaku_description)

        all_comments_from_source = await scraper.get_comments(provider_episode_id, progress_callback=sub_progress_callback)

        if not all_comments_from_source:
            await crud.update_episode_fetch_time(session, episode_id)
            raise TaskSuccess("未找到任何弹幕。")

        # 新增：在插入前，先筛选出数据库中不存在的新弹幕，以避免产生大量的“重复条目”警告。
        await progress_callback(95, "正在比对新旧弹幕...")
        existing_cids = await crud.get_existing_comment_cids(session, episode_id)
        new_comments = [c for c in all_comments_from_source if str(c.get('cid')) not in existing_cids]

        if not new_comments:
            await crud.update_episode_fetch_time(session, episode_id)
            raise TaskSuccess("刷新完成，没有新增弹幕。")

        await progress_callback(96, f"正在写入 {len(new_comments)} 条新弹幕...")
        added_count = await crud.bulk_insert_comments(session, episode_id, new_comments)
        await crud.update_episode_fetch_time(session, episode_id)
        logger.info(f"分集 ID: {episode_id} 刷新完成，新增 {added_count} 条弹幕。")
        raise TaskSuccess(f"刷新完成，新增 {added_count} 条弹幕。")
    except TaskSuccess:
        # 任务成功完成，直接重新抛出，由 TaskManager 处理
        raise
    except Exception as e:
        logger.error(f"刷新分集 ID: {episode_id} 时发生严重错误: {e}", exc_info=True)
        raise # Re-raise so the task manager catches it and marks as FAILED

async def reorder_episodes_task(source_id: int, session: AsyncSession, progress_callback: Callable):
    """后台任务：重新编号一个源的所有分集。"""
    logger.info(f"开始重整源 ID: {source_id} 的分集顺序。")
    await progress_callback(0, "正在获取分集列表...")
    
    try:
        # 获取所有分集，按现有顺序排序
        episodes = await crud.get_episodes_for_source(session, source_id)
        if not episodes:
            raise TaskSuccess("没有找到分集，无需重整。")

        total_episodes = len(episodes)
        updated_count = 0
        
        # 开始事务
        try:
            for i, episode_data in enumerate(episodes):
                new_index = i + 1
                if episode_data['episode_index'] != new_index:
                    await session.execute(orm_models.update(orm_models.Episode).where(orm_models.Episode.id == episode_data['id']).values(episode_index=new_index))
                    updated_count += 1
                await progress_callback(int(((i + 1) / total_episodes) * 100), f"正在处理分集 {i+1}/{total_episodes}...")
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"重整源 ID {source_id} 时数据库事务失败: {e}", exc_info=True)
            raise
        raise TaskSuccess(f"重整完成，共更新了 {updated_count} 个分集的集数。")
    except Exception as e:
        logger.error(f"重整分集任务 (源ID: {source_id}) 失败: {e}", exc_info=True)
        raise

async def manual_import_task(
    source_id: int, title: str, episode_index: int, url: str, provider_name: str,
    progress_callback: Callable, session: AsyncSession, manager: ScraperManager
):
    """后台任务：从URL手动导入弹幕。"""
    logger.info(f"开始手动导入任务: source_id={source_id}, title='{title}', url='{url}'")
    await progress_callback(10, "正在准备导入...")
    
    try:
        scraper = manager.get_scraper(provider_name)
        
        provider_episode_id = None
        if hasattr(scraper, 'get_ids_from_url'): provider_episode_id = await scraper.get_ids_from_url(url)
        elif hasattr(scraper, 'get_danmaku_id_from_url'): provider_episode_id = await scraper.get_danmaku_id_from_url(url)
        elif hasattr(scraper, 'get_tvid_from_url'): provider_episode_id = await scraper.get_tvid_from_url(url)
        elif hasattr(scraper, 'get_vid_from_url'): provider_episode_id = await scraper.get_vid_from_url(url)
        
        if not provider_episode_id: raise ValueError(f"无法从URL '{url}' 中解析出有效的视频ID。")

        # 修正：处理 Bilibili 和 MGTV 返回的字典ID，并将其格式化为 get_comments 期望的字符串格式。
        episode_id_for_comments = provider_episode_id
        if isinstance(provider_episode_id, dict):
            if provider_name == 'bilibili':
                episode_id_for_comments = f"{provider_episode_id.get('aid')},{provider_episode_id.get('cid')}"
            elif provider_name == 'mgtv':
                # MGTV 的 get_comments 期望 "cid,vid"
                episode_id_for_comments = f"{provider_episode_id.get('cid')},{provider_episode_id.get('vid')}"
            else:
                # 对于其他可能的字典返回，将其字符串化
                episode_id_for_comments = str(provider_episode_id)

        await progress_callback(20, f"已解析视频ID: {episode_id_for_comments}")
        comments = await scraper.get_comments(episode_id_for_comments, progress_callback=progress_callback)
        if not comments: raise TaskSuccess("未找到任何弹幕。")

        await progress_callback(90, "正在写入数据库...")
        episode_db_id = await crud.get_or_create_episode(session, source_id, episode_index, title, url, episode_id_for_comments)
        added_count = await crud.bulk_insert_comments(session, episode_db_id, comments)
        raise TaskSuccess(f"手动导入完成，新增 {added_count} 条弹幕。")
    except TaskSuccess:
        raise
    except Exception as e:
        logger.error(f"手动导入任务失败: {e}", exc_info=True)
        raise
