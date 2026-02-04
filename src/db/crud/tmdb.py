"""
Tmdb相关的CRUD操作
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, case, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from ..orm_models import Anime, TmdbEpisodeMapping
from .. import models
from src.core.timezone import get_now

logger = logging.getLogger(__name__)


async def save_tmdb_episode_group_mappings(session: AsyncSession, tmdb_tv_id: int, group_id: str, group_details: models.TMDBEpisodeGroupDetails):
    await session.execute(delete(TmdbEpisodeMapping).where(TmdbEpisodeMapping.tmdbEpisodeGroupId == group_id))

    mappings_to_insert = []
    sorted_groups = sorted(group_details.groups, key=lambda g: g.order)

    for custom_season_group in sorted_groups:
        if not custom_season_group.episodes: continue
        for custom_episode_index, episode in enumerate(custom_season_group.episodes):
            # 使用TMDB的episode_number作为绝对集数
            mappings_to_insert.append(
                TmdbEpisodeMapping(
                    tmdbTvId=tmdb_tv_id, tmdbEpisodeGroupId=group_id, tmdbEpisodeId=episode.id,
                    tmdbSeasonNumber=episode.seasonNumber, tmdbEpisodeNumber=episode.episodeNumber,
                    customSeasonNumber=custom_season_group.order, customEpisodeNumber=custom_episode_index + 1,
                    absoluteEpisodeNumber=episode.episodeNumber
                )
            )
    if mappings_to_insert:
        session.add_all(mappings_to_insert)
    await session.commit()
    logging.info(f"成功为剧集组 {group_id} 保存了 {len(mappings_to_insert)} 条分集映射。")

