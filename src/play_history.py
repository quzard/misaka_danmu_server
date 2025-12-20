"""
播放历史记录模块
用于记录和管理用户最近播放的番剧，支持 @SXDM 刷新弹幕指令
"""

import logging
from typing import List, Dict
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud
from .orm_models import Anime, AnimeSource, Episode

logger = logging.getLogger(__name__)


async def record_play_history(
    token: str,
    episode_id: int
) -> None:
    """
    记录播放历史到缓存（只记录番剧，不记录具体集数）
    保留最近5部番剧，使用 #A #B #C #D #E 标识

    此函数设计为后台异步执行，内部自己创建 session

    Args:
        token: 用户 token
        episode_id: 分集 ID
    """
    from .database import get_session

    try:
        async with get_session() as session:
            # 查询分集所属的番剧信息
            stmt = (
                select(Anime.id, Anime.title)
                .join(AnimeSource, AnimeSource.animeId == Anime.id)
                .join(Episode, Episode.sourceId == AnimeSource.id)
                .where(Episode.id == episode_id)
            )
            result = await session.execute(stmt)
            row = result.first()
            if not row:
                logger.debug(f"未找到分集信息: episodeId={episode_id}")
                return

            anime_id, anime_title = row

            # 获取现有播放历史
            cache_key = f"play_history_{token}"
            history = await crud.get_cache(session, cache_key)
            if not history:
                history = []

            # 移除相同 animeId 的旧记录（去重）
            history = [h for h in history if h.get("animeId") != anime_id]

            # 插入到最前面（#A 位置）
            new_record = {
                "animeId": anime_id,
                "animeTitle": anime_title,
                "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            history.insert(0, new_record)

            # 只保留最近5条
            history = history[:5]

            # 保存回缓存（10分钟）
            await crud.set_cache(session, cache_key, history, 600)
            logger.info(f"✓ 已记录播放历史: token={token[:8]}..., anime={anime_title}")
    except Exception as e:
        logger.error(f"记录播放历史失败: episodeId={episode_id}, error={e}", exc_info=True)


async def get_play_history(
    session: AsyncSession,
    token: str
) -> List[Dict]:
    """
    获取播放历史

    Args:
        session: 数据库会话
        token: 用户 token

    Returns:
        播放历史列表，每项包含 animeId, animeTitle, updateTime
    """
    cache_key = f"play_history_{token}"
    history = await crud.get_cache(session, cache_key)
    return history if history else []


async def clear_play_history(
    session: AsyncSession,
    token: str
) -> bool:
    """
    清除播放历史
    
    Args:
        session: 数据库会话
        token: 用户 token
        
    Returns:
        是否成功清除
    """
    cache_key = f"play_history_{token}"
    return await crud.delete_cache(session, cache_key)

