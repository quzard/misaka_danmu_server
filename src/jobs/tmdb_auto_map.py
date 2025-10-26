import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
import httpx

from .. import crud, models
from .base import BaseJob
from ..rate_limiter import RateLimiter
from ..task_manager import TaskManager, TaskSuccess
from ..scraper_manager import ScraperManager
from ..metadata_manager import MetadataSourceManager
from ..ai_matcher import AIMatcher

class TmdbAutoMapJob(BaseJob):
    job_type = "tmdbAutoScrape"
    job_name = "TMDB自动刮削与剧集组映射"
    description = "自动从TMDB刮削已导入作品的别名、剧集组信息，更新分集映射关系。帮助解决分集顺序不一致的问题。"

    # 修正：此任务不涉及弹幕下载，因此移除不必要的 rate_limiter 依赖
    # 修正：接收正确的依赖项
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], task_manager: TaskManager, metadata_manager: MetadataSourceManager):
        # 由于此任务的依赖项与基类不同，我们不调用 super().__init__，
        # 而是直接初始化此任务所需的属性。
        self._session_factory = session_factory
        self.task_manager = task_manager
        self.metadata_manager = metadata_manager
        self.logger = logging.getLogger(self.__class__.__name__)


    async def run(self, session: AsyncSession, progress_callback: Callable):
        """
        定时任务的核心逻辑。
        1. 获取所有TV系列作品
        2. 对于没有TMDB ID的作品，通过标题搜索TMDB获取ID
        3. 刮削别名信息
        4. 获取并映射剧集组信息
        """
        self.logger.info(f"开始执行 [{self.job_name}] 定时任务...")
        await progress_callback(0, "正在初始化...")

        # 为元数据管理器调用创建一个虚拟用户对象
        user = models.User(id=0, username="scheduled_task")

        # 注册默认配置(如果不存在)
        from ..ai_matcher import DEFAULT_AI_MATCH_PROMPT, DEFAULT_AI_RECOGNITION_PROMPT, DEFAULT_AI_ALIAS_VALIDATION_PROMPT
        await crud.initialize_configs(session, {
            "aiMatchPrompt": (DEFAULT_AI_MATCH_PROMPT, "AI智能匹配提示词"),
            "aiRecognitionPrompt": (DEFAULT_AI_RECOGNITION_PROMPT, "AI辅助识别提示词"),
            "aiAliasValidationPrompt": (DEFAULT_AI_ALIAS_VALIDATION_PROMPT, "AI别名验证提示词")
        })

        # 初始化AI matcher (如果启用)
        ai_matcher = None
        ai_recognition_enabled = False
        try:
            ai_match_enabled = await crud.get_config_value(session, "aiMatchEnabled") == "true"
            ai_recognition_enabled = await crud.get_config_value(session, "aiRecognitionEnabled") == "true"

            if ai_match_enabled and ai_recognition_enabled:
                self.logger.info("AI辅助识别已启用")
                config = {
                    "ai_match_provider": await crud.get_config_value(session, "aiMatchProvider") or "deepseek",
                    "ai_match_api_key": await crud.get_config_value(session, "aiMatchApiKey"),
                    "ai_match_base_url": await crud.get_config_value(session, "aiMatchBaseUrl"),
                    "ai_match_model": await crud.get_config_value(session, "aiMatchModel") or "deepseek-chat",
                    "ai_match_prompt": await crud.get_config_value(session, "aiMatchPrompt") or DEFAULT_AI_MATCH_PROMPT,
                    "ai_recognition_prompt": await crud.get_config_value(session, "aiRecognitionPrompt") or DEFAULT_AI_RECOGNITION_PROMPT
                }
                ai_matcher = AIMatcher(config)
        except Exception as e:
            self.logger.warning(f"初始化AI matcher失败: {e}, 将使用传统搜索")

        # 获取所有TV系列作品
        from ..orm_models import Anime, AnimeMetadata
        from sqlalchemy import select
        stmt = (
            select(
                Anime.id.label("animeId"),
                Anime.title,
                Anime.year,
                Anime.type,
                AnimeMetadata.tmdbId,
                AnimeMetadata.tmdbEpisodeGroupId
            )
            .outerjoin(AnimeMetadata, Anime.id == AnimeMetadata.animeId)
            .where(Anime.type == 'tv_series')
        )
        result = await session.execute(stmt)
        shows_to_update = [dict(row) for row in result.mappings()]

        total_shows = len(shows_to_update)
        self.logger.info(f"找到 {total_shows} 个TV系列作品需要处理。")
        await progress_callback(5, f"找到 {total_shows} 个作品待处理")

        processed_count = 0
        scraped_count = 0
        mapped_count = 0

        for i, show in enumerate(shows_to_update):
            current_progress = 5 + int((i / total_shows) * 95) if total_shows > 0 else 95
            anime_id = show['animeId']
            title = show['title']
            year = show.get('year')
            tmdb_id = show.get('tmdbId')

            await progress_callback(current_progress, f"正在处理: {title} ({i+1}/{total_shows})")
            self.logger.info(f"正在处理: '{title}' (Anime ID: {anime_id}, TMDB ID: {tmdb_id or '无'})")

            try:
                # 步骤 1: 如果没有TMDB ID，尝试通过标题搜索获取
                if not tmdb_id:
                    self.logger.info(f"'{title}' 没有TMDB ID，尝试搜索...")
                    try:
                        # 使用AI标准化标题 (如果启用)
                        search_title = title
                        search_year = year
                        search_type = show.get('type', 'tv_series')

                        use_episode_group = False
                        recognized_season = None

                        if ai_matcher and ai_recognition_enabled:
                            try:
                                recognition_result = await ai_matcher.recognize_title(
                                    title=title,
                                    year=year,
                                    anime_type=search_type
                                )
                                if recognition_result:
                                    search_title = recognition_result.get("search_title", title)
                                    search_year = recognition_result.get("year", year)
                                    search_type = recognition_result.get("type", search_type)
                                    use_episode_group = recognition_result.get("use_episode_group", False)
                                    recognized_season = recognition_result.get("season")

                                    if recognized_season:
                                        self.logger.info(f"AI识别到季度: {recognized_season}")
                                    if use_episode_group:
                                        self.logger.info(f"AI识别: 该作品需要使用剧集组")

                                    self.logger.info(f"AI标准化: '{title}' → '{search_title}' (year={search_year}, type={search_type})")
                            except Exception as e:
                                self.logger.warning(f"AI标准化失败: {e}, 使用原标题搜索")

                        # 根据类型选择mediaType
                        media_type = "movie" if search_type == "movie" else "tv"

                        search_results = await self.metadata_manager.search("tmdb", search_title, user, mediaType=media_type)
                        if search_results:
                            # 选择第一个结果（可以根据年份进一步筛选）
                            best_match = search_results[0]
                            if search_year:
                                # 尝试找到年份匹配的结果
                                for result in search_results:
                                    if result.year == search_year:
                                        best_match = result
                                        break

                            tmdb_id = best_match.tmdbId
                            self.logger.info(f"为 '{title}' 找到TMDB ID: {tmdb_id}")

                            # 保存TMDB ID到数据库
                            await crud.update_metadata_if_empty(
                                session,
                                anime_id,
                                tmdb_id=tmdb_id
                            )
                            await session.commit()
                            scraped_count += 1
                        else:
                            self.logger.warning(f"未能为 '{title}' 找到TMDB搜索结果。")
                            continue
                    except Exception as e:
                        self.logger.error(f"搜索 '{title}' 时发生错误: {e}")
                        continue

                # 步骤 2: 获取媒体详情，包括别名
                details = await self.metadata_manager.get_details("tmdb", tmdb_id, user, mediaType="tv")
                if not details:
                    self.logger.warning(f"未能从 TMDB 获取 '{title}' (ID: {tmdb_id}) 的详情。")
                    continue

                # 步骤 3: 更新别名（使用AI验证和分类）
                if ai_matcher and ai_recognition_enabled:
                    # 收集所有别名
                    all_aliases = []
                    if details.nameEn: all_aliases.append(details.nameEn)
                    if details.nameJp: all_aliases.append(details.nameJp)
                    if details.nameRomaji: all_aliases.append(details.nameRomaji)
                    if details.aliasesCn: all_aliases.extend(details.aliasesCn)

                    if all_aliases:
                        self.logger.info(f"正在使用AI验证 '{title}' 的 {len(all_aliases)} 个别名...")
                        validated_aliases = ai_matcher.validate_aliases(
                            title=title,
                            year=year,
                            anime_type=search_type,  # 使用search_type
                            aliases=all_aliases
                        )

                        if validated_aliases:
                            # 使用AI验证后的别名
                            aliases_to_update = {
                                "name_en": validated_aliases.get("nameEn"),
                                "name_jp": validated_aliases.get("nameJp"),
                                "name_romaji": validated_aliases.get("nameRomaji"),
                                "aliases_cn": validated_aliases.get("aliasesCn", [])
                            }
                            if any(aliases_to_update.values()):
                                await crud.update_anime_aliases_if_empty(session, anime_id, aliases_to_update)
                                self.logger.info(f"为 '{title}' 更新了AI验证后的别名。")
                        else:
                            self.logger.warning(f"AI别名验证失败,使用原始别名")
                            # 降级到原始别名
                            aliases_to_update = {
                                "name_en": details.nameEn,
                                "name_jp": details.nameJp,
                                "name_romaji": details.nameRomaji,
                                "aliases_cn": details.aliasesCn
                            }
                            if any(aliases_to_update.values()):
                                await crud.update_anime_aliases_if_empty(session, anime_id, aliases_to_update)
                                self.logger.info(f"为 '{title}' 更新了原始别名。")
                else:
                    # 不使用AI,直接更新原始别名
                    aliases_to_update = {
                        "name_en": details.nameEn,
                        "name_jp": details.nameJp,
                        "name_romaji": details.nameRomaji,
                        "aliases_cn": details.aliasesCn
                    }
                    if any(aliases_to_update.values()):
                        await crud.update_anime_aliases_if_empty(session, anime_id, aliases_to_update)
                        self.logger.info(f"为 '{title}' 更新了别名。")

                # 步骤 4: 获取所有剧集组
                tmdb_source = self.metadata_manager.sources.get("tmdb")
                if not tmdb_source or not hasattr(tmdb_source, 'get_all_episode_groups'):
                    self.logger.warning(f"TMDB源不支持 get_all_episode_groups 方法，跳过 '{title}' 的剧集组处理。")
                    continue

                all_groups = await tmdb_source.get_all_episode_groups(int(tmdb_id), user)
                if not all_groups:
                    self.logger.info(f"'{title}' (TMDB ID: {tmdb_id}) 没有找到任何剧集组。")
                    continue
                
                self.logger.info(f"为 '{title}' 找到 {len(all_groups)} 个剧集组: {[g.get('name') for g in all_groups]}")

                # 步骤 4: 自动选择最佳剧集组进行处理
                # 如果AI识别到需要使用剧集组且有季度信息,尝试匹配对应季度的剧集组
                groups_to_process = []
                if use_episode_group and recognized_season is not None:
                    # 尝试找到匹配季度的剧集组
                    for g in all_groups:
                        group_name = g.get('name', '').lower()

                        # 特殊处理第0季(特别季)
                        if recognized_season == 0:
                            # 匹配 "specials", "season 0", "s00", "特别篇" 等
                            if ("special" in group_name or
                                "season 0" in group_name or
                                "s00" in group_name or
                                "s0" in group_name or
                                "特别" in group_name):
                                groups_to_process.append(g)
                                self.logger.info(f"AI识别: 找到特别季剧集组: {g.get('name')}")
                        else:
                            # 匹配 "season 2", "第2季", "s02" 等格式
                            if (f"season {recognized_season}" in group_name or
                                f"第{recognized_season}季" in group_name or
                                f"s{recognized_season:02d}" in group_name or
                                f"s{recognized_season}" in group_name):
                                groups_to_process.append(g)
                                self.logger.info(f"AI识别: 找到匹配季度{recognized_season}的剧集组: {g.get('name')}")

                # 如果没有找到匹配的,或者不需要使用剧集组,则使用默认逻辑
                if not groups_to_process:
                    groups_to_process = [g for g in all_groups if g.get('type') == 1]
                if not groups_to_process:
                    self.logger.info(f"'{title}' 没有找到“原始播出顺序”(type=1)的剧集组，跳过映射更新。")
                    continue
                
                self.logger.info(f"为 '{title}' 选择了 {len(groups_to_process)} 个剧集组进行映射更新。")

                # 步骤 5: 为每个选定的剧集组，更新映射表
                for group in groups_to_process:
                    group_id = group.get('id')
                    if not group_id:
                        continue
                    
                    self.logger.info(f"正在为 '{title}' 更新剧集组 '{group.get('name')}' (ID: {group_id}) 的映射...")
                    await self.metadata_manager.update_tmdb_mappings(int(tmdb_id), group_id, user)

                    # 步骤 6: 更新作品关联的主剧集组ID
                    await crud.update_anime_tmdb_group_id(session, anime_id, group_id)
                    self.logger.info(f"已将 '{title}' 的主剧集组ID更新为: {group_id}")
                    mapped_count += 1

                await session.commit() # 提交本次节目的所有更改
                processed_count += 1

            except Exception as e:
                self.logger.error(f"处理 '{title}' 时发生错误: {e}", exc_info=True)
                await session.rollback() # 出错时回滚
            finally:
                await asyncio.sleep(1) # 简单的速率限制，防止对TMDB API造成过大压力

        self.logger.info(f"定时任务 [{self.job_name}] 执行完毕。")
        self.logger.info(f"统计: 共处理 {processed_count}/{total_shows} 个作品, 刮削 {scraped_count} 个TMDB ID, 映射 {mapped_count} 个剧集组。")
        # 修正：抛出 TaskSuccess 异常，以便 TaskManager 可以用一个有意义的消息来结束任务
        raise TaskSuccess(f"任务执行完毕，共处理 {processed_count}/{total_shows} 个作品, 刮削 {scraped_count} 个TMDB ID, 映射 {mapped_count} 个剧集组。")