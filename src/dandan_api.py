import asyncio
import logging
import json
import re
import time
import ipaddress
from typing import List, Optional, Dict, Any, Tuple
from typing import Callable
from datetime import datetime, timezone
from opencc import OpenCC
from thefuzz import fuzz

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from . import crud, models, orm_models, tasks, scraper_manager as sm, rate_limiter as rl
from .config_manager import ConfigManager
from .cache_manager import CacheManager
from .timezone import get_now, get_app_timezone
from .database import get_db_session, sync_postgres_sequence
from .utils import parse_search_keyword, sample_comments_evenly
from .rate_limiter import RateLimiter
from .task_manager import TaskManager, TaskStatus, TaskSuccess
from .metadata_manager import MetadataSourceManager
from .scraper_manager import ScraperManager
from .api.control_api import ControlAutoImportRequest, get_title_recognition_manager
from .api.dependencies import get_cache_manager
from .search_utils import unified_search
from .ai_matcher import AIMatcher, DEFAULT_AI_MATCH_PROMPT
from .orm_models import Anime, AnimeSource, Episode
from .models import ProviderEpisodeInfo

logger = logging.getLogger(__name__)

# --- Module-level Constants for Type Mappings and Parsing ---
# To avoid repetition and improve maintainability.
DANDAN_TYPE_MAPPING = {
    "tv_series": "tvseries", "movie": "movie", "ova": "ova", "other": "other"
}
DANDAN_TYPE_DESC_MAPPING = {
    "tv_series": "TV动画", "movie": "电影/剧场版", "ova": "OVA", "other": "其他"
}

# 后备搜索状态管理
FALLBACK_SEARCH_BANGUMI_ID = 999999999  # 搜索中的固定bangumiId
SAMPLED_CACHE_TTL = 86400  # 缓存1天 (24小时) - 保留用于兼容性

# episodeId到源映射的缓存键前缀
EPISODE_MAPPING_CACHE_PREFIX = "episode_mapping_"

# 缓存键前缀定义
FALLBACK_SEARCH_CACHE_PREFIX = "fallback_search_"
TOKEN_SEARCH_TASKS_PREFIX = "token_search_task_"
USER_LAST_BANGUMI_CHOICE_PREFIX = "user_last_bangumi_"
COMMENTS_FETCH_CACHE_PREFIX = "comments_fetch_"
SAMPLED_COMMENTS_CACHE_PREFIX = "sampled_comments_"

# 缓存TTL定义
FALLBACK_SEARCH_CACHE_TTL = 3600  # 后备搜索缓存1小时
TOKEN_SEARCH_TASKS_TTL = 3600  # Token搜索任务1小时
USER_LAST_BANGUMI_CHOICE_TTL = 86400  # 用户选择记录1天
COMMENTS_FETCH_CACHE_TTL = 300  # 弹幕获取缓存5分钟(临时缓存)
SAMPLED_COMMENTS_CACHE_TTL_DB = 86400  # 弹幕采样缓存1天

# ==================== 缓存辅助函数(兼容层) ====================
# 这些函数现在作为 CacheManager 的兼容包装器
# 从 app.state 获取全局 CacheManager 实例

def _get_cache_manager_from_request() -> Optional[CacheManager]:
    """从当前请求上下文获取 CacheManager"""
    try:
        from starlette.requests import Request
        from contextvars import ContextVar
        # 这是一个简化的实现,实际使用时需要从依赖注入获取
        return None
    except:
        return None

async def _get_db_cache(session: AsyncSession, prefix: str, key: str) -> Optional[Any]:
    """
    从数据库缓存中获取数据(兼容包装器)
    """
    cache_key = f"{prefix}{key}"
    cached_data = await crud.get_cache(session, cache_key)

    if cached_data:
        try:
            if isinstance(cached_data, str):
                return json.loads(cached_data)
            else:
                return cached_data
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"解析缓存数据失败: {cache_key}, 错误: {e}")
            return None
    return None

async def _set_db_cache(session: AsyncSession, prefix: str, key: str, value: Any, ttl_seconds: int):
    """
    设置数据库缓存(兼容包装器)
    """
    cache_key = f"{prefix}{key}"
    try:
        if not isinstance(value, str):
            json_value = json.dumps(value, ensure_ascii=False)
        else:
            json_value = value
        await crud.set_cache(session, cache_key, json_value, ttl_seconds)
        logger.debug(f"设置缓存: {cache_key}")
    except Exception as e:
        logger.error(f"设置缓存失败: {cache_key}, 错误: {e}")

async def _delete_db_cache(session: AsyncSession, prefix: str, key: str) -> bool:
    """
    删除数据库缓存(兼容包装器)
    """
    cache_key = f"{prefix}{key}"
    try:
        result = await crud.delete_cache(session, cache_key)
        if result:
            logger.debug(f"删除缓存: {cache_key}")
        return result
    except Exception as e:
        logger.error(f"删除缓存失败: {cache_key}, 错误: {e}")
        return False

# ==================== 结束缓存辅助函数 ====================

async def _store_episode_mapping(session: AsyncSession, episode_id: int, provider: str, media_id: str, episode_index: int, original_title: str):
    """
    存储episodeId到源的映射关系到数据库缓存
    """
    mapping_data = {
        "provider": provider,
        "media_id": media_id,
        "episode_index": episode_index,
        "original_title": original_title,
        "timestamp": time.time()
    }

    cache_key = f"{EPISODE_MAPPING_CACHE_PREFIX}{episode_id}"
    # 使用3小时过期时间（10800秒）
    await crud.set_cache(session, cache_key, json.dumps(mapping_data), ttl_seconds=10800)
    logger.debug(f"存储episodeId映射: {episode_id} -> {provider}:{media_id}")

async def _get_episode_mapping(session: AsyncSession, episode_id: int) -> Optional[Dict[str, Any]]:
    """
    从数据库缓存中获取episodeId的映射关系
    """
    cache_key = f"{EPISODE_MAPPING_CACHE_PREFIX}{episode_id}"
    cached_data = await crud.get_cache(session, cache_key)

    if cached_data:
        try:
            # cached_data可能已经是dict类型（从crud.get_cache返回）
            if isinstance(cached_data, str):
                mapping_data = json.loads(cached_data)
            else:
                mapping_data = cached_data
            logger.info(f"从缓存获取episodeId映射: {episode_id} -> {mapping_data['provider']}:{mapping_data['media_id']}")
            return mapping_data
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"解析episodeId映射缓存失败: {e}")
            return None

    return None


def _format_episode_ranges(episodes: List[int]) -> str:
    """
    将分集列表格式化为简洁的范围表示
    例如: [1,2,3,5,6,7,10] -> "1-3,5-7,10"
    """
    if not episodes:
        return ""

    episodes = sorted(set(episodes))  # 去重并排序
    ranges = []
    start = episodes[0]
    end = episodes[0]

    for i in range(1, len(episodes)):
        if episodes[i] == end + 1:
            # 连续的集数
            end = episodes[i]
        else:
            # 不连续，保存当前范围
            if start == end:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{end}")
            start = episodes[i]
            end = episodes[i]

    # 保存最后一个范围
    if start == end:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{end}")

    return ",".join(ranges)
   
async def _find_existing_anime_by_bangumi_id(session: AsyncSession, bangumi_id: str, search_key: str) -> Optional[Dict[str, Any]]:
    """
    根据bangumiId和搜索会话查找已存在的映射记录，返回anime信息
    使用bangumiId确保精确匹配，避免不同搜索结果被错误合并
    """
    # 从数据库缓存中查找当前搜索会话的结果
    search_info = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
    if search_info:
        if "bangumi_mapping" in search_info:
            if bangumi_id in search_info["bangumi_mapping"]:
                mapping_info = search_info["bangumi_mapping"][bangumi_id]
                if mapping_info.get("real_anime_id"):
                    real_anime_id = mapping_info["real_anime_id"]
                    title = mapping_info.get("original_title", "未知")
                    logger.debug(f"在当前搜索会话中找到已存在的剧集: bangumiId={bangumi_id}, title='{title}' (anime_id={real_anime_id})")
                    return {"animeId": real_anime_id, "title": title}

    logger.debug(f"在当前搜索会话中未找到已存在的剧集: bangumiId={bangumi_id}")
    return None
  
async def _update_episode_mapping(session: AsyncSession, episode_id: int, provider: str, media_id: str, episode_index: int, original_title: str):
    """
    更新episodeId的映射关系（更新数据库缓存）
    """
    # 更新数据库缓存
    await _store_episode_mapping(session, episode_id, provider, media_id, episode_index, original_title)

    # 查找并更新fallback_search_cache中的real_anime_id映射
    real_anime_id = int(str(episode_id)[2:8])  # 从episodeId提取real_anime_id

    # 获取所有后备搜索缓存键（通过模式匹配）
    try:
        all_cache_keys = await crud.get_cache_keys_by_pattern(session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
        for cache_key in all_cache_keys:
            search_key = cache_key.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
            search_info = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)

            if search_info and search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
                for bangumi_id, mapping_info in search_info["bangumi_mapping"].items():
                    if mapping_info.get("real_anime_id") == real_anime_id:
                        # 更新映射信息
                        mapping_info["provider"] = provider
                        mapping_info["media_id"] = media_id
                        # 保存更新后的搜索信息
                        await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info, FALLBACK_SEARCH_CACHE_TTL)
                        # 更新用户选择记录
                        await _set_db_cache(session, USER_LAST_BANGUMI_CHOICE_PREFIX, search_key, bangumi_id, USER_LAST_BANGUMI_CHOICE_TTL)
                        logger.info(f"更新数据库缓存映射: real_anime_id={real_anime_id}, provider={provider}")
                        break
    except Exception as e:
        logger.warning(f"更新缓存映射失败: {e}")

    logger.debug(f"更新episodeId映射: {episode_id} -> {provider}:{media_id}")

async def _check_related_match_fallback_task(session: AsyncSession, search_term: str) -> Optional[Dict[str, Any]]:
    """
    检查是否有相关的后备匹配任务正在进行
    返回任务信息（包含进度）或None
    """
    # 查找正在进行的匹配后备任务
    # 通过TaskStateCache查找match_fallback类型的任务

    # 查询正在进行的匹配后备任务
    stmt = select(orm_models.TaskStateCache).where(
        orm_models.TaskStateCache.taskType == "match_fallback"
    ).order_by(orm_models.TaskStateCache.createdAt.desc()).limit(10)  # 获取最近10个任务

    result = await session.execute(stmt)
    task_caches = result.scalars().all()

    # 检查任务参数中是否包含相关的搜索词
    for task_cache in task_caches:
        # 获取对应的TaskHistory记录
        history_stmt = select(orm_models.TaskHistory).where(
            orm_models.TaskHistory.taskId == task_cache.taskId,
            orm_models.TaskHistory.status.in_(['排队中', '运行中'])
        )
        history_result = await session.execute(history_stmt)
        task_history = history_result.scalar_one_or_none()

        if task_history:
            # 简单的标题匹配 - 检查任务标题是否包含搜索词
            if search_term.lower() in task_history.title.lower():
                return {
                    "task_id": task_history.taskId,
                    "title": task_history.title,
                    "progress": task_history.progress or 0,
                    "status": task_history.status,
                    "description": task_history.description or "匹配后备正在进行"
                }

            # 也可以检查任务描述
            if task_history.description and search_term.lower() in task_history.description.lower():
                return {
                    "task_id": task_history.taskId,
                    "title": task_history.title,
                    "progress": task_history.progress or 0,
                    "status": task_history.status,
                    "description": task_history.description
                }

    return None

async def _get_next_virtual_anime_id(session: AsyncSession) -> int:
    """
    获取下一个虚拟animeId（6位数字，从900000开始）
    用于后备搜索结果显示
    """
    # 查找当前最大的虚拟animeId
    max_id = None
    try:
        all_cache_keys = await crud.get_cache_keys_by_pattern(session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
        for cache_key in all_cache_keys:
            search_key = cache_key.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
            search_info = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)

            if search_info and search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
                for bangumi_id, mapping_info in search_info["bangumi_mapping"].items():
                    anime_id = mapping_info.get("anime_id")
                    if anime_id and 900000 <= anime_id <= 999999:
                        if max_id is None or anime_id > max_id:
                            max_id = anime_id
    except Exception as e:
        logger.error(f"查找最大虚拟anime_id失败: {e}")

    if max_id is None:
        return 900000  # 如果没有找到，从900000开始
    else:
        return max_id + 1

async def _get_next_real_anime_id(session: AsyncSession) -> int:
    """
    获取下一个真实的animeId（当前最大animeId + 1）
    用于实际的episodeId生成
    """
    # 查询当前最大的animeId
    result = await session.execute(
        select(func.max(orm_models.Anime.id))
    )
    max_id = result.scalar()

    if max_id is None:
        return 1  # 如果没有找到，从1开始
    else:
        return max_id + 1

async def _try_predownload_next_episode(
    current_episode_id: int,
    session_factory,
    config_manager: ConfigManager,
    task_manager: TaskManager,
    scraper_manager: ScraperManager,
    rate_limiter: RateLimiter
):
    """
    尝试预下载下一集弹幕（异步，不阻塞当前请求）

    触发条件:
    1. preDownloadNextEpisodeEnabled = true
    2. matchFallbackEnabled = true 或 searchFallbackEnabled = true
    3. 下一集没有弹幕(无论是否存在记录)
    4. 没有正在运行的下载任务

    逻辑:
    - 如果下一集已有记录且有弹幕: 跳过
    - 如果下一集已有记录但无弹幕: 刷新弹幕
    - 如果下一集无记录: 从源站获取并创建记录+下载弹幕
    """
    try:
        # 1. 检查配置: 是否启用预下载
        predownload_enabled = (await config_manager.get("preDownloadNextEpisodeEnabled", "false")).lower() == 'true'
        if not predownload_enabled:
            logger.info(f"预下载跳过: 未启用预下载功能 (episodeId={current_episode_id})")
            return

        # 2. 检查配置: 是否启用后备机制
        match_fallback_enabled = (await config_manager.get("matchFallbackEnabled", "false")).lower() == 'true'
        search_fallback_enabled = (await config_manager.get("searchFallbackEnabled", "false")).lower() == 'true'

        if not match_fallback_enabled and not search_fallback_enabled:
            logger.info(f"预下载跳过: 未启用任何后备机制 (episodeId={current_episode_id}, matchFallback={match_fallback_enabled}, searchFallback={search_fallback_enabled})")
            return

        logger.info(f"预下载检查开始: episodeId={current_episode_id}, predownload={predownload_enabled}, matchFallback={match_fallback_enabled}, searchFallback={search_fallback_enabled}")

        # 3. 创建新的数据库会话 (避免与主请求的session冲突)
        async with session_factory() as session:
            # 4. 查询当前分集信息
            current_episode_stmt = select(orm_models.Episode).where(
                orm_models.Episode.id == current_episode_id
            )
            current_episode_result = await session.execute(current_episode_stmt)
            current_episode = current_episode_result.scalar_one_or_none()

            if not current_episode:
                logger.warning(f"预下载跳过: 当前分集 {current_episode_id} 不存在")
                return

            # 5. 获取source信息(需要provider和mediaId)
            source_stmt = select(orm_models.AnimeSource).where(
                orm_models.AnimeSource.id == current_episode.sourceId
            )
            source_result = await session.execute(source_stmt)
            source = source_result.scalar_one_or_none()

            if not source:
                logger.warning(f"预下载跳过: 当前分集的源 {current_episode.sourceId} 不存在")
                return

            # 6. 查询下一集
            next_episode_index = current_episode.episodeIndex + 1
            next_episode_stmt = select(orm_models.Episode).where(
                orm_models.Episode.sourceId == current_episode.sourceId,
                orm_models.Episode.episodeIndex == next_episode_index
            )
            next_episode_result = await session.execute(next_episode_stmt)
            next_episode = next_episode_result.scalar_one_or_none()

            # 7. 如果下一集已存在且有弹幕,跳过
            if next_episode and next_episode.commentCount > 0:
                logger.info(f"预下载跳过: 下一集 {next_episode.id} 已有 {next_episode.commentCount} 条弹幕")
                return

            # 8. 准备下载参数
            provider = source.providerName
            media_id = source.mediaId
            anime_id = source.animeId

            # 获取anime信息
            anime_stmt = select(orm_models.Anime).where(orm_models.Anime.id == anime_id)
            anime_result = await session.execute(anime_stmt)
            anime = anime_result.scalar_one_or_none()

            if not anime:
                logger.warning(f"预下载跳过: anime {anime_id} 不存在")
                return

        # 9. 在session外提交预下载任务
        logger.info(f"预下载: 准备下载下一集 (index={next_episode_index}, provider={provider}, mediaId={media_id})")

        # 使用unique_key防止重复
        unique_key = f"predownload_{provider}_{media_id}_{next_episode_index}"

        try:
            # 创建下载任务
            async def predownload_task(session, progress_callback):
                """预下载任务: 获取分集信息并下载弹幕"""
                try:

                    await progress_callback(10, "正在获取分集列表...")

                    # 获取分集列表
                    logger.info(f"预下载: 正在获取分集列表 (provider={provider}, mediaId={media_id})")
                    scraper = scraper_manager.get_scraper(provider)
                    episodes = await scraper.get_episodes(media_id)

                    if not episodes or len(episodes) == 0:
                        logger.warning(f"预下载失败: 无法获取分集列表 (provider={provider}, mediaId={media_id})")
                        raise TaskSuccess("无法获取分集列表")

                    # 查找下一集
                    target_episode = None
                    for ep in episodes:
                        if ep.episodeIndex == next_episode_index:
                            target_episode = ep
                            break

                    if not target_episode:
                        logger.info(f"预下载跳过: 源站没有第 {next_episode_index} 集 (provider={provider}, mediaId={media_id})")
                        raise TaskSuccess(f"源站没有第 {next_episode_index} 集")

                    provider_episode_id = target_episode.episodeId
                    episode_title = target_episode.title

                    logger.info(f"预下载: 找到下一集 '{episode_title}' (provider_episode_id={provider_episode_id})")

                    await progress_callback(30, f"正在下载弹幕: {episode_title}...")

                    # 检查速率限制
                    await rate_limiter.check(provider)

                    # 下载弹幕
                    comments = await scraper.get_comments(
                        provider_episode_id,
                        progress_callback=lambda p, msg: progress_callback(30 + int(p * 0.6), msg)
                    )

                    if not comments or len(comments) == 0:
                        logger.warning(f"预下载: 第 {next_episode_index} 集没有弹幕")
                        raise TaskSuccess("未找到弹幕")

                    await rate_limiter.increment(provider)

                    logger.info(f"预下载: 获取到 {len(comments)} 条弹幕")

                    await progress_callback(90, "正在保存弹幕...")

                    # 创建或获取Episode记录
                    episode_db_id = await crud.create_episode_if_not_exists(
                        session, anime_id, source.id, next_episode_index,
                        episode_title, target_episode.url, provider_episode_id
                    )

                    # 保存弹幕
                    added_count = await crud.save_danmaku_for_episode(
                        session, episode_db_id, comments, config_manager
                    )

                    await session.commit()

                    logger.info(f"✓ 预下载完成: '{episode_title}' (index={next_episode_index}, 新增{added_count}条弹幕)")
                    raise TaskSuccess(f"预下载完成，新增 {added_count} 条弹幕")

                except TaskSuccess:
                    raise
                except Exception as e:
                    logger.error(f"预下载任务失败: {e}", exc_info=True)
                    raise

            task_id, _ = await task_manager.submit_task(
                predownload_task,
                f"预下载弹幕: {anime.title} 第{next_episode_index}集",
                unique_key=unique_key,
                task_type="predownload"
            )
            logger.info(f"✓ 预下载任务已提交: anime='{anime.title}', index={next_episode_index}, taskId={task_id}")

        except HTTPException as e:
            if e.status_code == 409:
                logger.info(f"预下载跳过: 任务已在运行中 (unique_key={unique_key})")
            else:
                logger.warning(f"预下载任务提交失败 (HTTP {e.status_code}): {e.detail}")
        except Exception as e:
            logger.warning(f"预下载任务提交失败: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"预下载处理异常 (episodeId={current_episode_id}): {e}", exc_info=True)

def _generate_episode_id(anime_id: int, source_order: int, episode_number: int) -> int:
    """
    生成episode ID，格式：25 + animeid（6位）+ 源顺序（2位）+ 集编号（4位）
    按照弹幕库标准，animeId补0到6位
    例如：animeId=136 → episodeId=25000136010001
    """
    # 参数验证
    if anime_id is None or source_order is None or episode_number is None:
        raise ValueError(f"生成episodeId时参数不能为None: anime_id={anime_id}, source_order={source_order}, episode_number={episode_number}")

    # 按照弹幕库标准：animeId补0到6位
    # 格式化为：25 + 6位animeId + 2位源顺序 + 4位集编号
    episode_id = int(f"25{anime_id:06d}{source_order:02d}{episode_number:04d}")
    return episode_id

# 后备搜索函数将在模型定义后添加
# 新增：用于清理文件名中常见元数据关键词的正则表达式
METADATA_KEYWORDS_PATTERN = re.compile(
    r'1080p|720p|2160p|4k|bluray|x264|h\s*\.?\s*264|hevc|x265|h\s*\.?\s*265|aac|flac|web-dl|BDRip|WEBRip|TVRip|DVDrip|AVC|CHT|CHS|BIG5|GB|10bit|8bit',
    re.IGNORECASE
)

# 这个子路由将包含所有接口的实际实现。
# 它将被挂载到主路由的不同路径上。
implementation_router = APIRouter()

def _process_comments_for_dandanplay(comments_data: List[Dict[str, Any]]) -> List[models.Comment]:
    """
    将弹幕字典列表处理为符合 dandanplay 客户端规范的格式。
    核心逻辑是移除 p 属性中的字体大小参数，同时保留其他所有部分。
    原始格式: "时间,模式,字体大小,颜色,[来源]"
    目标格式: "时间,模式,颜色,[来源]"
    """
    processed_comments = []
    for i, item in enumerate(comments_data):
        p_attr = item.get("p", "")
        p_parts = p_attr.split(',')

        # 查找可选的用户标签（如[bilibili]），以确定核心参数的数量
        core_parts_count = len(p_parts)
        for j, part in enumerate(p_parts):
            if '[' in part and ']' in part:
                core_parts_count = j
                break
        
        if core_parts_count == 4:
            del p_parts[2] # 移除字体大小 (index 2)
        
        new_p_attr = ','.join(p_parts)
        processed_comments.append(models.Comment(cid=i, p=new_p_attr, m=item.get("m", "")))
    return processed_comments


class DandanApiRoute(APIRoute):
    """
    自定义的 APIRoute 类，用于为 dandanplay 兼容接口定制异常处理。
    捕获 HTTPException，并以 dandanplay API v2 的格式返回错误信息。
    """
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except HTTPException as exc:
                # 简单的 HTTP 状态码到 dandanplay 错误码的映射
                # 1001: 无效的参数
                # 1003: 未授权或资源不可用
                # 404: 未找到
                # 500: 服务器内部错误
                error_code_map = {
                    status.HTTP_400_BAD_REQUEST: 1001,
                    status.HTTP_422_UNPROCESSABLE_ENTITY: 1001,
                    # 新增：将404也映射到1003，对外统一表现为“资源不可用”
                    status.HTTP_404_NOT_FOUND: 1003,
                    status.HTTP_403_FORBIDDEN: 1003,
                    status.HTTP_500_INTERNAL_SERVER_ERROR: 500,
                }
                error_code = error_code_map.get(exc.status_code, 1003) # 默认客户端错误为1003

                # 为常见的错误代码提供更统一的错误消息
                error_message = "请求的资源不可用或您没有权限访问。" if error_code == 1003 else exc.detail

                # 始终返回 200 OK，错误信息在 JSON body 中体现
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "success": False,
                        "errorCode": error_code,
                        "errorMessage": error_message,
                    },
                )
        return custom_route_handler

async def get_config_manager(request: Request) -> ConfigManager:
    """依赖项：从应用状态获取配置管理器"""
    return request.app.state.config_manager

async def get_task_manager(request: Request) -> TaskManager:
    """依赖项：从应用状态获取任务管理器"""
    return request.app.state.task_manager

async def get_metadata_manager(request: Request) -> MetadataSourceManager:
    """依赖项：从应用状态获取元数据源管理器"""
    return request.app.state.metadata_manager

async def get_rate_limiter(request: Request) -> RateLimiter:
    """依赖项：从应用状态获取速率限制器"""
    return request.app.state.rate_limiter

# 这是将包含在 main.py 中的主路由。
# 使用自定义的 Route 类来应用特殊的异常处理。
dandan_router = APIRouter(route_class=DandanApiRoute)

class DandanResponseBase(BaseModel):
    """模仿 dandanplay API v2 的基础响应模型"""
    success: bool = True
    errorCode: int = 0
    errorMessage: str = Field("", description="错误信息")


class DandanEpisodeInfo(BaseModel):
    """dandanplay /search/episodes 接口中的分集信息模型"""
    episodeId: int
    episodeTitle: str

class DandanAnimeInfo(BaseModel):
    """dandanplay /search/episodes 接口中的番剧信息模型"""
    animeId: int
    animeTitle: str
    imageUrl: str = ""
    searchKeyword: str = ""
    type: str
    typeDescription: str
    isOnAir: bool = False
    airDay: int = 0
    isFavorited: bool = False
    rating: float = 0.0
    episodes: List[DandanEpisodeInfo]

class DandanSearchEpisodesResponse(DandanResponseBase):
    hasMore: bool = False
    animes: List[DandanAnimeInfo]

# --- Models for /search/anime ---
class DandanSearchAnimeItem(BaseModel):
    animeId: Optional[int] = None  # 支持后备搜索时animeId为None
    bangumiId: Optional[str] = ""
    animeTitle: str
    type: str
    typeDescription: str
    imageUrl: Optional[str] = None
    startDate: Optional[str] = None # To keep compatibility, but will be populated from year
    year: Optional[int] = None
    episodeCount: int
    rating: float = 0.0
    isFavorited: bool = False

class DandanSearchAnimeResponse(DandanResponseBase):
    animes: List[DandanSearchAnimeItem]


# --- Models for /bangumi/{anime_id} ---

class BangumiTitle(BaseModel):
    language: str
    title: str

class BangumiEpisodeSeason(BaseModel):
    id: str
    airDate: Optional[datetime] = None
    name: str
    episodeCount: int
    summary: str

class BangumiEpisode(BaseModel):
    seasonId: Optional[str] = None
    episodeId: int
    episodeTitle: str
    episodeNumber: str
    lastWatched: Optional[datetime] = None
    airDate: Optional[datetime] = None

class BangumiIntro(BaseModel):
    animeId: int
    bangumiId: Optional[str] = ""
    animeTitle: str
    imageUrl: Optional[str] = None
    searchKeyword: Optional[str] = None
    isOnAir: bool = False
    airDay: int = 0
    isRestricted: bool = False
    rating: float = 0.0

class BangumiTag(BaseModel):
    id: int
    name: str
    count: int

class BangumiOnlineDatabase(BaseModel):
    name: str
    url: str

class BangumiTrailer(BaseModel):
    id: int
    url: str
    title: str
    imageUrl: str
    date: datetime

class BangumiDetails(BangumiIntro):
    type: str
    typeDescription: str
    titles: List[BangumiTitle] = []
    seasons: List[BangumiEpisodeSeason] = []
    episodes: List[BangumiEpisode] = []
    summary: Optional[str] = ""
    metadata: List[str] = []
    year: Optional[int] = None
    userRating: int = 0
    favoriteStatus: Optional[str] = None
    comment: Optional[str] = None
    ratingDetails: Dict[str, float] = {}
    relateds: List[BangumiIntro] = []
    similars: List[BangumiIntro] = []
    tags: List[BangumiTag] = []
    onlineDatabases: List[BangumiOnlineDatabase] = []
    trailers: List[BangumiTrailer] = []

class BangumiDetailsResponse(DandanResponseBase):
    bangumi: Optional[BangumiDetails] = None

# --- Models for /match ---

class DandanMatchInfo(BaseModel):
    episodeId: int
    animeId: int
    animeTitle: str
    episodeTitle: str
    type: str
    typeDescription: str
    shift: int = 0
    imageUrl: Optional[str] = None

class DandanMatchResponse(DandanResponseBase):
    isMatched: bool = False
    matches: List[DandanMatchInfo] = []

# --- Models for /match/batch ---

class DandanBatchMatchRequestItem(BaseModel):
    fileName: str
    fileHash: Optional[str] = None
    fileSize: Optional[int] = None
    videoDuration: Optional[int] = None
    matchMode: Optional[str] = "hashAndFileName"

class DandanBatchMatchRequest(BaseModel):
    requests: List[DandanBatchMatchRequestItem]

# --- 后备搜索函数 ---

async def _handle_fallback_search(
    search_term: str,
    token: str,
    session: AsyncSession,
    scraper_manager: ScraperManager,
    metadata_manager: MetadataSourceManager,
    config_manager: ConfigManager,
    rate_limiter: RateLimiter,
    title_recognition_manager,
    task_manager: TaskManager
) -> DandanSearchAnimeResponse:
    """
    处理后备搜索逻辑
    """
    # 生成搜索任务的唯一标识
    search_key = f"search_{hash(search_term + token)}"

    # 检查该token是否已有正在进行的搜索任务
    existing_search_key = await _get_db_cache(session, TOKEN_SEARCH_TASKS_PREFIX, token)
    if existing_search_key:
        existing_search = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, existing_search_key)
        if existing_search and existing_search["status"] == "running":
            # 返回正在进行的搜索状态
            elapsed_time = time.time() - existing_search["start_time"]
            progress = min(int((elapsed_time / 60) * 100), 95)
            return DandanSearchAnimeResponse(animes=[
                DandanSearchAnimeItem(
                    animeId=999999999,
                    bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
                    animeTitle=f"{existing_search['search_term']} 搜索正在运行",
                    type="tvseries",
                    typeDescription=f"{progress}%",
                    imageUrl="/static/logo.png",
                    startDate="2025-01-01T00:00:00+08:00",
                    year=2025,
                    episodeCount=1,
                    rating=0.0,
                    isFavorited=False
                )
            ])

    # 首先检查是否有相关的后备匹配任务正在进行
    match_fallback_task = await _check_related_match_fallback_task(session, search_term)
    if match_fallback_task:
        # 返回后备匹配的进度信息，格式类似后备搜索
        progress = match_fallback_task['progress']
        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999999,
                bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
                animeTitle=f"{search_term} 匹配后备正在运行",
                type="tvseries",
                typeDescription=f"{progress}%",
                imageUrl="/static/logo.png",
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=1,
                rating=0.0,
                isFavorited=False
            )
        ])

    # 检查是否已有正在进行的搜索
    search_info = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
    if search_info:
        # 如果搜索已完成，返回结果
        if search_info["status"] == "completed":
            return DandanSearchAnimeResponse(animes=search_info["results"])

        # 如果搜索失败，返回空结果
        if search_info["status"] == "failed":
            return DandanSearchAnimeResponse(animes=[])

        # 如果搜索正在进行中，返回搜索状态
        if search_info["status"] == "running":
            elapsed_time = time.time() - search_info["start_time"]
            if elapsed_time >= 5:  # 5秒后返回搜索中状态
                progress = min(int((elapsed_time / 60) * 100), 95)  # 假设最多1分钟完成，最高95%
                return DandanSearchAnimeResponse(animes=[
                    DandanSearchAnimeItem(
                        animeId=999999999,  # 使用特定的不会冲突的数字
                        bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
                        animeTitle=f"{search_term} 搜索正在运行",
                        type="tvseries",
                        typeDescription=f"{progress}%",
                        imageUrl="/static/logo.png",
                        startDate="2025-01-01T00:00:00+08:00",
                        year=2025,
                        episodeCount=1,
                        rating=0.0,
                        isFavorited=False
                    )
                ])
            else:
                # 5秒内返回搜索启动状态
                return DandanSearchAnimeResponse(animes=[
                    DandanSearchAnimeItem(
                        animeId=999999999,
                        bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
                        animeTitle=f"{search_term} 搜索正在启动",
                        type="tvseries",
                        typeDescription="搜索正在启动",
                        imageUrl="/static/logo.png",
                        startDate="2025-01-01T00:00:00+08:00",
                        year=2025,
                        episodeCount=1,
                        rating=0.0,
                        isFavorited=False
                    )
                ])

    # 解析搜索词，提取季度和集数信息
    parsed_info = parse_search_keyword(search_term)

    # 启动新的搜索任务
    search_info = {
        "status": "running",
        "start_time": time.time(),
        "search_term": search_term,
        "parsed_info": parsed_info,  # 保存解析信息
        "results": []
    }
    await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info, FALLBACK_SEARCH_CACHE_TTL)

    # 记录该token正在执行的搜索任务
    await _set_db_cache(session, TOKEN_SEARCH_TASKS_PREFIX, token, search_key, TOKEN_SEARCH_TASKS_TTL)

    # 通过任务管理器提交后备搜索任务
    async def fallback_search_coro_factory(session_inner: AsyncSession, progress_callback):
        """后备搜索任务的协程工厂"""
        try:
            # 执行搜索任务
            await _execute_fallback_search_task(
                search_term, search_key, token, session_inner, progress_callback,
                scraper_manager, metadata_manager, config_manager,
                rate_limiter, title_recognition_manager
            )
        except Exception as e:
            logger.error(f"后备搜索任务执行失败: {e}", exc_info=True)
            # 更新缓存状态为失败
            search_info_failed = await _get_db_cache(session_inner, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
            if search_info_failed:
                search_info_failed["status"] = "failed"
                await _set_db_cache(session_inner, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info_failed, FALLBACK_SEARCH_CACHE_TTL)
        finally:
            # 清理token搜索任务记录
            existing_token_key = await _get_db_cache(session_inner, TOKEN_SEARCH_TASKS_PREFIX, token)
            if existing_token_key == search_key:
                await _delete_db_cache(session_inner, TOKEN_SEARCH_TASKS_PREFIX, token)

    # 提交后备搜索任务(立即执行模式)
    try:
        task_title = f"后备搜索: {search_term}"
        task_id, done_event = await task_manager.submit_task(
            fallback_search_coro_factory,
            task_title,
            run_immediately=True,
            queue_type="fallback"
        )
        logger.info(f"后备搜索任务已提交: {task_id}")
    except Exception as e:
        logger.error(f"提交后备搜索任务失败: {e}", exc_info=True)
        search_info["status"] = "failed"
        return DandanSearchAnimeResponse(animes=[])

    # 立即返回"搜索中"状态，让用户知道搜索正在进行
    return DandanSearchAnimeResponse(animes=[
        DandanSearchAnimeItem(
            animeId=999999999,  # 使用特定的不会冲突的数字
            bangumiId=str(FALLBACK_SEARCH_BANGUMI_ID),
            animeTitle=f"{search_term} 搜索正在启动",
            type="tvseries",
            typeDescription="0%",
            imageUrl="/static/logo.png",
            startDate="2025-01-01T00:00:00+08:00",
            year=2025,
            episodeCount=1,
            rating=0.0,
            isFavorited=False
        )
    ])

async def _execute_fallback_search_task(
    search_term: str,
    search_key: str,
    token: str,
    session: AsyncSession,
    progress_callback,
    scraper_manager: ScraperManager,
    metadata_manager: MetadataSourceManager,
    config_manager: ConfigManager,
    rate_limiter: RateLimiter,
    title_recognition_manager
):
    """执行后备搜索任务。"""
    try:
        # 1. 解析搜索词，提取基础标题 / 季度 / 集数信息
        parsed_info = parse_search_keyword(search_term)
        original_title = parsed_info["title"]
        season_to_filter = parsed_info.get("season")
        episode_to_filter = parsed_info.get("episode")

        # 2. 应用与 WebUI 一致的标题预处理规则
        search_title = original_title
        if title_recognition_manager:
            (
                processed_title,
                processed_episode,
                processed_season,
                preprocessing_applied,
            ) = await title_recognition_manager.apply_search_preprocessing(
                original_title, episode_to_filter, season_to_filter
            )
            if preprocessing_applied:
                search_title = processed_title
                logger.info(
                    f"✓ 后备搜索预处理: '{original_title}' -> '{search_title}'"
                )
                if processed_episode != episode_to_filter:
                    logger.info(
                        f"✓ 后备搜索集数预处理: {episode_to_filter} -> {processed_episode}"
                    )
                    episode_to_filter = processed_episode
                if processed_season != season_to_filter:
                    logger.info(
                        f"✓ 后备搜索季度预处理: {season_to_filter} -> {processed_season}"
                    )
                    season_to_filter = processed_season
            else:
                logger.info(f"○ 后备搜索预处理未生效: '{original_title}'")
        else:
            logger.info("○ 未配置标题识别管理器，跳过后备搜索预处理。")

        # 3. 同步更新缓存中的 parsed_info，确保后续 /api/v2/bangumi 使用预处理后的季/集信息
        search_info = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
        if search_info:
            cached_parsed = search_info.get("parsed_info") or {}
            cached_parsed["season"] = season_to_filter
            cached_parsed["episode"] = episode_to_filter
            cached_parsed["title"] = search_title
            search_info["parsed_info"] = cached_parsed
            await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info, FALLBACK_SEARCH_CACHE_TTL)

        # 4. 构造 episode_info，使后备搜索与 WebUI 搜索在分集维度保持一致
        episode_info = (
            {"season": season_to_filter, "episode": episode_to_filter}
            if episode_to_filter is not None
            else None
        )

        # 更新进度
        await progress_callback(10, "开始搜索...")

        # 4. 使用统一的搜索函数
        #    - 使用预处理后的 search_title
        #    - 传入 episode_info
        #    - 将别名相似度阈值调整为 70，与 WebUI 匹配
        sorted_results = await unified_search(
            search_term=search_title,
            session=session,
            scraper_manager=scraper_manager,
            metadata_manager=metadata_manager,
            use_alias_expansion=True,
            use_alias_filtering=True,
            use_title_filtering=True,
            use_source_priority_sorting=True,
            progress_callback=progress_callback,
            episode_info=episode_info,
            alias_similarity_threshold=70,
        )

        # 5. 根据标题关键词修正媒体类型（与 WebUI 一致）
        def is_movie_by_title(title: str) -> bool:
            if not title:
                return False
            # 关键词列表，不区分大小写
            movie_keywords = ["剧场版", "劇場版", "movie", "映画"]
            title_lower = title.lower()
            return any(keyword in title_lower for keyword in movie_keywords)

        for item in sorted_results:
            if item.type == "tv_series" and is_movie_by_title(item.title):
                logger.info(
                    f"标题 '{item.title}' 包含电影关键词，类型从 'tv_series' 修正为 'movie'。"
                )
                item.type = "movie"

        # 6. 如果搜索词中明确指定了季度，对结果进行过滤（与 WebUI 一致）
        if season_to_filter:
            original_count = len(sorted_results)
            # 当指定季度时，我们只关心电视剧类型
            filtered_by_type = [item for item in sorted_results if item.type == "tv_series"]

            # 然后在电视剧类型中，我们按季度号过滤
            filtered_by_season = [
                item for item in filtered_by_type if item.season == season_to_filter
            ]

            logger.info(
                f"根据指定的季度 ({season_to_filter}) 进行过滤，从 {original_count} 个结果中保留了 {len(filtered_by_season)} 个。"
            )
            sorted_results = filtered_by_season

        # 7. 转换为DandanSearchAnimeItem格式
        await progress_callback(80, "转换搜索结果...")
        search_results = []

        # 获取下一个虚拟animeId（6位数字，用于显示）
        next_virtual_anime_id = await _get_next_virtual_anime_id(session)

        for i, result in enumerate(sorted_results):
            # 为每个搜索结果分配一个虚拟animeId
            current_virtual_anime_id = next_virtual_anime_id + i

            # 使用弹幕库现有的格式：A + 虚拟animeId
            unique_bangumi_id = f"A{current_virtual_anime_id}"

            # 在标题后面添加来源和年份信息
            year_info = f" 年份：{result.year}" if result.year else ""
            title_with_source = f"{result.title} （来源：{result.provider}{year_info}）"

            # 存储bangumiId到原始信息的映射
            search_info_mapping = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
            if search_info_mapping:
                if "bangumi_mapping" not in search_info_mapping:
                    search_info_mapping["bangumi_mapping"] = {}
                search_info_mapping["bangumi_mapping"][unique_bangumi_id] = {
                    "provider": result.provider,
                    "media_id": result.mediaId,
                    "original_title": result.title,
                    "type": result.type,
                    "anime_id": current_virtual_anime_id,  # 存储虚拟animeId
                }
                await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info_mapping, FALLBACK_SEARCH_CACHE_TTL)

            # 检查库内是否已有相同标题的分集
            base_type_desc = DANDAN_TYPE_DESC_MAPPING.get(result.type, "其他")
            type_description = base_type_desc

            try:
                # 查询库内已有的分集信息
                existing_episodes = await crud.get_episode_indices_by_anime_title(
                    session, result.title
                )
                if existing_episodes:
                    # 将分集列表转换为简洁的范围表示
                    episode_ranges = _format_episode_ranges(existing_episodes)
                    type_description = f"{base_type_desc}（库内：{episode_ranges}）"
            except Exception as e:
                logger.debug(f"查询库内分集信息失败: {e}")
                # 如果查询失败，使用原始描述
                type_description = base_type_desc

            search_results.append(
                DandanSearchAnimeItem(
                    animeId=current_virtual_anime_id,  # 使用虚拟animeId
                    bangumiId=unique_bangumi_id,
                    animeTitle=title_with_source,
                    type=DANDAN_TYPE_MAPPING.get(result.type, "other"),
                    typeDescription=type_description,
                    imageUrl=result.imageUrl,
                    startDate=f"{result.year}-01-01T00:00:00+08:00"
                    if result.year
                    else None,
                    year=result.year,
                    episodeCount=result.episodeCount or 0,
                    rating=0.0,
                    isFavorited=False,
                )
            )

        await progress_callback(90, "整理搜索结果...")

        # 更新缓存状态为完成
        search_info_complete = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
        if search_info_complete:
            search_info_complete["status"] = "completed"
            search_info_complete["results"] = search_results
            await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info_complete, FALLBACK_SEARCH_CACHE_TTL)

        # 将搜索结果存储到数据库缓存中（与WebUI搜索一致）
        try:
            # 提取核心标题（去除季度和集数信息）
            parsed = parse_search_keyword(search_term)
            core_title = parsed["title"]

            # 使用核心标题作为缓存键，这样同一剧的不同集数可以共享缓存
            cache_key = f"fallback_search_{core_title}"

            # 将搜索结果转换为可缓存的格式
            cache_data = {
                "search_term": core_title,
                "results": [result.model_dump() for result in search_results],
                "timestamp": time.time(),
            }

            # 存储到数据库缓存（10分钟过期）
            await crud.set_cache(session, cache_key, json.dumps(cache_data), ttl_seconds=600)
            logger.info(
                f"后备搜索结果已存储到数据库缓存: {cache_key} (原始搜索词: {search_term})"
            )

        except Exception as e:
            logger.warning(f"存储后备搜索结果到数据库缓存失败: {e}")

        await progress_callback(100, "搜索完成")

    except Exception as e:
        logger.error(f"后备搜索任务执行失败: {e}", exc_info=True)
        # 更新缓存状态为失败
        search_info_failed = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
        if search_info_failed:
            search_info_failed["status"] = "failed"
            await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info_failed, FALLBACK_SEARCH_CACHE_TTL)
    finally:
        # 清理token搜索任务记录
        existing_token_key = await _get_db_cache(session, TOKEN_SEARCH_TASKS_PREFIX, token)
        if existing_token_key == search_key:
            await _delete_db_cache(session, TOKEN_SEARCH_TASKS_PREFIX, token)

async def _search_implementation(
    search_term: str,
    episode: Optional[str],
    session: AsyncSession
) -> DandanSearchEpisodesResponse:
    """搜索接口的通用实现，避免代码重复。"""
    search_term = search_term.strip()
    if not search_term:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required query parameter: 'anime' or 'keyword'"
        )

    # 修正：调用 utils 中的全局解析函数，以保持逻辑统一
    parsed_info = parse_search_keyword(search_term)
    title_to_search = parsed_info["title"]
    season_to_search = parsed_info.get("season")
    episode_from_title = parsed_info.get("episode")

    # 优先使用独立的 'episode' 参数
    episode_number_from_param = int(episode) if episode and episode.isdigit() else None
    final_episode_to_search = episode_number_from_param if episode_number_from_param is not None else episode_from_title

    # 使用解析后的信息进行数据库查询
    flat_results = await crud.search_episodes_in_library(
        session,
        anime_title=title_to_search,
        episode_number=final_episode_to_search,
        season_number=season_to_search
    )

    grouped_animes: Dict[int, DandanAnimeInfo] = {}

    for res in flat_results:
        anime_id = res['animeId']
        if anime_id not in grouped_animes:
            dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
            dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")

            grouped_animes[anime_id] = DandanAnimeInfo(
                animeId=anime_id,
                animeTitle=res['animeTitle'],
                imageUrl=res.get('imageUrl') or "",
                searchKeyword=search_term or "",
                type=dandan_type,
                typeDescription=dandan_type_desc,
                # isFavorited 字段现在由数据库查询提供
                isFavorited=res.get('isFavorited', False),
                episodes=[]
            )
        
        grouped_animes[anime_id].episodes.append(
            DandanEpisodeInfo(episodeId=res['episodeId'], episodeTitle=res['episodeTitle'])
        )
    
    return DandanSearchEpisodesResponse(animes=list(grouped_animes.values()))

def _parse_filename_for_match(filename: str) -> Optional[Dict[str, Any]]:
    """
    使用正则表达式从文件名中解析出番剧标题和集数。
    这是一个简化的实现，用于 dandanplay 兼容接口。
    """
    # 移除文件扩展名
    name_without_ext = filename.rsplit('.', 1)[0] if '.' in filename else filename

    # 模式1: SXXEXX 格式 (e.g., "Some.Anime.S01E02.1080p.mkv")
    s_e_pattern = re.compile(
        r"^(?P<title>.+?)"
        r"[\s._-]*"
        r"[Ss](?P<season>\d{1,2})"
        r"[Ee](?P<episode>\d{1,4})"
        r"\b",
        re.IGNORECASE
    )
    match = s_e_pattern.search(name_without_ext)
    if match:
        data = match.groupdict()
        title = data["title"].replace(".", " ").replace("_", " ").strip()
        title = re.sub(r'\[.*?\]', '', title).strip() # 移除字幕组标签
        # 新增：移除标题中的年份并清理多余空格
        title = re.sub(r'\b(19|20)\d{2}\b', '', title).strip()
        title = re.sub(r'\s+', ' ', title).strip(' -')
        return {
            "title": title,
            "season": int(data["season"]),
            "episode": int(data["episode"])
        }

    # 模式2: 只有集数 (e.g., "[Subs] Some Anime - 02 [1080p].mkv")
    ep_only_patterns = [
        re.compile(r"^(?P<title>.+?)\s*[-_]\s*\b(?P<episode>\d{1,4})\b", re.IGNORECASE),
        re.compile(r"^(?P<title>.+?)\s+\b(?P<episode>\d{1,4})\b", re.IGNORECASE),
    ]
    for pattern in ep_only_patterns:
        match = pattern.search(name_without_ext)
        if match:
            data = match.groupdict()
            title = data["title"]
            # 清理标题中的元数据
            title = re.sub(r'\[.*?\]|\(.*?\)|\【.*?\】', '', title).strip()
            title = METADATA_KEYWORDS_PATTERN.sub('', title).strip()
            title = title.replace("_", " ").replace(".", " ").strip()
            # 新增：移除标题中的年份并清理多余空格
            title = re.sub(r'\b(19|20)\d{2}\b', '', title).strip()
            title = re.sub(r'\s+', ' ', title).strip(' -')
            return {
                "title": title,
                "season": None, # 此模式无法识别季度
                "episode": int(data["episode"]),
            }
    
    # 模式3: 电影或单文件视频 (没有集数)
    title = name_without_ext
    title = re.sub(r'\[.*?\]|\(.*?\)|\【.*?\】', '', title).strip()
    title = METADATA_KEYWORDS_PATTERN.sub('', title).strip()
    title = title.replace("_", " ").replace(".", " ").strip()
    # 移除年份, 兼容括号内和独立两种形式
    title = re.sub(r'\(\s*(19|20)\d{2}\s*\)', '', title).strip()
    title = re.sub(r'\b(19|20)\d{2}\b', '', title).strip()
    title = re.sub(r'\s+', ' ', title).strip(' -')

    if title:
        return {
            "title": title,
            "season": None,  # 电影不设置季度
            "episode": None, # 电影不设置集数
            "is_movie": True # 标记为电影
        }

    return None


async def get_token_from_path(
    request: Request,
    token: str = Path(..., description="路径中的API授权令牌"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    一个 FastAPI 依赖项，用于验证路径中的 token。
    这是为 dandanplay 客户端设计的特殊鉴权方式。
    此函数现在还负责UA过滤和访问日志记录。
    """
    # --- 新增：解析真实客户端IP ---
    # --- 新增：解析真实客户端IP，支持CIDR ---
    config_manager: ConfigManager = request.app.state.config_manager
    trusted_proxies_str = await config_manager.get("trustedProxies", "")
    trusted_networks = []
    if trusted_proxies_str:
        for proxy_entry in trusted_proxies_str.split(','):
            try:
                trusted_networks.append(ipaddress.ip_network(proxy_entry.strip()))
            except ValueError:
                logger.warning(f"无效的受信任代理IP或CIDR: '{proxy_entry.strip()}'，已忽略。")
    
    client_ip_str = request.client.host if request.client else "127.0.0.1"
    is_trusted = False
    if trusted_networks:
        try:
            client_addr = ipaddress.ip_address(client_ip_str)
            is_trusted = any(client_addr in network for network in trusted_networks)
        except ValueError:
            logger.warning(f"无法将客户端IP '{client_ip_str}' 解析为有效的IP地址。")

    if is_trusted:
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            client_ip_str = x_forwarded_for.split(',')[0].strip()
        else:
            # 如果没有 X-Forwarded-For，则回退到 X-Real-IP
            client_ip_str = request.headers.get("x-real-ip", client_ip_str)
    # --- IP解析结束 ---

    # 1. 验证 token 是否存在、启用且未过期
    request_path = request.url.path
    log_path = re.sub(r'^/api/v1/[^/]+', '', request_path) # 从路径中移除 /api/v1/{token} 部分

    token_info = await crud.validate_api_token(session, token=token)
    if not token_info: 
        # 尝试记录失败的访问
        token_record = await crud.get_api_token_by_token_str(session, token)
        if token_record:
            expires_at = token_record.get('expiresAt')
            is_expired = False
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=get_app_timezone())
                is_expired = expires_at < get_now()
            status_to_log = 'denied_expired' if is_expired else 'denied_disabled'
            await crud.create_token_access_log(session, token_record['id'], client_ip_str, request.headers.get("user-agent"), log_status=status_to_log, path=log_path)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API token")

    # 2. UA 过滤
    ua_filter_mode = await crud.get_config_value(session, 'uaFilterMode', 'off')
    user_agent = request.headers.get("user-agent", "")

    if ua_filter_mode != 'off':
        ua_rules = await crud.get_ua_rules(session)
        ua_list = [rule['uaString'] for rule in ua_rules]
        
        is_matched = any(rule in user_agent for rule in ua_list)

        if ua_filter_mode == 'blacklist' and is_matched:
            await crud.create_token_access_log(session, token_info['id'], client_ip_str, user_agent, log_status='denied_ua_blacklist', path=log_path)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User-Agent is blacklisted")
        
        if ua_filter_mode == 'whitelist' and not is_matched:
            await crud.create_token_access_log(session, token_info['id'], client_ip_str, user_agent, log_status='denied_ua_whitelist', path=log_path)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User-Agent not in whitelist")

    # 3. 增加调用计数 (在所有验证通过后)
    await crud.increment_token_call_count(session, token_info['id'])
    await session.commit()

    # 3. 记录成功访问
    await crud.create_token_access_log(session, token_info['id'], client_ip_str, user_agent, log_status='allowed', path=log_path)

    return token

async def get_scraper_manager(request: Request) -> ScraperManager:
    """依赖项：从应用状态获取 Scraper 管理器"""
    return request.app.state.scraper_manager

@implementation_router.get(
    "/search/episodes",
    response_model=DandanSearchEpisodesResponse,
    summary="[dandanplay兼容] 搜索节目和分集"
)
async def search_episodes_for_dandan(
    anime: str = Query(..., description="节目名称"),
    episode: Optional[str] = Query(None, description="分集标题 (通常是数字)"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session)
):
    """
    模拟 dandanplay 的 /api/v2/search/episodes 接口。
    它会搜索 **本地弹幕库** 中的番剧和分集信息。
    """
    search_term = anime.strip()
    return await _search_implementation(search_term, episode, session)

@implementation_router.get(
    "/search/anime",
    response_model=DandanSearchAnimeResponse,
    summary="[dandanplay兼容] 搜索作品"
)
async def search_anime_for_dandan(
    keyword: Optional[str] = Query(None, description="节目名称 (兼容 keyword)"),
    anime: Optional[str] = Query(None, description="节目名称 (兼容 anime)"),
    episode: Optional[str] = Query(None, description="分集标题 (此接口中未使用)"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    config_manager: ConfigManager = Depends(get_config_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    title_recognition_manager = Depends(get_title_recognition_manager),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """
    模拟 dandanplay 的 /api/v2/search/anime 接口。
    它会搜索 **本地弹幕库** 中的番剧信息，不包含分集列表。
    新增：支持后备搜索功能，当库内无结果或指定集数不存在时，触发全网搜索。
    支持SXXEXX格式的季度和集数搜索。
    """
    search_term = keyword or anime
    if not search_term:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required query parameter: 'keyword' or 'anime'"
        )

    # 解析搜索关键词，提取标题、季数和集数
    parsed_info = parse_search_keyword(search_term)
    title_to_search = parsed_info["title"]
    season_to_search = parsed_info.get("season")
    episode_to_search = parsed_info.get("episode")

    # 首先搜索本地库
    db_results = await crud.search_animes_for_dandan(session, search_term)

    # 如果指定了具体集数，需要检查该集数是否存在
    should_trigger_fallback = False
    if db_results and episode_to_search is not None:
        # 检查是否存在指定的集数
        episode_exists = False
        for anime_result in db_results:
            anime_id = anime_result['animeId']
            # 查询该番剧的所有分集
            episodes = await crud.search_episodes_in_library(
                session,
                anime_title=title_to_search,
                episode_number=episode_to_search,
                season_number=season_to_search
            )
            if episodes:
                episode_exists = True
                break

        if not episode_exists:
            logger.info(f"本地库中找到番剧但不存在指定集数 E{episode_to_search:02d}，将触发后备搜索")
            should_trigger_fallback = True

    # 如果本地库有结果且不需要触发后备搜索，直接返回
    if db_results and not should_trigger_fallback:
        animes = []
        for res in db_results:
            dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
            dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
            year = res.get('year')
            start_date_str = None
            if year:
                start_date_str = datetime(year, 1, 1, tzinfo=get_app_timezone()).isoformat()
            elif res.get('startDate'):
                start_date_str = res.get('startDate').isoformat()

            animes.append(DandanSearchAnimeItem(
                animeId=res['animeId'],
                bangumiId=res.get('bangumiId') or f"A{res['animeId']}",
                animeTitle=res['animeTitle'],
                type=dandan_type,
                typeDescription=dandan_type_desc,
                imageUrl=res.get('imageUrl'),
                startDate=start_date_str,
                year=year,
                episodeCount=res.get('episodeCount', 0),
                rating=0.0,
                isFavorited=False
            ))
        return DandanSearchAnimeResponse(animes=animes)

    # 如果本地库无结果或需要触发后备搜索，检查是否启用了后备搜索
    search_fallback_enabled = await config_manager.get("searchFallbackEnabled", "false")
    if search_fallback_enabled.lower() == 'true' and (not db_results or should_trigger_fallback):
        # 检查Token是否被允许使用后备搜索功能
        try:
            # 获取当前token的信息
            token_stmt = select(orm_models.ApiToken).where(orm_models.ApiToken.token == token)
            token_result = await session.execute(token_stmt)
            current_token_obj = token_result.scalar_one_or_none()

            if current_token_obj:
                # 获取允许的token列表
                allowed_tokens_str = await config_manager.get("matchFallbackTokens", "[]")
                allowed_token_ids = json.loads(allowed_tokens_str)

                # 如果配置了允许的token列表且当前token不在列表中，跳过后备搜索
                if allowed_token_ids and current_token_obj.id not in allowed_token_ids:
                    logger.info(f"Token '{current_token_obj.name}' (ID: {current_token_obj.id}) 未被授权使用后备搜索功能，跳过后备搜索。")
                    return DandanSearchAnimeResponse(animes=[])
                else:
                    logger.info(f"Token '{current_token_obj.name}' (ID: {current_token_obj.id}) 已被授权使用后备搜索功能。")
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"检查后备搜索Token授权时发生错误: {e}，继续执行后备搜索")

        # 使用解析后的标题进行后备搜索，但保留原始搜索词用于缓存键
        search_title_for_fallback = title_to_search
        if episode_to_search is not None:
            # 如果指定了集数，在后备搜索中包含季度和集数信息
            if season_to_search is not None:
                search_title_for_fallback = f"{title_to_search} S{season_to_search:02d}E{episode_to_search:02d}"
            else:
                search_title_for_fallback = f"{title_to_search} E{episode_to_search:02d}"
        elif season_to_search is not None:
            search_title_for_fallback = f"{title_to_search} S{season_to_search:02d}"

        return await _handle_fallback_search(
            search_title_for_fallback, token, session, scraper_manager,
            metadata_manager, config_manager, rate_limiter, title_recognition_manager,
            task_manager
        )

    # 本地库无结果且未启用后备搜索，返回空结果
    return DandanSearchAnimeResponse(animes=[])

@implementation_router.get(
    "/bangumi/{bangumiId}",
    response_model=BangumiDetailsResponse,
    summary="[dandanplay兼容] 获取番剧详情"
)
async def get_bangumi_details(
    bangumiId: str = Path(..., description="作品ID, A开头的备用ID, 或真实的Bangumi ID"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    scraper_manager: ScraperManager = Depends(get_scraper_manager)
):
    """
    模拟 dandanplay 的 /api/v2/bangumi/{bangumiId} 接口。
    返回数据库中存储的番剧详细信息。
    新增：处理后备搜索的特殊bangumiId。
    """
    # 检查是否是搜索中的固定bangumiId
    if bangumiId == str(FALLBACK_SEARCH_BANGUMI_ID):
        return BangumiDetailsResponse(
            success=False,
            bangumi=None,
            errorMessage="搜索正在进行，请耐心等待"
        )





    anime_id_int: Optional[int] = None
    if bangumiId.startswith('A') and bangumiId[1:].isdigit():
        # 格式1: "A" + animeId, 例如 "A123"
        anime_id_int = int(bangumiId[1:])

        # 检查是否是后备搜索的虚拟animeId范围（900000-999999）
        if 900000 <= anime_id_int < 1000000:
            # 从数据库缓存中查找所有搜索结果
            try:
                all_cache_keys = await crud.get_cache_keys_by_pattern(session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
                for cache_key in all_cache_keys:
                    search_key = cache_key.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
                    search_info = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)

                    if search_info and search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
                        if bangumiId in search_info["bangumi_mapping"]:
                            mapping_info = search_info["bangumi_mapping"][bangumiId]
                            provider = mapping_info["provider"]
                            media_id = mapping_info["media_id"]
                            original_title = mapping_info["original_title"]
                            anime_id = mapping_info["anime_id"]

                            # 记录用户最后选择的虚拟bangumiId
                            await _set_db_cache(session, USER_LAST_BANGUMI_CHOICE_PREFIX, search_key, bangumiId, USER_LAST_BANGUMI_CHOICE_TTL)
                            logger.info(f"记录用户选择: search_key={search_key}, bangumiId={bangumiId}, provider={provider}")

                            # 获取原始搜索的季度和集数信息
                            parsed_info = search_info.get("parsed_info", {})
                            target_season = parsed_info.get("season")
                            target_episode = parsed_info.get("episode")

                            episodes = []
                            try:
                                # 完全按照WebUI的流程：调用scraper获取真实的分集信息
                                scraper = scraper_manager.get_scraper(provider)
                                if scraper:
                                    # 从映射信息中获取media_type
                                    media_type = None
                                    all_cache_keys_inner = await crud.get_cache_keys_by_pattern(session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
                                    for cache_key_inner in all_cache_keys_inner:
                                        search_key_inner = cache_key_inner.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
                                        search_info_inner = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key_inner)

                                        if search_info_inner and search_info_inner.get("status") == "completed" and "bangumi_mapping" in search_info_inner:
                                            for bangumi_id_inner, mapping_info_inner in search_info_inner["bangumi_mapping"].items():
                                                if mapping_info_inner.get("anime_id") == anime_id:
                                                    media_type = mapping_info_inner.get("type")
                                                    break
                                            if media_type:
                                                break

                                    # 使用与WebUI完全相同的调用方式
                                    actual_episodes = await scraper.get_episodes(media_id, db_media_type=media_type)

                                    if actual_episodes:
                                        # 检查是否已经有相同剧集的记录（源切换检测）
                                        existing_anime = await _find_existing_anime_by_bangumi_id(session, bangumiId, search_key)

                                        if existing_anime:
                                            # 找到现有剧集，这是源切换行为
                                            real_anime_id = existing_anime['animeId']
                                            logger.info(f"检测到源切换: 剧集'{original_title}' 已存在 (anime_id={real_anime_id})，将更新映射到新源 {provider}")

                                            # 更新现有episodeId的映射关系
                                            for i, episode_data in enumerate(actual_episodes):
                                                episode_id = _generate_episode_id(real_anime_id, 1, i + 1)
                                                await _update_episode_mapping(
                                                    session, episode_id, provider, media_id,
                                                    i + 1, original_title
                                                )
                                            logger.info(f"源切换: '{original_title}' 更新 {len(actual_episodes)} 个分集映射到 {provider}")
                                        else:
                                            # 新剧集，先检查数据库中是否已有相同标题的条目
                                            # 解析搜索关键词，提取纯标题
                                            parsed_info = parse_search_keyword(original_title)
                                            base_title = parsed_info["title"]

                                            # 直接在数据库中查找相同标题的条目
                                            stmt = select(Anime.id, Anime.title).where(
                                                Anime.title == base_title,
                                                Anime.season == 1
                                            )
                                            result = await session.execute(stmt)
                                            existing_db_anime = result.mappings().first()

                                            if existing_db_anime:
                                                # 如果数据库中已有相同标题的条目，使用已有的anime_id
                                                real_anime_id = existing_db_anime['id']
                                                logger.info(f"复用已存在的番剧: '{base_title}' (ID={real_anime_id}) 共 {len(actual_episodes)} 集")
                                            else:
                                                # 如果数据库中没有，获取新的真实animeId
                                                real_anime_id = await _get_next_real_anime_id(session)
                                                logger.info(f"新剧集: '{base_title}' (ID={real_anime_id}) 共 {len(actual_episodes)} 集")

                                        # 清除缓存中所有使用这个real_anime_id的其他映射（避免冲突）
                                        all_cache_keys_conflict = await crud.get_cache_keys_by_pattern(session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
                                        for cache_key_conflict in all_cache_keys_conflict:
                                            sk = cache_key_conflict.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
                                            si = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, sk)
                                            if si and si.get("status") == "completed" and "bangumi_mapping" in si:
                                                for bid, mi in list(si["bangumi_mapping"].items()):
                                                    # 如果是其他映射使用了相同的real_anime_id，清除它
                                                    if mi.get("real_anime_id") == real_anime_id and bid != bangumiId:
                                                        del si["bangumi_mapping"][bid]
                                                        logger.info(f"清除冲突的缓存映射: search_key={sk}, bangumiId={bid}, real_anime_id={real_anime_id}")
                                                # 保存更新后的缓存
                                                await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, sk, si, FALLBACK_SEARCH_CACHE_TTL)

                                        # 存储真实animeId到虚拟animeId的映射关系
                                        mapping_info["real_anime_id"] = real_anime_id
                                        # 更新缓存中的映射信息
                                        search_info["bangumi_mapping"][bangumiId] = mapping_info
                                        await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info, FALLBACK_SEARCH_CACHE_TTL)

                                        for i, episode_data in enumerate(actual_episodes):
                                            episode_index = i + 1

                                            # 如果指定了特定集数，只返回该集数
                                            if target_episode is not None and episode_index != target_episode:
                                                continue

                                            # 使用真实animeId生成标准的episodeId
                                            episode_id = _generate_episode_id(real_anime_id, 1, episode_index)
                                            # 直接使用原始分集标题
                                            episode_title = episode_data.title

                                            # 只有在新剧集时才存储映射关系（源切换时已经在上面更新了）
                                            if not existing_anime:
                                                await _store_episode_mapping(
                                                    session, episode_id, provider, media_id,
                                                    episode_index, original_title
                                                )

                                            episodes.append(BangumiEpisode(
                                                episodeId=episode_id,
                                                episodeTitle=episode_title,
                                                episodeNumber=str(episode_data.episodeIndex if episode_data.episodeIndex else episode_index)
                                            ))

                                    else:
                                        logger.warning(f"从 {provider} 获取分集列表为空: media_id={media_id}")
                                else:
                                    logger.error(f"找不到 {provider} 的scraper")

                            except Exception as e:
                                logger.error(f"获取分集列表失败: {e}")
                                episodes = []

                            bangumi_details = BangumiDetails(
                                animeId=anime_id,  # 使用分配的animeId
                                bangumiId=bangumiId,
                                animeTitle=f"{original_title} （来源：{provider}）",
                                imageUrl="/static/logo.png",
                                searchKeyword=original_title,
                                type="other",
                                typeDescription="其他",
                                episodes=episodes,
                                year=2025,
                                summary=f"来自后备搜索的结果 (源: {provider})",
                            )

                            return BangumiDetailsResponse(bangumi=bangumi_details)
            except Exception as e:
                logger.error(f"查找后备搜索缓存失败: {e}")
                # 如果查找失败,继续执行后续逻辑
                pass

            # 如果没找到对应的后备搜索ID，但在范围内，返回过期信息
            if 900000 <= anime_id_int < 1000000:
                return BangumiDetailsResponse(
                    success=True,
                    bangumi=None,
                    errorMessage="搜索结果不存在或已过期"
                )

    elif bangumiId.isdigit():
        # 格式2: 纯数字的 Bangumi ID, 例如 "148099"
        # 我们需要通过 bangumi_id 找到我们自己数据库中的 anime_id
        anime_id_int = await crud.get_anime_id_by_bangumi_id(session, bangumiId)


    if anime_id_int is None:
        return BangumiDetailsResponse(
            success=True,
            bangumi=None,
            errorMessage=f"找不到与标识符 '{bangumiId}' 关联的作品。"
        )

    details = await crud.get_anime_details_for_dandan(session, anime_id_int)
    if not details:
        return BangumiDetailsResponse(
            success=True,
            bangumi=None,
            errorMessage=f"在数据库中找不到ID为 {anime_id_int} 的作品详情。"
        )

    anime_data = details['anime']
    episodes_data = details['episodes']

    dandan_type = DANDAN_TYPE_MAPPING.get(anime_data.get('type'), "other")
    dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(anime_data.get('type'), "其他")

    formatted_episodes = [
        BangumiEpisode(
            episodeId=ep['episodeId'],
            episodeTitle=ep['episodeTitle'],
            episodeNumber=str(ep['episodeNumber'])
        ) for ep in episodes_data
    ]

    bangumi_id_str = anime_data.get('bangumiId') or f"A{anime_data['animeId']}"

    bangumi_details = BangumiDetails(
        animeId=anime_data['animeId'],
        bangumiId=bangumi_id_str,
        animeTitle=anime_data['animeTitle'],
        imageUrl=anime_data.get('imageUrl'),
        searchKeyword=anime_data['animeTitle'],
        type=dandan_type,
        typeDescription=dandan_type_desc,
        episodes=formatted_episodes,
        year=anime_data.get('year'),
        summary="暂无简介",
    )

    return BangumiDetailsResponse(bangumi=bangumi_details)

async def _get_match_for_item(
    item: DandanBatchMatchRequestItem,
    session: AsyncSession,
    task_manager: TaskManager,
    scraper_manager: ScraperManager,
    metadata_manager: MetadataSourceManager,
    config_manager: ConfigManager,
    rate_limiter: RateLimiter,
    title_recognition_manager,
    current_token: Optional[str] = None
) -> DandanMatchResponse:
    """
    通过文件名匹配弹幕库的核心逻辑。此接口不使用文件Hash。
    优先进行库内直接匹配，失败后回退到TMDB剧集组映射。
    新增：如果所有匹配都失败，且启用了后备机制，则触发自动搜索导入任务。
    """
    logger.info(f"执行匹配逻辑, 文件名: '{item.fileName}'")
    parsed_info = _parse_filename_for_match(item.fileName)
    logger.info(f"文件名解析结果: {parsed_info}")
    if not parsed_info:
        response = DandanMatchResponse(isMatched=False)
        logger.info(f"发送匹配响应 (解析失败): {response.model_dump_json(indent=2)}")
        return response

    # --- 步骤 1: 优先进行库内直接搜索 ---
    logger.info("正在进行库内直接搜索...")
    results = await crud.search_episodes_in_library(
        session, parsed_info["title"], parsed_info.get("episode"), parsed_info.get("season")
    )
    logger.info(f"直接搜索为 '{parsed_info['title']}' (季:{parsed_info.get('season')} 集:{parsed_info.get('episode')}) 找到 {len(results)} 条记录")
    
    if results:
        # 对结果进行严格的标题过滤，避免模糊匹配带来的问题
        normalized_search_title = parsed_info["title"].replace("：", ":").replace(" ", "")
        exact_matches = []
        for r in results:
            all_titles_to_check = [
                r.get('animeTitle'), r.get('nameEn'), r.get('nameJp'), r.get('nameRomaji'),
                r.get('aliasCn1'), r.get('aliasCn2'), r.get('aliasCn3'),
            ]
            aliases_to_check = {t for t in all_titles_to_check if t}
            # 使用normalized_search_title进行更精确的匹配
            if any(fuzz.partial_ratio(alias.replace("：", ":").replace(" ", ""), normalized_search_title) > 85 for alias in aliases_to_check):
                exact_matches.append(r)

        if len(exact_matches) < len(results):
            logger.info(f"过滤掉 {len(results) - len(exact_matches)} 条模糊匹配的结果。")
            results = exact_matches

        if results:
            # 优先处理被精确标记的源
            favorited_results = [r for r in results if r.get('isFavorited')]
            if favorited_results:
                res = favorited_results[0]
                dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
                dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
                match = DandanMatchInfo(
                    episodeId=res['episodeId'], animeId=res['animeId'], animeTitle=res['animeTitle'],
                    episodeTitle=res['episodeTitle'], type=dandan_type, typeDescription=dandan_type_desc,
                    imageUrl=res.get('imageUrl')
                )
                response = DandanMatchResponse(isMatched=True, matches=[match])
                logger.info(f"发送匹配响应 (精确标记匹配): {response.model_dump_json(indent=2)}")
                return response

            # 如果没有精确标记，检查所有匹配项是否都指向同一个番剧ID
            first_animeId = results[0]['animeId']
            all_from_same_anime = all(res['animeId'] == first_animeId for res in results)

            if all_from_same_anime:
                res = results[0]
                dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
                dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
                match = DandanMatchInfo(
                    episodeId=res['episodeId'], animeId=res['animeId'], animeTitle=res['animeTitle'],
                    episodeTitle=res['episodeTitle'], type=dandan_type, typeDescription=dandan_type_desc,
                    imageUrl=res.get('imageUrl')
                )
                response = DandanMatchResponse(isMatched=True, matches=[match])
                logger.info(f"发送匹配响应 (单一作品匹配): {response.model_dump_json(indent=2)}")
                return response

            # 如果匹配到了多个不同的番剧，则返回所有结果让用户选择
            matches = []
            for res in results:
                dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
                dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
                matches.append(DandanMatchInfo(
                    episodeId=res['episodeId'], animeId=res['animeId'], animeTitle=res['animeTitle'],
                    episodeTitle=res['episodeTitle'], type=dandan_type, typeDescription=dandan_type_desc,
                    imageUrl=res.get('imageUrl')
                ))
            response = DandanMatchResponse(isMatched=False, matches=matches)
            logger.info(f"发送匹配响应 (多个匹配): {response.model_dump_json(indent=2)}")
            return response

    # --- 步骤 2: 如果直接搜索无果，则回退到 TMDB 映射 ---
    # 注意：TMDB映射仅适用于TV系列，电影跳过此步骤
    if not parsed_info.get("is_movie"):
        logger.info("直接搜索未找到精确匹配，回退到 TMDB 映射匹配。")
        potential_animes = await crud.find_animes_for_matching(session, parsed_info["title"])
        logger.info(f"为标题 '{parsed_info['title']}' 找到 {len(potential_animes)} 个可能的库内作品进行TMDB匹配。")

        for anime in potential_animes:
            if anime.get("tmdbId") and anime.get("tmdbEpisodeGroupId"):
                logger.info(f"正在为作品 ID {anime['animeId']} (TMDB ID: {anime['tmdbId']}) 尝试 TMDB 映射匹配...")
                tmdb_results = await crud.find_episode_via_tmdb_mapping(
                    session,
                    tmdb_id=anime["tmdbId"],
                    group_id=anime["tmdbEpisodeGroupId"],
                    custom_season=parsed_info.get("season"),
                    custom_episode=parsed_info.get("episode")
                )
                if tmdb_results:
                    logger.info(f"TMDB 映射匹配成功，找到 {len(tmdb_results)} 个结果。")
                    res = tmdb_results[0]
                    dandan_type = DANDAN_TYPE_MAPPING.get(res.get('type'), "other")
                    dandan_type_desc = DANDAN_TYPE_DESC_MAPPING.get(res.get('type'), "其他")
                    match = DandanMatchInfo(
                        episodeId=res['episodeId'], animeId=res['animeId'], animeTitle=res['animeTitle'],
                        episodeTitle=res['episodeTitle'], type=dandan_type, typeDescription=dandan_type_desc,
                        imageUrl=res.get('imageUrl')
                    )
                    response = DandanMatchResponse(isMatched=True, matches=[match])
                    logger.info(f"发送匹配响应 (TMDB 映射匹配): {response.model_dump_json(indent=2)}")
                    return response
    else:
        logger.info("检测到电影文件，跳过 TMDB 映射匹配。")

    # --- 步骤 3: 如果所有方法都失败 ---
    # 新增：后备机制 (Fallback Mechanism)
    fallback_enabled_str = await config_manager.get("matchFallbackEnabled", "false")
    if fallback_enabled_str.lower() == 'true':
        # 检查Token是否被允许使用匹配后备功能
        if current_token:
            try:
                # 获取当前token的信息
                token_stmt = select(orm_models.ApiToken).where(orm_models.ApiToken.token == current_token)
                token_result = await session.execute(token_stmt)
                current_token_obj = token_result.scalar_one_or_none()

                if current_token_obj:
                    # 获取允许的token列表
                    allowed_tokens_str = await config_manager.get("matchFallbackTokens", "[]")
                    allowed_token_ids = json.loads(allowed_tokens_str)

                    # 如果配置了允许的token列表且当前token不在列表中，跳过后备机制
                    if allowed_token_ids and current_token_obj.id not in allowed_token_ids:
                        logger.info(f"Token '{current_token_obj.name}' (ID: {current_token_obj.id}) 未被授权使用匹配后备功能，跳过后备机制。")
                        response = DandanMatchResponse(isMatched=False, matches=[])
                        logger.info(f"发送匹配响应 (Token未授权): {response.model_dump_json(indent=2)}")
                        return response
                    else:
                        logger.info(f"Token '{current_token_obj.name}' (ID: {current_token_obj.id}) 已被授权使用匹配后备功能。")
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"检查匹配后备Token授权时发生错误: {e}，继续执行后备机制")

        # 检查黑名单
        blacklist_pattern = await config_manager.get("matchFallbackBlacklist", "")
        if blacklist_pattern.strip():
            try:
                if re.search(blacklist_pattern, item.fileName, re.IGNORECASE):
                    logger.info(f"文件 '{item.fileName}' 匹配黑名单规则 '{blacklist_pattern}'，跳过后备机制。")
                    response = DandanMatchResponse(isMatched=False, matches=[])
                    logger.info(f"发送匹配响应 (黑名单过滤): {response.model_dump_json(indent=2)}")
                    return response
            except re.error as e:
                logger.warning(f"黑名单正则表达式 '{blacklist_pattern}' 格式错误: {e}，忽略黑名单检查")

        # 方案C: 防重复机制 - 检查5分钟内是否已完成过相同的后备任务
        recent_fallback_key = f"recent_fallback_{parsed_info['title']}_{parsed_info.get('season')}_{parsed_info.get('episode')}"
        recent_fallback_data = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, recent_fallback_key)
        if recent_fallback_data:
            cached_time = recent_fallback_data.get("timestamp", 0)
            if time.time() - cached_time < 300:  # 5分钟内
                logger.info(f"检测到5分钟内已完成的后备任务，直接返回缓存结果")
                cached_response = recent_fallback_data.get("response")
                if cached_response:
                    return cached_response

        logger.info(f"匹配失败，已启用后备机制，正在为 '{item.fileName}' 创建自动搜索任务。")

        # 将匹配后备逻辑包装成协程工厂
        match_fallback_result = {"response": None}  # 用于存储结果

        async def match_fallback_coro_factory(session_inner: AsyncSession, progress_callback):
            """匹配后备任务的协程工厂"""
            try:
                # 构造 auto_search_and_import_task 需要的 payload
                # 根据 is_movie 标记判断媒体类型
                media_type_for_fallback = "movie" if parsed_info.get("is_movie") else "tv_series"

                logger.info(f"开始匹配后备流程: {item.fileName}")

                # 解析搜索关键词，提取纯标题
                search_parsed_info = parse_search_keyword(parsed_info["title"])
                base_title = search_parsed_info["title"]
                is_movie = parsed_info.get("is_movie", False)
                season = parsed_info.get("season") or 1
                # 电影不设置episode_number,保持为None
                episode_number = None if is_movie else (parsed_info.get("episode") or 1)

                # 步骤0.5: 创建季度映射任务(如果启用) - 与搜索并行运行
                season_mapping_task = None
                match_fallback_tmdb_enabled = await config_manager.get("matchFallbackEnableTmdbSeasonMapping", "false")
                if match_fallback_tmdb_enabled.lower() == "true" and not is_movie and season and season > 1:
                    logger.info(f"○ 匹配后备 季度映射: 开始为 '{base_title}' S{season:02d} 获取季度名称(并行)...")

                    # 检查是否启用AI匹配
                    ai_match_enabled = await config_manager.get("aiMatchEnabled", "false")
                    ai_matcher = None
                    if ai_match_enabled.lower() == "true":
                        try:
                            from .ai_matcher import AIMatcher
                            ai_config = {
                                "ai_match_provider": await config_manager.get("aiProvider", "deepseek"),
                                "ai_match_api_key": await config_manager.get("aiApiKey", ""),
                                "ai_match_base_url": await config_manager.get("aiBaseUrl", ""),
                                "ai_match_model": await config_manager.get("aiModel", "deepseek-chat"),
                                "ai_match_prompt": await config_manager.get("aiPrompt", ""),
                                "ai_log_raw_response": (await config_manager.get("aiLogRawResponse", "false")).lower() == "true"
                            }
                            ai_matcher = AIMatcher(ai_config)
                        except Exception as e:
                            logger.warning(f"匹配后备 季度映射: AI匹配器初始化失败: {e}")

                    # 获取元数据源和自定义提示词
                    metadata_source = await config_manager.get("seasonMappingMetadataSource", "tmdb")
                    custom_prompt = await config_manager.get("seasonMappingPrompt", "")
                    sources = [metadata_source] if metadata_source else None

                    # 创建并行任务
                    async def get_season_mapping():
                        try:
                            return await metadata_manager.get_season_name(
                                title=base_title,
                                season_number=season,
                                year=None,  # 匹配后备通常没有年份信息
                                sources=sources,
                                ai_matcher=ai_matcher,
                                user=None,
                                custom_prompt=custom_prompt if custom_prompt else None
                            )
                        except Exception as e:
                            logger.warning(f"匹配后备 季度映射失败: {e}")
                            return None

                    season_mapping_task = asyncio.create_task(get_season_mapping())
                else:
                    if match_fallback_tmdb_enabled.lower() != "true":
                        logger.info("○ 匹配后备 季度映射: 功能未启用")
                    elif is_movie:
                        logger.info("○ 匹配后备 季度映射: 电影类型,跳过")
                    elif not season or season <= 1:
                        logger.info(f"○ 匹配后备 季度映射: 季度号为{season},跳过(仅处理S02及以上)")

                # 步骤1：使用统一的搜索函数
                logger.info(f"步骤1：全网搜索 '{base_title}'")

                # 使用统一的搜索函数（与 WebUI 搜索保持一致的过滤策略）
                all_results = await unified_search(
                    search_term=base_title,
                    session=session_inner,
                    scraper_manager=scraper_manager,
                    metadata_manager=metadata_manager,  # 启用元数据别名扩展
                    use_alias_expansion=True,  # 启用别名扩展
                    use_alias_filtering=True,  # 启用别名过滤
                    use_title_filtering=True,  # 启用标题过滤
                    use_source_priority_sorting=False,  # 仅按相似度排序
                    strict_filtering=True,  # 使用严格过滤模式
                    alias_similarity_threshold=70,  # 与 WebUI 一致的别名相似度阈值
                    progress_callback=progress_callback
                )

                if not all_results:
                    logger.warning(f"匹配后备失败：没有找到任何搜索结果")
                    response = DandanMatchResponse(isMatched=False, matches=[])
                    match_fallback_result["response"] = response
                    return

                logger.info(f"搜索完成，共 {len(all_results)} 个结果")

                # 等待季度映射任务完成(如果有)
                season_name_from_mapping = None
                if season_mapping_task:
                    try:
                        season_name_from_mapping = await season_mapping_task
                        if season_name_from_mapping:
                            logger.info(f"✓ 匹配后备 季度映射成功: '{base_title}' S{season:02d} → '{season_name_from_mapping}'")
                        else:
                            logger.info(f"○ 匹配后备 季度映射: 未找到季度名称")
                    except Exception as e:
                        logger.warning(f"匹配后备 季度映射任务失败: {e}")

                # 根据季度映射结果调整搜索结果的 season 字段
                if season_name_from_mapping and season and season > 1:
                    from .season_mapper import title_contains_season_name

                    adjusted_count = 0
                    for item in all_results:
                        # 只处理电视剧类型且 season 为 None 或 1 的结果
                        if item.type == "tv_series" and (item.season is None or item.season == 1):
                            if title_contains_season_name(item.title, season_name_from_mapping, threshold=60.0):
                                logger.info(f"  ✓ 季度调整: '{item.title}' (Provider: {item.provider}) season: {item.season} → {season}")
                                item.season = season
                                adjusted_count += 1

                    if adjusted_count > 0:
                        logger.info(f"✓ 根据季度映射调整了 {adjusted_count} 个结果的 season 字段")

                # 步骤2：智能排序 (类型匹配优先)
                logger.info(f"步骤2：智能排序 (类型匹配优先)")

                # 确定目标类型
                target_type = "movie" if is_movie else "tv_series"

                # 获取源的优先级顺序
                source_settings = await crud.get_all_scraper_settings(session_inner)
                source_order_map = {s['providerName']: s['displayOrder'] for s in source_settings}

                def calculate_match_score(result):
                    """计算匹配分数，分数越高越优先"""
                    score = 0

                    # 1. 类型匹配 (最高优先级，+1000分)
                    if result.type == target_type:
                        score += 1000
                        logger.debug(f"  - {result.provider} - {result.title}: 类型匹配 +1000")

                    # 2. 标题相似度 (0-100分)
                    similarity = fuzz.token_set_ratio(base_title, result.title)
                    score += similarity
                    logger.debug(f"  - {result.provider} - {result.title}: 相似度{similarity} +{similarity}")

                    # 3. 年份匹配 (如果有年份信息，+50分)
                    # TODO: 从parsed_info中获取年份信息

                    return score

                # 按分数排序 (分数高的在前)，相同分数时按源优先级排序
                sorted_results = sorted(
                    all_results,
                    key=lambda r: (calculate_match_score(r), -source_order_map.get(r.provider, 999)),
                    reverse=True
                )

                # 打印排序后的结果列表
                logger.info(f"排序后的搜索结果列表 (按匹配分数):")
                for idx, result in enumerate(sorted_results, 1):
                    score = calculate_match_score(result)
                    type_match = "✓" if result.type == target_type else "✗"
                    logger.info(f"  {idx}. [{type_match}] {result.provider} - {result.title} (ID: {result.mediaId}, 类型: {result.type}, 年份: {result.year or 'N/A'}, 分数: {score:.0f})")

                # 步骤3：自动选择最佳源
                logger.info(f"步骤3：自动选择最佳源")

                # 获取精确标记信息 (AI匹配和传统匹配都需要)
                favorited_info = {}
                async with scraper_manager._session_factory() as ai_session:
                    for result in sorted_results:
                        # 查找是否有相同provider和mediaId的源被标记
                        stmt = (
                            select(AnimeSource.isFavorited)
                            .where(
                                AnimeSource.providerName == result.provider,
                                AnimeSource.mediaId == result.mediaId
                            )
                            .limit(1)
                        )
                        result_row = await ai_session.execute(stmt)
                        is_favorited = result_row.scalar_one_or_none()
                        if is_favorited:
                            key = f"{result.provider}:{result.mediaId}"
                            favorited_info[key] = True

                # 检查是否启用AI匹配
                ai_match_enabled = (await config_manager.get("aiMatchEnabled", "false")).lower() == 'true'

                # 如果启用AI匹配，尝试使用AI选择
                ai_selected_index = None
                if ai_match_enabled:
                    try:
                        # 动态注册AI提示词配置(如果不存在则创建,使用硬编码默认值)
                        await crud.initialize_configs(session_inner, {
                            "aiMatchPrompt": (DEFAULT_AI_MATCH_PROMPT, "AI智能匹配提示词")
                        })

                        # 获取AI配置
                        # 注意: 此时数据库中一定存在这个键(上面已经初始化),直接读取即可
                        ai_config = {
                            "ai_match_provider": await config_manager.get("aiProvider", "deepseek"),
                            "ai_match_api_key": await config_manager.get("aiApiKey", ""),
                            "ai_match_base_url": await config_manager.get("aiBaseUrl", ""),
                            "ai_match_model": await config_manager.get("aiModel", "deepseek-chat"),
                            "ai_match_prompt": await config_manager.get("aiPrompt", ""),
                            "ai_log_raw_response": (await config_manager.get("aiLogRawResponse", "false")).lower() == "true"
                        }

                        # 检查必要配置
                        if not ai_config["ai_match_api_key"]:
                            logger.warning("AI匹配已启用但未配置API密钥，降级到传统匹配")
                        else:
                            # 构建查询信息
                            query_info = {
                                "title": base_title,
                                "season": season,
                                "episode": episode_number,
                                "year": None,  # 匹配后备场景通常没有年份信息
                                "type": "movie" if is_movie else "tv_series"
                            }

                            # 初始化AI匹配器并选择
                            matcher = AIMatcher(ai_config)
                            ai_selected_index = await matcher.select_best_match(
                                query_info, sorted_results, favorited_info
                            )

                            if ai_selected_index is not None:
                                logger.info(f"AI匹配成功选择: 索引 {ai_selected_index}")
                            else:
                                # 检查是否启用传统匹配兜底
                                ai_fallback_enabled = (await config_manager.get("aiFallbackEnabled", "true")).lower() == 'true'
                                if ai_fallback_enabled:
                                    logger.info("AI匹配未找到合适结果，降级到传统匹配")
                                else:
                                    logger.warning("AI匹配未找到合适结果，且传统匹配兜底已禁用，将不使用任何结果")

                    except Exception as e:
                        # 检查是否启用传统匹配兜底
                        ai_fallback_enabled = (await config_manager.get("aiFallbackEnabled", "true")).lower() == 'true'
                        if ai_fallback_enabled:
                            logger.error(f"AI匹配失败，降级到传统匹配: {e}", exc_info=True)
                        else:
                            logger.error(f"AI匹配失败，且传统匹配兜底已禁用: {e}", exc_info=True)
                        ai_selected_index = None

                # 检查是否启用顺延机制
                fallback_enabled = (await config_manager.get("externalApiFallbackEnabled", "false")).lower() == 'true'

                best_match = None

                # 如果AI选择成功，使用AI选择的结果
                if ai_selected_index is not None:
                    best_match = sorted_results[ai_selected_index]
                    logger.info(f"  - 使用AI选择的结果: {best_match.provider} - {best_match.title}")
                elif ai_match_enabled:
                    # AI匹配已启用但失败，检查是否允许降级到传统匹配
                    ai_fallback_enabled = (await config_manager.get("aiFallbackEnabled", "true")).lower() == 'true'
                    if not ai_fallback_enabled:
                        logger.warning("AI匹配失败且传统匹配兜底已禁用，匹配后备失败")
                        return DandanMatchResponse(isMatched=False, matches=[])
                    # 允许降级，继续使用传统匹配
                    logger.info("AI匹配失败，使用传统匹配兜底")
                    # 传统匹配: 优先查找精确标记源 (需验证标题相似度)
                    favorited_match = None
                    for result in sorted_results:
                        key = f"{result.provider}:{result.mediaId}"
                        if favorited_info.get(key):
                            # 验证标题相似度,避免错误匹配
                            similarity = fuzz.token_set_ratio(base_title, result.title)
                            logger.info(f"  - 找到精确标记源: {result.provider} - {result.title} (相似度: {similarity}%)")

                            # 只有相似度 >= 80% 才使用精确标记源
                            if similarity >= 80:
                                favorited_match = result
                                logger.info(f"  - 标题相似度验证通过 ({similarity}% >= 80%)")
                                break
                            else:
                                logger.warning(f"  - 标题相似度过低 ({similarity}% < 80%)，跳过此精确标记源")

                    if favorited_match:
                        best_match = favorited_match
                        logger.info(f"  - 使用精确标记源: {best_match.provider} - {best_match.title}")
                    elif not fallback_enabled:
                        # 顺延机制关闭，使用第一个结果 (已经是分数最高的)
                        best_match = sorted_results[0]
                        logger.info(f"  - 顺延机制关闭，选择第一个结果: {best_match.provider} - {best_match.title}")
                else:
                    # AI未启用，使用传统匹配
                    # 传统匹配: 优先查找精确标记源 (需验证标题相似度)
                    favorited_match = None
                    for result in sorted_results:
                        key = f"{result.provider}:{result.mediaId}"
                        if favorited_info.get(key):
                            # 验证标题相似度,避免错误匹配
                            similarity = fuzz.token_set_ratio(base_title, result.title)
                            logger.info(f"  - 找到精确标记源: {result.provider} - {result.title} (相似度: {similarity}%)")

                            # 只有相似度 >= 80% 才使用精确标记源
                            if similarity >= 80:
                                favorited_match = result
                                logger.info(f"  - 标题相似度验证通过 ({similarity}% >= 80%)")
                                break
                            else:
                                logger.warning(f"  - 标题相似度过低 ({similarity}% < 80%)，跳过此精确标记源")

                    if favorited_match:
                        best_match = favorited_match
                        logger.info(f"  - 使用精确标记源: {best_match.provider} - {best_match.title}")
                    elif not fallback_enabled:
                        # 顺延机制关闭，使用第一个结果 (已经是分数最高的)
                        best_match = sorted_results[0]
                        logger.info(f"  - 顺延机制关闭，选择第一个结果: {best_match.provider} - {best_match.title}")

                if best_match is None and fallback_enabled:
                    # 顺延机制启用：依次验证候选源 (按分数从高到低)
                    logger.info(f"  - 顺延机制启用，依次验证候选源")
                    for attempt, candidate in enumerate(sorted_results, 1):
                        logger.info(f"    {attempt}. 正在验证: {candidate.provider} - {candidate.title} (ID: {candidate.mediaId}, 类型: {candidate.type})")
                        try:
                            scraper = scraper_manager.get_scraper(candidate.provider)
                            if not scraper:
                                logger.warning(f"    {attempt}. {candidate.provider} - 无法获取scraper，跳过")
                                continue

                            # 获取分集列表进行验证
                            episodes = await scraper.get_episodes(candidate.mediaId, db_media_type=candidate.type)
                            if not episodes:
                                logger.warning(f"    {attempt}. {candidate.provider} - 没有分集列表，跳过")
                                continue

                            # 如果用户搜索的是电影，只匹配电影类型的候选源
                            if is_movie:
                                if candidate.type != "movie":
                                    logger.warning(f"    {attempt}. {candidate.provider} - 类型不匹配 (搜索电影，但候选源是{candidate.type})，跳过")
                                    continue
                                logger.info(f"    {attempt}. {candidate.provider} - 验证通过 (电影)")
                            # 如果指定了集数，检查是否有目标集数
                            elif episode_number is not None:
                                target_episode = None
                                for ep in episodes:
                                    if ep.episodeIndex == episode_number:
                                        target_episode = ep
                                        break

                                if not target_episode:
                                    logger.warning(f"    {attempt}. {candidate.provider} - 没有第 {episode_number} 集，跳过")
                                    continue

                                logger.info(f"    {attempt}. {candidate.provider} - 验证通过")
                            else:
                                logger.info(f"    {attempt}. {candidate.provider} - 验证通过")
                            best_match = candidate
                            break
                        except Exception as e:
                            logger.warning(f"    {attempt}. {candidate.provider} - 验证失败: {e}")
                            continue

                if not best_match:
                    logger.warning(f"匹配后备失败：所有候选源都无法提供有效分集")
                    response = DandanMatchResponse(isMatched=False, matches=[])
                    match_fallback_result["response"] = response
                    return

                # 步骤4：应用入库后处理规则
                logger.info(f"步骤4：应用入库后处理规则")
                final_title = best_match.title
                final_season = season if season is not None else 1  # 默认为第1季
                if title_recognition_manager:
                    converted_title, converted_season, was_converted, _ = await title_recognition_manager.apply_storage_postprocessing(
                        best_match.title, season, best_match.provider
                    )
                    if was_converted:
                        final_title = converted_title
                        final_season = converted_season if converted_season is not None else 1
                        logger.info(f"  - 应用入库后处理: '{best_match.title}' S{season or 1:02d} -> '{final_title}' S{final_season:02d}")

                # 步骤5：分配虚拟animeId和真实episodeId
                logger.info(f"步骤5：分配虚拟animeId和真实episodeId")

                # 分配虚拟animeId
                virtual_anime_id = await _get_next_virtual_anime_id(session_inner)
                logger.info(f"  - 分配虚拟animeId: {virtual_anime_id}")

                # 分配真实anime_id（用于生成episodeId）
                # 注意：Anime和AnimeSource已经在orm_models中定义，这里直接使用
                stmt = select(orm_models.Anime.id, orm_models.Anime.title).where(
                    orm_models.Anime.title == final_title,
                    orm_models.Anime.season == final_season
                )
                result = await session_inner.execute(stmt)
                existing_db_anime = result.mappings().first()

                if existing_db_anime:
                    real_anime_id = existing_db_anime['id']
                    logger.info(f"  - 复用已存在的番剧: '{final_title}' (real_anime_id={real_anime_id})")
                else:
                    real_anime_id = await _get_next_real_anime_id(session_inner)
                    logger.info(f"  - 分配新的real_anime_id: {real_anime_id}")

                # 获取或创建source，以获取正确的source_order
                # 检查是否已有该源
                source_stmt = select(orm_models.AnimeSource.id, orm_models.AnimeSource.sourceOrder).where(
                    orm_models.AnimeSource.animeId == real_anime_id,
                    orm_models.AnimeSource.providerName == best_match.provider,
                    orm_models.AnimeSource.mediaId == best_match.mediaId
                )
                source_result = await session_inner.execute(source_stmt)
                existing_source = source_result.mappings().first()

                if existing_source:
                    source_order = existing_source['sourceOrder']
                    logger.info(f"  - 复用已存在的源: source_order={source_order}")
                else:
                    # 查找当前最大的source_order
                    max_order_stmt = select(func.max(orm_models.AnimeSource.sourceOrder)).where(orm_models.AnimeSource.animeId == real_anime_id)
                    max_order_result = await session_inner.execute(max_order_stmt)
                    current_max_order = max_order_result.scalar_one_or_none()
                    logger.debug(f"  - 查询到的最大source_order: {current_max_order}")
                    source_order = (current_max_order or 0) + 1
                    logger.info(f"  - 分配新的source_order: {source_order}")

                # 生成真实episodeId (电影使用1作为episode_number)
                final_episode_number = 1 if is_movie else episode_number
                real_episode_id = _generate_episode_id(real_anime_id, source_order, final_episode_number)
                logger.info(f"  - 生成真实episodeId: {real_episode_id}")

                # 步骤6：存储映射关系到数据库缓存
                mapping_key = f"fallback_anime_{virtual_anime_id}"
                mapping_data = {
                    "real_anime_id": real_anime_id,
                    "provider": best_match.provider,
                    "mediaId": best_match.mediaId,
                    "final_title": final_title,
                    "final_season": final_season,
                    "media_type": best_match.type,
                    "imageUrl": best_match.imageUrl,
                    "year": best_match.year,
                    "timestamp": time.time()
                }
                await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, mapping_key, mapping_data, FALLBACK_SEARCH_CACHE_TTL)

                # 存储episodeId映射
                episode_mapping_key = f"fallback_episode_{real_episode_id}"
                episode_mapping_data = {
                    "virtual_anime_id": virtual_anime_id,
                    "real_anime_id": real_anime_id,
                    "provider": best_match.provider,
                    "mediaId": best_match.mediaId,
                    "episode_number": final_episode_number,  # 使用final_episode_number (电影为1)
                    "final_title": final_title,
                    "final_season": final_season,
                    "media_type": best_match.type,
                    "imageUrl": best_match.imageUrl,
                    "year": best_match.year,
                    "timestamp": time.time()
                }
                await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, episode_mapping_key, episode_mapping_data, FALLBACK_SEARCH_CACHE_TTL)

                logger.info(f"匹配后备完成: virtual_anime_id={virtual_anime_id}, real_anime_id={real_anime_id}, episodeId={real_episode_id}")

                # 方案A: 写入数据库 - 创建anime和episode记录
                try:
                    logger.info("开始将后备匹配结果写入数据库...")

                    # 检查anime是否已存在
                    stmt = select(orm_models.Anime).where(orm_models.Anime.id == real_anime_id)
                    result = await session_inner.execute(stmt)
                    existing_anime = result.scalar_one_or_none()

                    if not existing_anime:
                        # 创建anime条目
                        logger.info(f"创建anime条目: id={real_anime_id}, title='{final_title}'")
                        new_anime = orm_models.Anime(
                            id=real_anime_id,
                            title=final_title,
                            type=best_match.type,
                            season=final_season,
                            imageUrl=best_match.imageUrl,
                            year=best_match.year,
                            createdAt=get_now()
                        )
                        session_inner.add(new_anime)
                        await session_inner.flush()
                        # 同步PostgreSQL序列
                        await sync_postgres_sequence(session_inner)
                    else:
                        logger.info(f"anime条目已存在: id={real_anime_id}, title='{existing_anime.title}'")

                    # 创建或获取source关联
                    source_id = await crud.link_source_to_anime(session_inner, real_anime_id, best_match.provider, best_match.mediaId)
                    logger.info(f"source_id={source_id}, provider={best_match.provider}, mediaId={best_match.mediaId}")

                    # 创建episode记录
                    episode_title = f"第{final_episode_number}集" if not is_movie else final_title
                    episode_db_id = await crud.create_episode_if_not_exists(
                        session_inner,
                        real_anime_id,
                        source_id,
                        final_episode_number,
                        episode_title,
                        None,  # url
                        f"fallback_{best_match.provider}_{best_match.mediaId}_{final_episode_number}"  # provider_episode_id
                    )
                    logger.info(f"episode记录已创建/获取: episode_db_id={episode_db_id}")

                    # 提交数据库更改
                    await session_inner.commit()
                    logger.info("后备匹配结果已成功写入数据库")

                except Exception as db_error:
                    logger.error(f"写入数据库失败: {db_error}", exc_info=True)
                    await session_inner.rollback()
                    # 即使数据库写入失败,也继续返回结果(依赖缓存)

                # 返回真实的匹配结果
                match_result = DandanMatchInfo(
                    episodeId=real_episode_id,
                    animeId=virtual_anime_id,  # 返回虚拟animeId
                    animeTitle=final_title,
                    episodeTitle=f"第{episode_number}集" if not parsed_info.get("is_movie") else final_title,
                    type="tvseries" if not parsed_info.get("is_movie") else "movie",
                    typeDescription="匹配成功",
                    imageUrl=best_match.imageUrl
                )
                response = DandanMatchResponse(isMatched=True, matches=[match_result])
                logger.info(f"发送匹配响应 (匹配后备): episodeId={real_episode_id}, animeId={virtual_anime_id}")

                # 存储到防重复缓存
                recent_fallback_key = f"recent_fallback_{parsed_info['title']}_{parsed_info.get('season')}_{parsed_info.get('episode')}"
                recent_fallback_data = {
                    "response": response,
                    "timestamp": time.time()
                }
                await _set_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, recent_fallback_key, recent_fallback_data, 300)  # 5分钟TTL

                match_fallback_result["response"] = response
            except Exception as e:
                logger.error(f"匹配后备失败: {e}", exc_info=True)
                response = DandanMatchResponse(isMatched=False, matches=[])
                match_fallback_result["response"] = response

        # 提交匹配后备任务(立即执行模式)
        try:
            task_title = f"匹配后备: {item.fileName}"
            task_id, done_event = await task_manager.submit_task(
                match_fallback_coro_factory,
                task_title,
                run_immediately=True,
                queue_type="fallback"
            )
            logger.info(f"匹配后备任务已提交: {task_id}")

            # 等待任务完成(最多30秒)
            try:
                await asyncio.wait_for(done_event.wait(), timeout=30.0)
                logger.info(f"匹配后备任务完成: {task_id}")
            except asyncio.TimeoutError:
                logger.warning(f"匹配后备任务超时: {task_id}")
                match_fallback_result["response"] = DandanMatchResponse(isMatched=False, matches=[])

            # 返回结果
            if match_fallback_result["response"]:
                return match_fallback_result["response"]
            else:
                return DandanMatchResponse(isMatched=False, matches=[])
        except Exception as e:
            logger.error(f"提交匹配后备任务失败: {e}", exc_info=True)
            return DandanMatchResponse(isMatched=False, matches=[])

    response = DandanMatchResponse(isMatched=False, matches=[])
    logger.info(f"发送匹配响应 (所有方法均未匹配): {response.model_dump_json(indent=2)}")
    return response

@implementation_router.post(
    "/match",
    response_model=DandanMatchResponse,
    summary="[dandanplay兼容] 匹配单个文件"
)
async def match_single_file(
    request: DandanBatchMatchRequestItem,
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    config_manager: ConfigManager = Depends(get_config_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    title_recognition_manager = Depends(get_title_recognition_manager)
):
    """
    通过文件名匹配弹幕库。此接口不使用文件Hash。
    优先进行库内直接匹配，失败后回退到TMDB剧集组映射。
    """
    return await _get_match_for_item(
        request, session, task_manager, scraper_manager,
        metadata_manager, config_manager, rate_limiter, title_recognition_manager,
        current_token=token
    )


@implementation_router.post(
    "/match/batch",
    response_model=List[DandanMatchResponse],
    summary="[dandanplay兼容] 批量匹配文件"
)
async def match_batch_files(
    request: DandanBatchMatchRequest,
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    task_manager: TaskManager = Depends(get_task_manager),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    metadata_manager: MetadataSourceManager = Depends(get_metadata_manager),
    config_manager: ConfigManager = Depends(get_config_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    title_recognition_manager = Depends(get_title_recognition_manager)
):
    """
    批量匹配文件。
    """
    if len(request.requests) > 32:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="批量匹配请求不能超过32个文件。")

    tasks = [
        _get_match_for_item(
            item, session, task_manager, scraper_manager, metadata_manager, config_manager, rate_limiter, title_recognition_manager,
            current_token=token
        ) for item in request.requests
    ]
    results = await asyncio.gather(*tasks)
    return results


@implementation_router.get(
    "/extcomment",
    response_model=models.CommentResponse,
    summary="[dandanplay兼容] 获取外部弹幕"
)
async def get_external_comments_from_url(
    url: str = Query(..., description="外部视频链接 (支持 Bilibili, 腾讯, 爱奇艺, 优酷, 芒果TV)"),
    chConvert: int = Query(0, description="中文简繁转换。0-不转换，1-转换为简体，2-转换为繁体。"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    manager: ScraperManager = Depends(get_scraper_manager)
):
    """
    从外部URL获取弹幕，并转换为dandanplay格式。
    结果会被缓存5小时。
    """
    cache_key = f"ext_danmaku_v2_{url}"
    cached_comments = await crud.get_cache(session, cache_key)
    if cached_comments is not None:
        logger.info(f"外部弹幕缓存命中: {url}")
        comments_data = cached_comments
    else:
        logger.info(f"外部弹幕缓存未命中，正在从网络获取: {url}")
        scraper = manager.get_scraper_by_domain(url)
        if not scraper:
            raise HTTPException(status_code=400, detail="不支持的URL或视频源。")

        try:
            provider_episode_id = await scraper.get_id_from_url(url)
            if not provider_episode_id:
                raise ValueError(f"无法从URL '{url}' 中解析出有效的视频ID。")
            
            episode_id_for_comments = scraper.format_episode_id_for_comments(provider_episode_id)
            comments_data = await scraper.get_comments(episode_id_for_comments)

            # 修正：使用 scraper.provider_name 修复未定义的 'provider' 变量
            if not comments_data: logger.warning(f"未能从 {scraper.provider_name} URL 获取任何弹幕: {url}")

        except Exception as e:
            logger.error(f"处理 {scraper.provider_name} 外部弹幕时出错: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"获取 {scraper.provider_name} 弹幕失败。")

        # 缓存结果5小时 (18000秒)
        await crud.set_cache(session, cache_key, comments_data, 18000)

    # 处理简繁转换
    if chConvert in [1, 2]:
        converter = None
        if chConvert == 1:
            converter = OpenCC('t2s')  # 繁转简
        elif chConvert == 2:
            converter = OpenCC('s2t')  # 简转繁
        
        if converter:
            for comment in comments_data:
                comment['m'] = converter.convert(comment['m'])

    # 修正：使用统一的弹幕处理函数，以确保输出格式符合 dandanplay 客户端规范
    processed_comments = _process_comments_for_dandanplay(comments_data)
    return models.CommentResponse(count=len(processed_comments), comments=processed_comments)

@implementation_router.get(
    "/comment/{episodeId}",
    response_model=models.CommentResponse,
    summary="[dandanplay兼容] 获取弹幕"
)
async def get_comments_for_dandan(
    request: Request,
    episodeId: int = Path(..., description="分集ID (来自 /search/episodes 响应中的 episodeId)"),
    chConvert: int = Query(0, description="中文简繁转换。0-不转换，1-转换为简体，2-转换为繁体。"),
    # 'from' 是 Python 的关键字，所以我们必须使用别名
    fromTime: int = Query(0, alias="from", description="弹幕开始时间(秒)"),
    withRelated: bool = Query(True, description="是否包含关联弹幕"),
    token: str = Depends(get_token_from_path),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager),
    scraper_manager: ScraperManager = Depends(get_scraper_manager),
    task_manager: TaskManager = Depends(get_task_manager),
    rate_limiter: RateLimiter = Depends(get_rate_limiter)
):
    """
    模拟 dandanplay 的弹幕获取接口。
    优化：优先使用弹幕库，如果没有则直接从源站获取并异步存储。
    """
    # 预下载下一集弹幕 (异步,不阻塞当前响应)
    # 在函数开始时就提交,无论当前集是否有弹幕
    # 添加异常处理回调，确保任何错误都能被记录
    predownload_task = asyncio.create_task(_try_predownload_next_episode(
        episodeId, request.app.state.db_session_factory, config_manager, task_manager,
        scraper_manager, rate_limiter
    ))

    # 添加异常处理回调
    def handle_predownload_exception(task):
        try:
            task.result()  # 如果任务有异常，这里会抛出
        except Exception as e:
            logger.error(f"预下载任务异常 (episodeId={episodeId}): {e}", exc_info=True)

    predownload_task.add_done_callback(handle_predownload_exception)

    # 1. 优先从弹幕库获取弹幕
    comments_data = await crud.fetch_comments(session, episodeId)

    if not comments_data:
        logger.info(f"弹幕库中未找到 episodeId={episodeId} 的弹幕，尝试直接从源站获取")

        # 检查是否是后备搜索/匹配后备的episodeId
        # 虚拟episodeId格式: 25000166010002 (166=anime_id, 01=source_order, 0002=episode_number)
        # 缓存key格式: fallback_episode_25000166010000 (最后4位为0000表示整部剧)

        fallback_info = None
        episode_number = None

        # 尝试解析虚拟episodeId
        if episodeId >= 25000000000000:
            # 提取anime_id, source_order, episode_number
            temp_id = episodeId - 25000000000000
            anime_id_part = temp_id // 1000000
            temp_id = temp_id % 1000000
            source_order_part = temp_id // 10000
            episode_number = temp_id % 10000

            # 构造整部剧的缓存key
            virtual_anime_base = 25000000000000 + anime_id_part * 1000000 + source_order_part * 10000
            fallback_series_key = f"fallback_episode_{virtual_anime_base}"

            # 从数据库缓存中查找整部剧的信息
            fallback_info = await crud.get_cache(session, fallback_series_key)
            logger.debug(f"查找缓存: {fallback_series_key}, 找到: {fallback_info is not None}")

        # 如果数据库缓存中没有,再从数据库缓存中查找(使用新的前缀)
        if not fallback_info:
            fallback_episode_cache_key = f"fallback_episode_{episodeId}"
            fallback_info = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, fallback_episode_cache_key)
            if fallback_info:
                episode_number = fallback_info.get("episode_number")

        if fallback_info:
            logger.info(f"检测到后备搜索/匹配后备的episodeId: {episodeId}, 集数: {episode_number}")

            # 从缓存中获取信息
            real_anime_id = fallback_info["real_anime_id"]
            provider = fallback_info["provider"]
            mediaId = fallback_info["mediaId"]
            final_title = fallback_info["final_title"]
            final_season = fallback_info["final_season"]
            media_type = fallback_info["media_type"]
            imageUrl = fallback_info.get("imageUrl")
            year = fallback_info.get("year")

            # 步骤1：创建或获取anime条目
            stmt = select(Anime).where(Anime.id == real_anime_id)
            result = await session.execute(stmt)
            existing_anime = result.scalar_one_or_none()

            if not existing_anime:
                # 创建anime条目
                logger.info(f"创建anime条目: id={real_anime_id}, title='{final_title}'")
                new_anime = Anime(
                    id=real_anime_id,
                    title=final_title,
                    type=media_type,
                    season=final_season,
                    imageUrl=imageUrl,
                    year=year,
                    createdAt=get_now()
                )
                session.add(new_anime)
                await session.flush()
                # 同步PostgreSQL序列(避免主键冲突)
                await sync_postgres_sequence(session)
            else:
                logger.info(f"anime条目已存在: id={real_anime_id}, title='{existing_anime.title}'")

            # 步骤2：创建或获取source关联
            source_id = await crud.link_source_to_anime(session, real_anime_id, provider, mediaId)
            logger.info(f"source_id={source_id}")

            # 提交anime和source创建，避免与后台任务产生锁冲突
            await session.commit()
            logger.info(f"已提交anime和source创建")

            # 步骤3：获取分集信息
            logger.info(f"开始获取分集信息: provider={provider}, mediaId={mediaId}, episode_number={episode_number}")

            # 获取scraper
            scraper = scraper_manager.get_scraper(provider)
            if not scraper:
                logger.error(f"无法获取scraper: {provider}")
                await session.rollback()
                return models.CommentResponse(count=0, comments=[])

            # 获取分集列表
            try:
                episodes_list = await scraper.get_episodes(mediaId, db_media_type=media_type)
                if not episodes_list or len(episodes_list) < episode_number:
                    logger.error(f"无法获取第{episode_number}集的信息")
                    await session.rollback()
                    return models.CommentResponse(count=0, comments=[])

                # 获取目标分集信息
                target_episode = episodes_list[episode_number - 1]
                provider_episode_id = target_episode.episodeId
                episode_title = target_episode.title
                episode_url = target_episode.url

                logger.info(f"获取到分集信息: title='{episode_title}', provider_episode_id='{provider_episode_id}'")

            except Exception as e:
                logger.error(f"获取分集信息失败: {e}", exc_info=True)
                await session.rollback()
                return models.CommentResponse(count=0, comments=[])

            # 步骤4：下载弹幕 (使用task_manager提交到后备队列)
            logger.info(f"开始下载弹幕: provider_episode_id={provider_episode_id}")

            # 检查是否已有相同的弹幕下载任务正在进行
            task_unique_key = f"match_fallback_comments_{episodeId}"
            existing_task = await crud.find_recent_task_by_unique_key(session, task_unique_key, 1)
            if existing_task:
                logger.info(f"弹幕下载任务已存在: {task_unique_key}，等待任务完成...")
                # 等待最多30秒，检查缓存中是否有结果
                cache_key = f"comments_{episodeId}"
                for i in range(30):
                    await asyncio.sleep(1)
                    cached_comments = await _get_db_cache(session, COMMENTS_FETCH_CACHE_PREFIX, cache_key)
                    if cached_comments:
                        logger.info(f"从缓存中获取到弹幕数据，共 {len(cached_comments)} 条")
                        break
                # 跳过任务提交，直接进入缓存读取逻辑
            else:
                # 任务不存在，提交新任务
                # 保存当前作用域的变量，避免闭包问题
                current_scraper = scraper
                current_provider_episode_id = provider_episode_id
                current_provider = provider
                current_real_anime_id = real_anime_id
                current_mediaId = mediaId
                current_episode_number = episode_number
                current_episode_title = episode_title
                current_episode_url = episode_url
                current_episodeId = episodeId
                current_fallback_episode_cache_key = f"fallback_episode_{episodeId}"
                current_rate_limiter = rate_limiter
                current_final_title = final_title
                current_final_season = final_season
                current_media_type = media_type
                current_imageUrl = imageUrl
                current_year = year
                current_episodes_list = episodes_list  # 保存整部剧的分集列表

                async def download_match_fallback_comments_task(task_session, progress_callback):
                    """匹配后备弹幕下载任务"""
                    try:
                        await progress_callback(10, "开始下载弹幕...")

                        # 检查流控
                        await current_rate_limiter.check_fallback("match", current_provider)

                        # 下载弹幕
                        comments = await current_scraper.get_comments(current_provider_episode_id, progress_callback=progress_callback)
                        if not comments:
                            logger.warning(f"下载失败，未获取到弹幕")
                            return None

                        # 增加流控计数
                        await current_rate_limiter.increment_fallback("match", current_provider)
                        logger.info(f"下载成功，共 {len(comments)} 条弹幕")

                        # 立即存储到数据库缓存中，让主接口能快速返回
                        cache_key = f"comments_{current_episodeId}"
                        await _set_db_cache(task_session, COMMENTS_FETCH_CACHE_PREFIX, cache_key, comments, COMMENTS_FETCH_CACHE_TTL)
                        logger.info(f"弹幕已存入缓存: {cache_key}")

                        await progress_callback(60, "创建数据库条目...")

                        # 在task_session中创建或获取anime条目
                        stmt = select(Anime).where(Anime.id == current_real_anime_id)
                        result = await task_session.execute(stmt)
                        existing_anime = result.scalar_one_or_none()

                        if not existing_anime:
                            # 创建anime条目
                            logger.info(f"任务中创建anime条目: id={current_real_anime_id}, title='{current_final_title}'")
                            new_anime = Anime(
                                id=current_real_anime_id,
                                title=current_final_title,
                                type=current_media_type,
                                season=current_final_season,
                                imageUrl=current_imageUrl,
                                year=current_year,
                                createdAt=get_now()
                            )
                            task_session.add(new_anime)
                            await task_session.flush()

                            # 同步PostgreSQL序列(避免主键冲突)
                            await sync_postgres_sequence(task_session)
                        else:
                            logger.info(f"任务中anime条目已存在: id={current_real_anime_id}, title='{existing_anime.title}'")

                        # 创建或获取source关联 (在task_session中)
                        source_id = await crud.link_source_to_anime(task_session, current_real_anime_id, current_provider, current_mediaId)
                        logger.info(f"source_id={source_id}")

                        # 获取source_order用于生成虚拟episodeId
                        stmt_source = select(AnimeSource.sourceOrder).where(AnimeSource.id == source_id)
                        result_source = await task_session.execute(stmt_source)
                        source_order = result_source.scalar_one()

                        # 创建当前Episode条目
                        episode_db_id = await crud.create_episode_if_not_exists(
                            task_session, current_real_anime_id, source_id, current_episode_number,
                            current_episode_title, current_episode_url, current_provider_episode_id
                        )
                        await task_session.flush()
                        logger.info(f"Episode条目已创建/存在: id={episode_db_id}")

                        # 为整部剧创建一条缓存记录(不下载弹幕,不创建数据库记录)
                        # 这样播放器推理下一集时能通过缓存触发弹幕下载
                        # 缓存条目保留3小时,支持连续播放
                        try:
                            # 使用虚拟anime_id作为缓存key的前缀
                            # 格式: fallback_episode_25000166010000 (最后4位为0000表示整部剧)
                            virtual_anime_base = 25000000000000 + current_real_anime_id * 1000000 + source_order * 10000
                            fallback_series_key = f"fallback_episode_{virtual_anime_base}"

                            cache_value = {
                                "real_anime_id": current_real_anime_id,
                                "provider": current_provider,
                                "mediaId": current_mediaId,
                                "final_title": current_final_title,
                                "final_season": current_final_season,
                                "media_type": current_media_type,
                                "imageUrl": current_imageUrl,
                                "year": current_year,
                                "total_episodes": len(current_episodes_list)
                            }

                            # 存储到数据库缓存,3小时过期
                            await crud.set_cache(task_session, fallback_series_key, cache_value, 10800)
                            await task_session.flush()
                            logger.info(f"为整部剧创建了缓存记录: {fallback_series_key} (共{len(current_episodes_list)}集)")
                        except Exception as e:
                            logger.warning(f"创建缓存记录失败: {e}")

                        await progress_callback(80, "保存弹幕...")

                        # 保存弹幕
                        added_count = await crud.save_danmaku_for_episode(
                            task_session, current_episodeId, comments, None
                        )
                        await task_session.commit()
                        logger.info(f"保存成功，共 {added_count} 条弹幕")

                        # 清理数据库缓存
                        await _delete_db_cache(task_session, FALLBACK_SEARCH_CACHE_PREFIX, current_fallback_episode_cache_key)
                        logger.debug(f"清理数据库缓存: {current_fallback_episode_cache_key}")

                        # 注意:不删除数据库缓存中的整部剧记录,保留3小时以支持连续播放
                        # 数据库缓存会自动过期

                        await progress_callback(100, "完成")
                        return comments

                    except Exception as e:
                        logger.error(f"匹配后备弹幕下载任务执行失败: {e}", exc_info=True)
                        await task_session.rollback()
                        return None

                # 提交弹幕下载任务到后备队列
                try:
                    task_id, done_event = await task_manager.submit_task(
                        download_match_fallback_comments_task,
                        f"匹配后备弹幕下载: episodeId={episodeId}",
                        unique_key=task_unique_key,
                        task_type="download_comments",
                        queue_type="fallback"  # 使用后备队列
                    )
                    logger.info(f"已提交匹配后备弹幕下载任务: {task_id}")

                    # 等待任务完成，但设置较短的超时时间（30秒）
                    try:
                        await asyncio.wait_for(done_event.wait(), timeout=30.0)
                        # 任务完成，检查缓存中是否有结果
                        cache_key = f"comments_{episodeId}"
                        cached_comments_result = await _get_db_cache(session, COMMENTS_FETCH_CACHE_PREFIX, cache_key)
                        if cached_comments_result:
                            logger.info(f"匹配后备弹幕下载任务快速完成，获得 {len(cached_comments_result)} 条弹幕")
                            # 不删除缓存，让后续逻辑继续处理
                        else:
                            logger.warning(f"任务完成但缓存中未找到弹幕数据")
                    except asyncio.TimeoutError:
                        logger.warning(f"匹配后备弹幕下载任务超时，任务将在后台继续执行")
                        # 超时后返回空结果，让用户稍后再试
                        return models.CommentResponse(count=0, comments=[])

                except HTTPException as e:
                    # 如果是409错误(任务已在运行中),等待一段时间后从缓存获取
                    if e.status_code == 409:
                        logger.info(f"任务已在运行中，等待现有任务完成...")
                        # 等待最多30秒，检查缓存中是否有结果
                        cache_key = f"comments_{episodeId}"
                        for i in range(30):
                            await asyncio.sleep(1)
                            cached_comments_wait = await _get_db_cache(session, COMMENTS_FETCH_CACHE_PREFIX, cache_key)
                            if cached_comments_wait:
                                logger.info(f"从缓存中获取到弹幕数据，共 {len(cached_comments_wait)} 条")
                                break
                        # 继续执行后续逻辑，从缓存中获取弹幕
                    else:
                        logger.error(f"提交匹配后备弹幕下载任务失败: {e}", exc_info=True)
                        await session.rollback()
                        return models.CommentResponse(count=0, comments=[])
                except Exception as e:
                    logger.error(f"提交匹配后备弹幕下载任务失败: {e}", exc_info=True)
                    await session.rollback()
                    return models.CommentResponse(count=0, comments=[])

        # 检查弹幕获取缓存
        cache_key = f"comments_{episodeId}"
        comments_data = await _get_db_cache(session, COMMENTS_FETCH_CACHE_PREFIX, cache_key)
        if comments_data:
            logger.info(f"从缓存中获取 episodeId={episodeId} 的弹幕")

            # 即使从缓存获取，也需要保存到数据库和XML文件
            if comments_data and str(episodeId).startswith("25") and len(str(episodeId)) >= 13:
                try:
                    # 解析episodeId获取anime_id和episode_number
                    episode_id_str = str(episodeId)
                    real_anime_id = int(episode_id_str[2:8])
                    episode_number = int(episode_id_str[10:14])

                    # 获取映射信息
                    mapping_data = await _get_episode_mapping(session, episodeId)
                    if mapping_data:
                        provider = mapping_data["provider"]
                        media_id = mapping_data["media_id"]
                        original_title = mapping_data["original_title"]

                        # 复用现有的保存逻辑：查找或创建动画条目、源关联、分集条目，然后保存弹幕
                        try:
                            # 1. 首先尝试根据real_anime_id查找已存在的anime记录
                            existing_anime_stmt = select(Anime).where(Anime.id == real_anime_id)
                            existing_anime_result = await session.execute(existing_anime_stmt)
                            existing_anime = existing_anime_result.scalar_one_or_none()

                            if existing_anime:
                                # 如果已存在，直接使用
                                anime_id = existing_anime.id
                                logger.info(f"找到已存在的番剧: ID={anime_id}, 标题='{existing_anime.title}', 季数={existing_anime.season}")
                            else:
                                # 如果不存在，解析标题并检查数据库中是否已有相同条目
                                parsed_info = parse_search_keyword(original_title)
                                base_title = parsed_info["title"]

                                # 直接在数据库中查找相同标题的条目（不应用标题识别转换）
                                stmt = select(Anime.id, Anime.title).where(
                                    Anime.title == base_title,
                                    Anime.season == 1
                                )
                                result = await session.execute(stmt)
                                existing_anime_row = result.mappings().first()

                                if existing_anime_row:
                                    # 如果已存在，直接使用
                                    anime_id = existing_anime_row['id']
                                    logger.info(f"找到已存在的番剧（按标题）: ID={anime_id}, 标题='{base_title}'")
                                else:
                                    # 如果不存在，创建新的（使用解析后的纯标题）
                                    anime_id = await crud.get_or_create_anime(
                                        session, base_title, "tv_series", 1,
                                        None, None, None, None, provider
                                    )

                            # 2. 创建源关联
                            source_id = await crud.link_source_to_anime(
                                session, anime_id, provider, media_id
                            )

                            # 3. 创建分集条目（使用原生标题）
                            episode_title = f"第{episode_number}集"  # 缓存弹幕时暂时使用默认标题
                            episode_db_id = await crud.create_episode_if_not_exists(
                                session, anime_id, source_id, episode_number,
                                episode_title, "", f"{provider}_{media_id}_{episode_number}"
                            )

                            # 4. 保存弹幕到数据库和XML文件
                            added_count = await crud.save_danmaku_for_episode(
                                session, episode_db_id, comments_data, config_manager
                            )
                            await session.commit()

                            logger.info(f"缓存弹幕已保存到数据库和XML文件: anime_id={anime_id}, source_id={source_id}, episode_db_id={episode_db_id}, 保存了 {added_count} 条弹幕")
                        except Exception as save_error:
                            logger.error(f"保存缓存弹幕到数据库失败: {save_error}", exc_info=True)
                            await session.rollback()
                except Exception as e:
                    logger.warning(f"处理缓存弹幕保存时发生错误: {e}")
                    # 不影响弹幕返回，继续执行
        else:
            # 2. 检查是否是后备搜索的特殊episodeId（以25开头的新格式）
            if str(episodeId).startswith("25") and len(str(episodeId)) >= 13:  # 新的ID格式
                # 解析episodeId：25 + animeId(6位) + 源顺序(2位) + 集编号(4位)
                episode_id_str = str(episodeId)
                real_anime_id = int(episode_id_str[2:8])  # 提取真实animeId
                _ = int(episode_id_str[8:10])  # 提取源顺序（暂时不使用）
                episode_number = int(episode_id_str[10:14])  # 提取集编号

            # 查找对应的映射信息
            episode_url = None
            provider = None

            # 首先尝试从数据库缓存中获取episodeId的映射
            mapping_data = await _get_episode_mapping(session, episodeId)
            if mapping_data:
                episode_url = mapping_data["media_id"]
                provider = mapping_data["provider"]
                logger.info(f"从缓存获取episodeId映射: episodeId={episodeId}, provider={provider}, url={episode_url}")
            else:
                # 如果缓存中没有，从数据库缓存中查找
                # 首先尝试根据用户最后的选择来确定源
                try:
                    all_cache_keys = await crud.get_cache_keys_by_pattern(session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
                    for cache_key in all_cache_keys:
                        search_key = cache_key.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
                        search_info = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)

                        if search_info and search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
                            # 检查是否有用户最后的选择记录
                            last_bangumi_id = await _get_db_cache(session, USER_LAST_BANGUMI_CHOICE_PREFIX, search_key)
                            if last_bangumi_id and last_bangumi_id in search_info["bangumi_mapping"]:
                                mapping_info = search_info["bangumi_mapping"][last_bangumi_id]
                                # 检查真实animeId是否匹配
                                if mapping_info.get("real_anime_id") == real_anime_id:
                                    episode_url = mapping_info["media_id"]
                                    provider = mapping_info["provider"]
                                    logger.info(f"根据用户最后选择找到映射: bangumiId={last_bangumi_id}, provider={provider}")
                                    break
                except Exception as e:
                    logger.error(f"查找用户选择映射失败: {e}")

                # 如果没有找到用户最后的选择，则使用原来的逻辑
                if not episode_url:
                    try:
                        all_cache_keys_fallback = await crud.get_cache_keys_by_pattern(session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
                        for cache_key_fallback in all_cache_keys_fallback:
                            search_key_fallback = cache_key_fallback.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
                            search_info_fallback = await _get_db_cache(session, FALLBACK_SEARCH_CACHE_PREFIX, search_key_fallback)

                            if search_info_fallback and search_info_fallback.get("status") == "completed" and "bangumi_mapping" in search_info_fallback:
                                for bangumi_id, mapping_info in search_info_fallback["bangumi_mapping"].items():
                                    # 检查真实animeId是否匹配
                                    if mapping_info.get("real_anime_id") == real_anime_id:
                                        episode_url = mapping_info["media_id"]
                                        provider = mapping_info["provider"]
                                        logger.info(f"根据真实animeId={real_anime_id}找到映射: bangumiId={bangumi_id}, provider={provider}")
                                        break
                                if episode_url:
                                    break
                    except Exception as e:
                        logger.error(f"查找真实animeId映射失败: {e}")

            if episode_url and provider:
                logger.info(f"找到后备搜索映射: provider={provider}, url={episode_url}")

                # 检查是否已有相同的弹幕下载任务正在进行
                task_unique_key = f"fallback_comments_{episodeId}"
                existing_task = await crud.find_recent_task_by_unique_key(session, task_unique_key, 1)
                if existing_task:
                    logger.info(f"弹幕下载任务已存在: {task_unique_key}，等待任务完成...")
                    # 等待最多30秒，检查缓存中是否有结果
                    cache_key = f"comments_{episodeId}"
                    for i in range(30):
                        await asyncio.sleep(1)
                        cached_comments_existing = await _get_db_cache(session, COMMENTS_FETCH_CACHE_PREFIX, cache_key)
                        if cached_comments_existing:
                            logger.info(f"从缓存中获取到弹幕数据，共 {len(cached_comments_existing)} 条")
                            break
                    # 继续执行后续逻辑，从缓存中获取弹幕

                # 3. 将弹幕下载包装成任务管理器任务
                # 保存当前作用域的变量，避免闭包问题
                current_provider = provider
                current_episode_url = episode_url
                current_episode_number = episode_number
                current_episodeId = episodeId
                current_config_manager = config_manager
                current_scraper_manager = scraper_manager
                current_rate_limiter = rate_limiter
                current_episodes_list_ref = None  # 用于保存整部剧的分集列表

                async def download_comments_task(task_session, progress_callback):
                    try:
                        await progress_callback(10, "开始获取弹幕...")
                        scraper = current_scraper_manager.get_scraper(current_provider)
                        if scraper:
                            # 首先获取分集列表
                            await progress_callback(30, "获取分集列表...")
                            # 查找映射信息（根据real_anime_id匹配）
                            mapping_info = None
                            try:
                                all_cache_keys_mapping = await crud.get_cache_keys_by_pattern(task_session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
                                for cache_key_mapping in all_cache_keys_mapping:
                                    search_key = cache_key_mapping.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
                                    last_bangumi_id = await _get_db_cache(task_session, USER_LAST_BANGUMI_CHOICE_PREFIX, search_key)
                                    if last_bangumi_id:
                                        search_info = await _get_db_cache(task_session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
                                        if search_info and last_bangumi_id in search_info.get("bangumi_mapping", {}):
                                            temp_mapping = search_info["bangumi_mapping"][last_bangumi_id]
                                            # 检查real_anime_id是否匹配
                                            if temp_mapping.get("real_anime_id") == real_anime_id:
                                                mapping_info = temp_mapping
                                                logger.info(f"找到匹配的映射信息: search_key={search_key}, bangumiId={last_bangumi_id}, real_anime_id={real_anime_id}")
                                                break
                            except Exception as e:
                                logger.error(f"查找映射信息失败: {e}")

                            if not mapping_info:
                                logger.error(f"无法找到real_anime_id={real_anime_id}的映射信息")
                                return None

                            media_type = mapping_info.get("type", "movie")
                            episodes_list = await scraper.get_episodes(current_episode_url, db_media_type=media_type)
                            # 保存到外层作用域，用于后续批量创建Episode记录
                            nonlocal current_episodes_list_ref
                            current_episodes_list_ref = episodes_list

                        if episodes_list and len(episodes_list) >= current_episode_number:
                            # 获取对应集数的分集信息（episode_number是从1开始的）
                            target_episode = episodes_list[current_episode_number - 1]
                            provider_episode_id = target_episode.episodeId
                            # 使用原生分集标题
                            original_episode_title = target_episode.title

                            if provider_episode_id:
                                episode_id_for_comments = scraper.format_episode_id_for_comments(provider_episode_id)

                                # 使用三线程下载模式获取弹幕
                                virtual_episode = ProviderEpisodeInfo(
                                    provider=current_provider,
                                    episodeIndex=current_episode_number,
                                    title=original_episode_title,  # 使用原生标题
                                    episodeId=episode_id_for_comments,
                                    url=""
                                )

                                # 使用并发下载获取弹幕（三线程模式）
                                async def dummy_progress_callback(_, _unused):
                                    pass  # 空的异步进度回调，忽略所有参数

                                download_results = await tasks._download_episode_comments_concurrent(
                                    scraper, [virtual_episode], current_rate_limiter,
                                    dummy_progress_callback,
                                    is_fallback=True,
                                    fallback_type="search"
                                )

                                # 提取弹幕数据
                                raw_comments_data = None
                                if download_results and len(download_results) > 0:
                                    _, comments = download_results[0]  # 忽略episode_index
                                    raw_comments_data = comments
                            else:
                                logger.warning(f"无法获取 {current_provider} 的分集ID: episode_number={current_episode_number}")
                                raw_comments_data = None
                        else:
                            logger.warning(f"从 {current_provider} 获取分集列表失败或集数不足: media_id={current_episode_url}, episode_number={current_episode_number}")
                            raw_comments_data = None

                        if raw_comments_data:
                                logger.info(f"成功从 {current_provider} 获取 {len(raw_comments_data)} 条弹幕")
                                await progress_callback(90, "弹幕获取完成，正在创建数据库条目...")

                                # 参考 WebUI 导入逻辑：先获取弹幕成功，再创建数据库条目
                                try:
                                    # 从映射信息中获取创建条目所需的数据
                                    original_title = mapping_info.get("original_title", "未知标题")
                                    media_type = mapping_info.get("type", "movie")

                                    # 从搜索缓存中获取更多信息（年份、海报等）和搜索关键词
                                    year = None
                                    image_url = None
                                    search_keyword = None
                                    try:
                                        all_cache_keys_info = await crud.get_cache_keys_by_pattern(task_session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
                                        for cache_key_info in all_cache_keys_info:
                                            search_key = cache_key_info.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
                                            last_bangumi_id = await _get_db_cache(task_session, USER_LAST_BANGUMI_CHOICE_PREFIX, search_key)
                                            if last_bangumi_id:
                                                search_info = await _get_db_cache(task_session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)
                                                if search_info and last_bangumi_id in search_info.get("bangumi_mapping", {}):
                                                    # 获取搜索关键词（从search_key中提取）
                                                    if search_key.startswith("search_"):
                                                        # 从数据库缓存中获取原始搜索词
                                                        search_keyword = search_info.get("search_term")

                                                    for result in search_info.get("results", []):
                                                        # result 是 DandanSearchAnimeItem 对象，使用属性访问
                                                        if hasattr(result, 'bangumiId') and result.bangumiId == last_bangumi_id:
                                                            year = getattr(result, 'year', None)
                                                            image_url = getattr(result, 'imageUrl', None)
                                                            break
                                                    break
                                    except Exception as e:
                                        logger.error(f"查找搜索缓存信息失败: {e}")

                                    # 解析搜索关键词，提取纯标题（如"天才基本法 S01E13" -> "天才基本法"）
                                    search_term = search_keyword or original_title
                                    parsed_info = parse_search_keyword(search_term)
                                    base_title = parsed_info["title"]

                                    # 由于我们在分配real_anime_id时已经检查了数据库，这里直接使用real_anime_id
                                    # 如果数据库中已有相同标题的条目，real_anime_id就是已有的anime_id
                                    # 如果没有，real_anime_id就是新分配的anime_id，需要创建条目

                                    # 检查数据库中是否已有这个anime_id的条目
                                    stmt = select(Anime.id).where(Anime.id == real_anime_id)
                                    result = await task_session.execute(stmt)
                                    existing_anime_row = result.scalar_one_or_none()

                                    if existing_anime_row:
                                        # 如果已存在，直接使用
                                        anime_id = real_anime_id
                                        logger.info(f"使用已存在的番剧: ID={anime_id}")
                                    else:
                                        # 如果不存在，直接创建新的（使用real_anime_id作为指定ID）
                                        new_anime = Anime(
                                            id=real_anime_id,
                                            title=base_title,
                                            type=media_type,
                                            season=1,
                                            year=year,
                                            imageUrl=image_url,
                                            createdAt=get_now()
                                        )
                                        task_session.add(new_anime)
                                        await task_session.flush()  # 确保ID可用
                                        anime_id = real_anime_id
                                        logger.info(f"创建新番剧: ID={anime_id}, 标题='{base_title}', 年份={year}")

                                        # 同步PostgreSQL序列(避免主键冲突)
                                        await sync_postgres_sequence(task_session)

                                    # 2. 创建源关联
                                    source_id = await crud.link_source_to_anime(
                                        task_session, anime_id, current_provider, current_episode_url
                                    )

                                    # 获取source_order用于生成虚拟episodeId
                                    stmt_source = select(AnimeSource.sourceOrder).where(AnimeSource.id == source_id)
                                    result_source = await task_session.execute(stmt_source)
                                    source_order = result_source.scalar_one()

                                    # 3. 创建分集条目（使用原生标题）
                                    episode_db_id = await crud.create_episode_if_not_exists(
                                        task_session, anime_id, source_id, current_episode_number,
                                        original_episode_title, "", provider_episode_id
                                    )

                                    # 为整部剧创建一条缓存记录(不下载弹幕,不创建数据库记录)
                                    # 这样播放器推理下一集时能通过缓存触发弹幕下载
                                    # 缓存条目保留3小时,支持连续播放
                                    if current_episodes_list_ref:
                                        try:
                                            # 使用虚拟anime_id作为缓存key的前缀
                                            # 格式: fallback_episode_25000166010000 (最后4位为0000表示整部剧)
                                            virtual_anime_base = 25000000000000 + anime_id * 1000000 + source_order * 10000
                                            fallback_series_key = f"fallback_episode_{virtual_anime_base}"

                                            cache_value = {
                                                "real_anime_id": anime_id,
                                                "provider": current_provider,
                                                "mediaId": current_episode_url,
                                                "final_title": base_title,
                                                "final_season": 1,
                                                "media_type": media_type,
                                                "imageUrl": image_url,
                                                "year": year,
                                                "total_episodes": len(current_episodes_list_ref)
                                            }

                                            # 存储到数据库缓存,3小时过期
                                            await crud.set_cache(task_session, fallback_series_key, cache_value, 10800)
                                            await task_session.flush()
                                            logger.info(f"为整部剧创建了缓存记录: {fallback_series_key} (共{len(current_episodes_list_ref)}集)")
                                        except Exception as e:
                                            logger.warning(f"创建缓存记录失败: {e}")

                                    # 4. 保存弹幕到数据库
                                    added_count = await crud.save_danmaku_for_episode(
                                        task_session, episode_db_id, raw_comments_data, current_config_manager
                                    )
                                    await task_session.commit()

                                    logger.info(f"数据库条目创建完成: anime_id={anime_id}, source_id={source_id}, episode_db_id={episode_db_id}, 保存了 {added_count} 条弹幕")

                                    # 清除缓存中所有使用这个real_anime_id的映射关系
                                    # 因为数据库中已经有了这个ID的记录，下次分配时不会再使用这个ID
                                    try:
                                        all_cache_keys_cleanup = await crud.get_cache_keys_by_pattern(task_session, f"{FALLBACK_SEARCH_CACHE_PREFIX}*")
                                        for cache_key_cleanup in all_cache_keys_cleanup:
                                            search_key = cache_key_cleanup.replace(FALLBACK_SEARCH_CACHE_PREFIX, "")
                                            search_info = await _get_db_cache(task_session, FALLBACK_SEARCH_CACHE_PREFIX, search_key)

                                            if search_info and search_info.get("status") == "completed" and "bangumi_mapping" in search_info:
                                                for bangumi_id, mapping_info in list(search_info["bangumi_mapping"].items()):
                                                    if mapping_info.get("real_anime_id") == real_anime_id:
                                                        # 从映射中移除这个条目
                                                        del search_info["bangumi_mapping"][bangumi_id]
                                                        logger.info(f"清除缓存映射: search_key={search_key}, bangumiId={bangumi_id}, real_anime_id={real_anime_id}")
                                                # 保存更新后的缓存
                                                await _set_db_cache(task_session, FALLBACK_SEARCH_CACHE_PREFIX, search_key, search_info, FALLBACK_SEARCH_CACHE_TTL)
                                    except Exception as e:
                                        logger.error(f"清除缓存映射失败: {e}")

                                except Exception as db_error:
                                    logger.error(f"创建数据库条目失败: {db_error}", exc_info=True)
                                    await task_session.rollback()

                                # 存储到数据库缓存中
                                cache_key = f"comments_{current_episodeId}"
                                await _set_db_cache(task_session, COMMENTS_FETCH_CACHE_PREFIX, cache_key, raw_comments_data, COMMENTS_FETCH_CACHE_TTL)

                                # 返回弹幕数据（无论数据库操作是否成功）
                                return raw_comments_data
                        else:
                            logger.warning(f"获取弹幕失败")
                            return None
                    except Exception as e:
                        logger.error(f"弹幕下载任务执行失败: {e}", exc_info=True)
                        return None

                # 提交弹幕下载任务
                try:
                    task_id, done_event = await task_manager.submit_task(
                        download_comments_task,
                        f"后备搜索弹幕下载: episodeId={episodeId}",
                        unique_key=task_unique_key,
                        task_type="download_comments",
                        queue_type="fallback"  # 使用后备队列
                    )
                    logger.info(f"已提交弹幕下载任务: {task_id}")

                    # 等待任务完成，但设置较短的超时时间（30秒）
                    try:
                        await asyncio.wait_for(done_event.wait(), timeout=30.0)
                        # 任务完成，检查缓存中是否有结果
                        cache_key = f"comments_{episodeId}"
                        comments_data = await _get_db_cache(session, COMMENTS_FETCH_CACHE_PREFIX, cache_key)
                        if comments_data:
                            logger.info(f"弹幕下载任务快速完成，获得 {len(comments_data)} 条弹幕")
                        else:
                            logger.warning(f"任务完成但缓存中未找到弹幕数据")
                    except asyncio.TimeoutError:
                        logger.info(f"弹幕下载任务未在30秒内完成，任务将继续在后台运行")
                        # 任务继续在后台运行，下次访问时就能从数据库获取

                except HTTPException as e:
                    if e.status_code == 409:  # 任务已在运行中
                        logger.info(f"弹幕下载任务已在运行中，等待现有任务完成...")
                        # 尝试等待现有任务完成，但设置较短的超时时间
                        try:
                            # 等待一段时间，看是否能从缓存中获取结果
                            await asyncio.sleep(5.0)  # 等待5秒
                            cache_key = f"comments_{episodeId}"
                            comments_data = await _get_db_cache(session, COMMENTS_FETCH_CACHE_PREFIX, cache_key)
                            if comments_data:
                                logger.info(f"从缓存中获取到弹幕数据: {len(comments_data)} 条")
                            else:
                                logger.info(f"等待5秒后仍未从缓存获取到数据，任务可能仍在进行中")
                        except Exception as wait_error:
                            logger.warning(f"等待现有任务时发生错误: {wait_error}")
                    else:
                        logger.error(f"提交弹幕下载任务失败: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"提交弹幕下载任务失败: {e}", exc_info=True)

        # 如果仍然没有弹幕数据，返回空结果
        if not comments_data:
            logger.warning(f"无法获取 episodeId={episodeId} 的弹幕数据")
            return models.CommentResponse(count=0, comments=[])

    # 应用弹幕输出上限（按时间段均匀采样，带缓存）
    limit_str = await config_manager.get('danmakuOutputLimitPerSource', '-1')
    try:
        limit = int(limit_str)
    except (ValueError, TypeError):
        limit = -1

    # 应用限制：按时间段均匀采样
    if limit > 0 and len(comments_data) > limit:
        # 检查缓存
        cache_key = f"sampled_{episodeId}_{limit}"
        current_time = time.time()

        # 尝试从数据库缓存获取
        cached_data = await _get_db_cache(session, SAMPLED_COMMENTS_CACHE_PREFIX, cache_key)
        if cached_data:
            # 缓存格式: {"comments": [...], "timestamp": 123456.789}
            cached_comments = cached_data.get("comments", [])
            cached_time = cached_data.get("timestamp", 0)
            if current_time - cached_time <= SAMPLED_CACHE_TTL:
                logger.info(f"使用缓存的采样结果: episodeId={episodeId}, limit={limit}, 缓存时间={int(current_time - cached_time)}秒前")
                comments_data = cached_comments
            else:
                # 缓存过期,重新采样
                logger.info(f"弹幕数量 {len(comments_data)} 超过限制 {limit}，开始均匀采样 (缓存已过期)")
                original_count = len(comments_data)
                comments_data = sample_comments_evenly(comments_data, limit)
                logger.info(f"弹幕采样完成: {original_count} -> {len(comments_data)} 条")

                # 更新缓存
                cache_value = {"comments": comments_data, "timestamp": current_time}
                await _set_db_cache(session, SAMPLED_COMMENTS_CACHE_PREFIX, cache_key, cache_value, SAMPLED_COMMENTS_CACHE_TTL_DB)
        else:
            # 无缓存,执行采样
            logger.info(f"弹幕数量 {len(comments_data)} 超过限制 {limit}，开始均匀采样")
            original_count = len(comments_data)
            comments_data = sample_comments_evenly(comments_data, limit)
            logger.info(f"弹幕采样完成: {original_count} -> {len(comments_data)} 条")

            # 存入缓存
            cache_value = {"comments": comments_data, "timestamp": current_time}
            await _set_db_cache(session, SAMPLED_COMMENTS_CACHE_PREFIX, cache_key, cache_value, SAMPLED_COMMENTS_CACHE_TTL_DB)
            logger.debug(f"采样结果已缓存: {cache_key}")

    # UA 已由 get_token_from_path 依赖项记录
    logger.debug(f"弹幕接口响应 (episodeId: {episodeId}): 总计 {len(comments_data)} 条弹幕")

    # 修正：使用统一的弹幕处理函数，以确保输出格式符合 dandanplay 客户端规范
    processed_comments = _process_comments_for_dandanplay(comments_data)

    return models.CommentResponse(count=len(processed_comments), comments=processed_comments)


# --- 路由挂载 ---
# 将实现路由挂载到主路由上，以支持两种URL结构。

# 2. 挂载以支持兼容路径: /{token}/api/v2/...
dandan_router.include_router(implementation_router, prefix="/{token}/api/v2")
# 1. 挂载以支持直接路径: /{token}/...
dandan_router.include_router(implementation_router, prefix="/{token}")