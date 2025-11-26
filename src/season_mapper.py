"""季度映射模块 - 通过元数据源获取季度名称"""
import asyncio
import hashlib
import logging
import re
from typing import Optional, List, Any

from pydantic import Field
from . import models, crud
from .ai.ai_prompts import SEASON_KEYWORDS, SPECIAL_SEASON_KEYWORDS, DEFAULT_AI_SEASON_MATCH_PROMPT

logger = logging.getLogger(__name__)


def calculate_similarity(str1: str, str2: str) -> float:
    """
    计算两个字符串的相似度 (0-100)
    使用 thefuzz 库的多种算法综合评分

    Args:
        str1: 第一个字符串
        str2: 第二个字符串

    Returns:
        相似度百分比 (0-100)
    """
    if not str1 or not str2:
        return 0.0

    from thefuzz import fuzz

    # 转换为小写进行比较
    s1 = str1.lower().strip()
    s2 = str2.lower().strip()

    # 使用多种算法计算相似度,取最高值
    # 1. 简单相似度 - 适合完全匹配
    simple_ratio = fuzz.ratio(s1, s2)

    # 2. 部分相似度 - 适合子串匹配 (如 "无限列车篇" 在 "鬼灭之刃 无限列车篇" 中)
    partial_ratio = fuzz.partial_ratio(s1, s2)

    # 3. Token排序相似度 - 忽略词序 (如 "鬼灭之刃 无限列车篇" vs "无限列车篇 鬼灭之刃")
    token_sort_ratio = fuzz.token_sort_ratio(s1, s2)

    # 4. Token集合相似度 - 忽略重复词和词序
    token_set_ratio = fuzz.token_set_ratio(s1, s2)

    # 取最高分
    max_similarity = max(simple_ratio, partial_ratio, token_sort_ratio, token_set_ratio)

    return float(max_similarity)


def title_contains_season_name(title: str, season_name: str, threshold: float = 60.0) -> bool:
    """
    判断标题是否包含季度名称
    使用多种策略进行匹配,适合中文动漫标题

    Args:
        title: 搜索结果标题 (如 "鬼灭之刃 无限列车篇")
        season_name: 季度名称 (如 "无限列车篇", "第2季 无限列车篇")
        threshold: 相似度阈值 (默认60%)

    Returns:
        是否包含
    """
    if not title or not season_name:
        return False

    from thefuzz import fuzz

    title_lower = title.lower().strip()
    season_name_lower = season_name.lower().strip()

    # 策略1: 直接子串包含 (最精确)
    if season_name_lower in title_lower:
        return True

    # 策略2: 移除常见前缀后包含
    # 移除 "第X季"、"Season X"、"S0X" 等前缀
    season_name_cleaned = re.sub(r'^(第\d+季|season\s*\d+|s\d+)\s*', '', season_name_lower, flags=re.IGNORECASE)
    if season_name_cleaned and season_name_cleaned in title_lower:
        return True

    # 策略3: 部分匹配 - 使用 thefuzz 的 partial_ratio
    # 适合 "无限列车篇" 在 "鬼灭之刃 无限列车篇" 中的场景
    partial_similarity = fuzz.partial_ratio(season_name_cleaned or season_name_lower, title_lower)
    if partial_similarity >= 90:  # 部分匹配要求更高的相似度
        return True

    # 策略4: Token 集合匹配 - 检查季度名称的关键词是否都在标题中
    # 例如: "无限列车篇" 的所有字符都在 "鬼灭之刃 无限列车篇" 中
    token_set_similarity = fuzz.token_set_ratio(season_name_cleaned or season_name_lower, title_lower)
    if token_set_similarity >= threshold:
        return True

    # 策略5: 分词匹配 - 检查季度名称的主要词汇是否在标题中
    # 例如: "无限" "列车" "篇" 都在标题中
    # 过滤掉单字和常见词
    common_words = {'第', '季', 'season', 's', '的', '之', '与', '和', 'the', 'and', 'or'}
    words = [w for w in re.split(r'\s+', season_name_cleaned or season_name_lower) if len(w) > 1 and w not in common_words]
    if words:
        # 至少70%的关键词在标题中
        matched_words = sum(1 for word in words if word in title_lower)
        if matched_words / len(words) >= 0.7:
            return True

    return False


class SeasonInfo(models.BaseModel):
    """通用季度信息模型"""
    season_number: int
    name: Optional[str] = None
    episode_count: int = 0
    air_date: Optional[str] = None
    overview: Optional[str] = None
    aliases: Optional[List[str]] = Field(default=[], description="季度别名列表")


class MetadataSearchCandidate(models.BaseModel):
    """元数据搜索候选结果"""
    source: str  # 'tmdb', 'tvdb', 'bangumi', etc.
    id: str  # 源的ID
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    media_type: str  # 'tv' or 'movie'
    overview: Optional[str] = None


class SeasonMapper:
    """季度映射器 - 通过元数据源获取季度名称"""
    
    def __init__(self, metadata_manager, session_factory):
        """
        初始化季度映射器
        
        Args:
            metadata_manager: MetadataSourceManager实例
            session_factory: 数据库会话工厂
        """
        self.metadata_manager = metadata_manager
        self._session_factory = session_factory
        self.logger = logger
    
    async def get_season_name(
        self,
        title: str,
        season_number: int,
        year: Optional[int] = None,
        sources: Optional[List[str]] = None,
        ai_matcher: Optional[Any] = None,
        user: Optional[models.User] = None,
        custom_prompt: Optional[str] = None
    ) -> Optional[str]:
        """
        通过元数据源获取指定季度的名称(通用方法)

        Args:
            title: 剧集标题
            season_number: 季度编号
            year: 年份(可选)
            sources: 要搜索的元数据源列表,None表示使用默认源
            ai_matcher: AI匹配器(可选)
            user: 用户对象
            custom_prompt: 自定义AI提示词(可选)

        Returns:
            季度名称,如果没有找到则返回None
        """
        # 检查缓存
        sources_str = "_".join(sources) if sources else "default"
        cache_key = f"season_name_{title}_{season_number}_{year or 'any'}_{sources_str}"
        async with self._session_factory() as session:
            cached_result = await crud.get_cache(session, cache_key)
            if cached_result:
                self.logger.info(f"季度名称缓存命中: {title} S{season_number:02d}")
                return cached_result.get("season_name")
        
        # 第1步: 搜索所有元数据源
        candidates = await self.search_all_metadata_sources(title, year, "tv", sources, user)
        if not candidates:
            self.logger.info(f"未找到任何元数据: {title}")
            return None
        
        # 第2步: 使用AI选择最佳匹配(如果有AI匹配器)
        selected_candidate = None
        if ai_matcher and len(candidates) > 1:
            try:
                # 转换为字典格式供AI使用
                candidates_dict = [c.model_dump() for c in candidates]
                selected_index = await ai_matcher.select_metadata_result(
                    title,
                    year,
                    candidates_dict,
                    season=season_number,
                    custom_prompt=custom_prompt
                )

                if selected_index is not None and 0 <= selected_index < len(candidates):
                    selected_candidate = candidates[selected_index]
                    self.logger.info(f"AI选择元数据: {selected_candidate.source}:{selected_candidate.id}")
            except Exception as e:
                self.logger.warning(f"AI选择元数据失败: {e}, 使用第一个结果")
        
        # 如果AI未选择或只有一个候选,使用第一个
        if not selected_candidate:
            selected_candidate = candidates[0]
            self.logger.info(f"使用第一个元数据结果: {selected_candidate.source}:{selected_candidate.id}")
        
        # 第3步: 获取季度列表
        seasons = await self.get_seasons_from_source(
            selected_candidate.source,
            selected_candidate.id,
            "tv"
        )
        if not seasons:
            return None
        
        # 第4步: 找到对应季度
        target_season = None
        for season in seasons:
            if season.season_number == season_number:
                target_season = season
                break
        
        if not target_season or not target_season.name:
            return None
        
        # 缓存结果(7天)
        async with self._session_factory() as session:
            await crud.set_cache(
                session,
                cache_key,
                {"season_name": target_season.name, "source": selected_candidate.source},
                ttl_seconds=604800,  # 7天
                provider=selected_candidate.source
            )
        
        self.logger.info(f"获取季度名称成功: {title} S{season_number:02d} → {target_season.name} (来源: {selected_candidate.source})")
        return target_season.name

    async def search_all_metadata_sources(
        self,
        title: str,
        year: Optional[int] = None,
        media_type: str = "tv",
        sources: Optional[List[str]] = None,
        user: Optional[models.User] = None
    ) -> List[MetadataSearchCandidate]:
        """
        搜索所有元数据源,返回候选列表

        Args:
            title: 搜索标题
            year: 年份(可选)
            media_type: 媒体类型 ('tv' or 'movie')
            sources: 要搜索的源列表,None表示搜索所有启用的源
            user: 用户对象

        Returns:
            候选结果列表
        """
        if not user:
            # 创建一个临时用户对象用于API调用
            user = models.User(id=0, username="system", isAdmin=True)

        # 确定要搜索的源
        if sources is None:
            sources = ["tmdb"]  # 默认只搜索TMDB,后续可扩展

        all_candidates = []

        # 并发搜索所有源
        for source_name in sources:
            try:
                source = self.metadata_manager.get_source(source_name)
                if not source:
                    self.logger.warning(f"元数据源 '{source_name}' 未找到")
                    continue

                # 调用源的搜索方法
                search_results = await source.search(title, user, mediaType=media_type)

                if not search_results:
                    self.logger.info(f"{source_name} 搜索无结果: {title}")
                    continue

                # 转换为通用格式
                for result in search_results[:10]:  # 每个源最多取10个结果
                    candidate = MetadataSearchCandidate(
                        source=source_name,
                        id=result.tmdbId or result.id,
                        title=result.title,
                        original_title=getattr(result, 'originalTitle', None),
                        year=result.year,
                        media_type=media_type,
                        overview=getattr(result, 'overview', None)
                    )
                    all_candidates.append(candidate)

                self.logger.info(f"{source_name} 搜索成功: {title}, 找到 {len(search_results)} 个结果")

            except Exception as e:
                self.logger.error(f"{source_name} 搜索失败: {title}, 错误: {e}")
                continue

        return all_candidates

    async def get_seasons_from_source(
        self,
        source: str,
        id: str,
        media_type: str = "tv"
    ) -> List[SeasonInfo]:
        """
        从指定元数据源获取季度信息

        Args:
            source: 元数据源名称 ('tmdb', 'tvdb', etc.)
            id: 源的ID
            media_type: 媒体类型 ('tv' or 'movie')

        Returns:
            季度信息列表
        """
        if media_type != "tv":
            return []

        # 检查缓存
        cache_key = f"{source}_seasons_{id}"
        async with self._session_factory() as session:
            cached_result = await crud.get_cache(session, cache_key)
            if cached_result:
                self.logger.info(f"{source} 季度信息缓存命中: {id}")
                return [SeasonInfo(**s) for s in cached_result]

        # 根据源类型调用不同的API
        try:
            if source == "tmdb":
                seasons = await self._get_tmdb_seasons(id)
            # 后续可扩展其他源
            # elif source == "tvdb":
            #     seasons = await self._get_tvdb_seasons(id)
            else:
                self.logger.warning(f"不支持的元数据源: {source}")
                return []

            # 缓存结果(30天)
            async with self._session_factory() as session:
                await crud.set_cache(
                    session,
                    cache_key,
                    [s.model_dump() for s in seasons],
                    ttl_seconds=2592000,  # 30天
                    provider=source
                )

            self.logger.info(f"获取{source}季度信息成功: {id}, 共{len(seasons)}季")
            return seasons

        except Exception as e:
            self.logger.error(f"获取{source}季度信息失败: {id}, 错误: {e}")
            return []

    async def _get_tmdb_seasons(self, tmdb_id: str) -> List[SeasonInfo]:
        """获取TMDB季度信息(内部方法)"""
        tmdb_source = self.metadata_manager.get_source("tmdb")
        # 直接调用TMDB API获取季度信息
        async with await tmdb_source._create_client() as client:
            response = await client.get(f"/tv/{tmdb_id}")
            response.raise_for_status()
            data = response.json()

            seasons_data = data.get("seasons", [])
            seasons = []

            for season_data in seasons_data:
                # 跳过特别篇(season 0)
                season_number = season_data.get("season_number", 0)
                if season_number == 0:
                    continue

                # 获取季度别名
                season_aliases = await self._get_season_aliases(
                    tmdb_id, season_number, season_data.get("name", "")
                )

                seasons.append(SeasonInfo(
                    season_number=season_number,
                    name=season_data.get("name"),
                    episode_count=season_data.get("episode_count", 0),
                    air_date=season_data.get("air_date"),
                    overview=season_data.get("overview"),
                    aliases=season_aliases
                ))

            return seasons

    async def _get_season_aliases(
        self,
        tmdb_id: str,
        season_number: int,
        season_name: str
    ) -> List[str]:
        """
        获取季度别名，包括常见的中英文表达

        Args:
            tmdb_id: TMDB ID
            season_number: 季度号
            season_name: 季度名称

        Returns:
            季度别名列表
        """
        aliases = set()

        # 添加原始名称
        if season_name:
            aliases.add(season_name)

        # 基于季度号生成常见别名
        season_aliases_map = {
            1: ["第一季", "第1季", "Season 1", "S1", "第一部", "Part 1"],
            2: ["第二季", "第2季", "Season 2", "S2", "第二部", "Part 2", "II", "ⅱ"],
            3: ["第三季", "第3季", "Season 3", "S3", "第三部", "Part 3", "III", "ⅲ"],
            4: ["第四季", "第4季", "Season 4", "S4", "第四部", "Part 4", "IV", "ⅳ"],
            5: ["第五季", "第5季", "Season 5", "S5", "第五部", "Part 5", "V", "ⅴ"],
            6: ["第六季", "第6季", "Season 6", "S6", "第六部", "Part 6", "VI", "ⅵ"],
        }

        # 添加基于季度号的别名
        if season_number in season_aliases_map:
            aliases.update(season_aliases_map[season_number])

        # 基于季度名称生成特殊别名
        if season_name:
            # 刀剑神域特殊处理
            if "刀剑神域" in season_name or "Sword Art Online" in season_name:
                if season_number == 3:
                    aliases.update([
                        "刀剑神域 Alicization篇",
                        "刀剑神域 爱丽丝篇",
                        "Sword Art Online Alicization",
                        "SAO Alicization"
                    ])
                elif season_number == 4:
                    aliases.update([
                        "刀剑神域 Alicization War of Underworld",
                        "刀剑神域 爱丽丝篇 异界战争",
                        "Sword Art Online Alicization War of Underworld",
                        "SAO War of Underworld"
                    ])

            # 进击的巨人特殊处理
            elif "进击的巨人" in season_name or "Attack on Titan" in season_name:
                if season_number == 4:
                    aliases.update([
                        "进击的巨人 最终季",
                        "进击的巨人 The Final Season",
                        "Attack on Titan The Final Season"
                    ])

            # 鬼灭之刃特殊处理
            elif "鬼灭之刃" in season_name or "Demon Slayer" in season_name:
                if season_number == 2:
                    aliases.update([
                        "鬼灭之刃 无限列车篇",
                        "鬼灭之刃 锻刀村篇",
                        "Demon Slayer Entertainment District Arc",
                        "Demon Slayer Mugen Train Arc"
                    ])
                elif season_number == 3:
                    aliases.update([
                        "鬼灭之刃 锻刀村篇",
                        "Demon Slayer Swordsmith Village Arc"
                    ])

        return list(aliases)


async def ai_season_mapping_and_correction(
    search_title: str,
    search_results: list,
    metadata_manager,
    ai_matcher,
    logger,
    similarity_threshold: float = 60.0
) -> list:
    """
    AI季度映射与修正函数 - 优化版本（并行计算）

    Args:
        search_title: 标准化的搜索标题
        search_results: 搜索结果列表
        metadata_manager: 元数据管理器
        ai_matcher: AI匹配器
        logger: 日志记录器
        similarity_threshold: 相似度阈值

    Returns:
        list: 修正结果列表，每个元素包含修正信息
    """
    try:
        # 1. 通过标题搜索TMDB获取季度信息（用于映射修正）
        tmdb_results = await _get_cached_tmdb_search(search_title, metadata_manager, logger)
        if not tmdb_results:
            logger.info(f"○ AI季度映射: 未找到 '{search_title}' 的TMDB信息")
            return []

        # 2. 如果TMDB返回多个结果，使用AI选择最佳TMDB匹配
        if len(tmdb_results) == 1:
            best_tmdb_match = tmdb_results[0]
            logger.info(f"○ AI季度映射: 唯一TMDB匹配: {best_tmdb_match.title} (类型: {best_tmdb_match.type})")
        else:
            # 多个TMDB结果时，AI选择最佳匹配
            try:
                # 转换MetadataDetailsResponse为ProviderSearchInfo格式供AI使用
                provider_results = []
                for r in tmdb_results:
                    provider_results.append(models.ProviderSearchInfo(
                        provider="tmdb",
                        mediaId=r.tmdbId or r.id,
                        title=r.title,
                        type=r.type or "unknown",
                        season=1,  # TMDB搜索结果没有季度信息，默认为1
                        year=r.year,
                        imageUrl=r.imageUrl,
                        episodeCount=None
                    ))

                query_info = {
                    "title": search_title,
                    "season": None,
                    "episode": None,
                    "year": None,
                    "type": None
                }

                selected_index = await ai_matcher.select_best_match(
                    query_info, provider_results, {}
                )

                if selected_index is not None and 0 <= selected_index < len(tmdb_results):
                    best_tmdb_match = tmdb_results[selected_index]
                    logger.info(f"✓ AI季度映射: AI选择TMDB匹配: {best_tmdb_match.title} (类型: {best_tmdb_match.type}, ID: {best_tmdb_match.id})")
                else:
                    logger.error(f"⚠ AI季度映射: AI选择TMDB匹配失败，使用第一个结果")
                    best_tmdb_match = tmdb_results[0]

            except Exception as e:
                logger.error(f"⚠ AI季度映射: TMDB匹配选择失败，使用第一个结果: {e}")
                best_tmdb_match = tmdb_results[0]

        # 3. 获取TMDB季度信息用于后续修正
        # 确保选择的是TV类型，否则无法获取季度信息
        if best_tmdb_match.type != 'tv':
            logger.warning(f"⚠ AI季度映射: 选择的TMDB结果不是TV类型 ({best_tmdb_match.type})，无法获取季度信息")
            # 尝试从TMDB结果中找到TV类型的结果
            tv_result = None
            for result in tmdb_results:
                if result.type == 'tv':
                    tv_result = result
                    logger.info(f"✓ AI季度映射: 找到TV类型结果: {tv_result.title} (ID: {tv_result.id})")
                    break

            if not tv_result:
                logger.error(f"⚠ AI季度映射: TMDB结果中没有TV类型，无法获取季度信息")
                return []

            best_tmdb_match = tv_result

        try:
            seasons_info = await metadata_manager.get_seasons("tmdb", best_tmdb_match.id)
        except Exception as e:
            logger.error(f"获取tmdb季度信息失败: {best_tmdb_match.id}, 错误: {e}")
            return []

        if not seasons_info or len(seasons_info) <= 1:
            logger.info(f"○ AI季度映射: '{search_title}' 只有1个季度或无季度信息，跳过")
            return []

        logger.info(f"✓ AI季度映射: 获取到 '{search_title}' 的TMDB季度信息，共 {len(seasons_info)} 个季度")
        for season in seasons_info:
            season_name = season.name or f"第{season.season_number}季"
            logger.info(f"  - 第{season.season_number}季: {season_name}")
        # 4. 对所有搜索结果进行AI季度修正（不是选择最佳匹配）
        tv_results = [item for item in search_results if item.type == 'tv_series']
        if not tv_results:
            logger.info(f"○ AI季度映射: 没有TV结果需要修正")
            return []

        logger.info(f"○ 开始AI季度修正，检查 {len(tv_results)} 个TV结果...")

        # 5. 并行计算每个结果的季度修正
        async def calculate_best_season_for_item(item):
            """并行计算单个项目的最佳季度"""
            item_title = item.title
            best_season = item.season or 1  # 保持原有季度或默认第1季
            best_confidence = 0.0
            best_season_name = ""

            # 首先检查标题中是否包含明确的季度关键词
            title_lower = item_title.lower()
            detected_season = None

            # 使用公共季度关键词配置
            season_keywords = SEASON_KEYWORDS

            # 检查标题中的季度关键词
            for season_num, keywords in season_keywords.items():
                for keyword in keywords:
                    if keyword in title_lower:
                        detected_season = season_num
                        break
                if detected_season:
                    break

            # 如果检测到明确的季度关键词，优先使用
            if detected_season:
                # 检查TMDB是否有对应的季度
                for season in seasons_info:
                    if season.season_number == detected_season:
                        season_name = season.name or f"第{season.season_number}季"
                        # 计算相似度作为验证
                        similarity = await asyncio.to_thread(
                            calculate_similarity,
                            item_title.lower(),
                            season_name.lower()
                        )
                        logger.debug(f"  ○ '{item_title}' 检测到季度关键词 S{detected_season}，匹配TMDB: {season_name} (相似度: {similarity:.1f}%)")

                        # 如果相似度达到阈值，使用检测到的季度
                        if similarity >= similarity_threshold:
                            best_season = detected_season
                            best_confidence = similarity
                            best_season_name = season_name
                            break
                else:
                    # TMDB没有对应季度，回退到相似度匹配
                    logger.debug(f"  ○ '{item_title}' 检测到季度关键词 S{detected_season}，但TMDB无此季度，回退到相似度匹配")

            # 如果没有检测到季度关键词或相似度不足，使用AI计算相似度
            if best_confidence < similarity_threshold:
                # 使用AI计算与所有TMDB季度的相似度
                try:
                    # 构建AI比较的选项，包含别名
                    season_options = []
                    for season in seasons_info:
                        season_name = season.name or f"第{season.season_number}季"
                        season_options.append({
                            "season_number": season.season_number,
                            "name": season_name,
                            "aliases": season.aliases or []
                        })

                    # 使用AI计算最佳季度匹配
                    ai_selected_season = await ai_matcher.select_best_season_for_title(
                        item_title, season_options
                    )

                    if ai_selected_season is not None:
                        best_season = ai_selected_season
                        best_confidence = 95.0  # AI选择给予高置信度
                        # 找到对应的季度名称
                        for season in seasons_info:
                            if season.season_number == ai_selected_season:
                                best_season_name = season.name or f"第{season.season_number}季"
                                break
                        logger.debug(f"  ○ '{item_title}' AI选择季度: S{best_season} ({best_season_name})")
                    else:
                        logger.debug(f"  ○ '{item_title}' AI未能确定季度，保持原季度 S{item.season or '?'}")

                except Exception as e:
                    logger.debug(f"  ○ '{item_title}' AI季度计算失败: {e}，保持原季度")

            # 调试：显示最终选择
            if best_confidence >= similarity_threshold:
                logger.debug(f"  ○ '{item_title}' 最终选择: S{best_season} ({best_season_name}) (置信度: {best_confidence:.1f}%)")

            # 返回修正信息（只有需要修正的）
            if best_confidence >= similarity_threshold and item.season != best_season:
                return {
                    'item': item,
                    'original_season': item.season,
                    'corrected_season': best_season,
                    'confidence': best_confidence,
                    'tmdb_season_name': best_season_name
                }
            elif best_confidence >= similarity_threshold:
                logger.debug(f"  ○ 无需修正: '{item_title}' 已是正确季度 S{best_season} (置信度: {best_confidence:.1f}%)")
                return None
            else:
                logger.debug(f"  ○ 相似度不足: '{item_title}' 保持原季度 S{item.season or '?'} (最高相似度: {best_confidence:.1f}% < {similarity_threshold}%)")
                return None

        # 并行处理所有TV结果
        tasks = [calculate_best_season_for_item(item) for item in tv_results]
        results = await asyncio.gather(*tasks)

        # 过滤有效的修正结果
        corrected_results = [result for result in results if result is not None]

        # 记录修正结果
        for correction in corrected_results:
            item = correction['item']
            original_season = correction['original_season']
            corrected_season = correction['corrected_season']
            confidence = correction['confidence']
            tmdb_season_name = correction.get('tmdb_season_name', '')
            logger.info(f"  ✓ AI修正: '{item.title}' S{original_season or '?'} → S{corrected_season} ({tmdb_season_name}) (置信度: {confidence:.1f}%)")

        logger.info(f"✓ AI季度映射完成: 修正了 {len(corrected_results)} 个结果的季度信息")
        return corrected_results

    except Exception as e:
        logger.warning(f"AI季度映射失败: {e}")
        return []


async def ai_type_and_season_mapping_and_correction(
    search_title: str,
    search_results: list,
    metadata_manager,
    ai_matcher,
    logger,
    similarity_threshold: float = 60.0
) -> dict:
    """
    统一的AI类型和季度映射与修正函数

    适用于所有六个流程：
    1. 主页搜索
    2. 全自动导入
    3. Webhook处理
    4. 后备搜索
    5. 后备匹配
    6. 外部控制搜索/导入

    Args:
        search_title: 标准化的搜索标题
        search_results: 搜索结果列表
        metadata_manager: 元数据管理器
        ai_matcher: AI匹配器
        logger: 日志记录器
        similarity_threshold: 相似度阈值

    Returns:
        dict: 包含类型修正和季度修正的结果
        {
            'type_corrections': list,  # 类型修正结果
            'season_corrections': list,  # 季度修正结果
            'total_corrections': int,   # 总修正数
            'corrected_results': list   # 修正后的完整结果列表
        }
    """
    try:
        logger.info(f"○ 开始统一AI映射修正: '{search_title}' ({len(search_results)} 个结果)")

        # 初始化结果
        type_corrections = []
        season_corrections = []
        corrected_results = []

        # 1. 类型修正（将所有结果修正为正确的媒体类型）
        logger.info(f"○ 开始类型修正...")
        for item in search_results:
            original_type = item.type
            corrected_type = original_type

            # 使用AI判断正确的类型（这里可以扩展AI类型判断逻辑）
            # 目前暂时保持原类型，后续可以添加AI类型判断
            if original_type != corrected_type:
                type_corrections.append({
                    'item': item,
                    'original_type': original_type,
                    'corrected_type': corrected_type
                })
                item.type = corrected_type
                logger.info(f"  ✓ 类型修正: '{item.title}' {original_type} → {corrected_type}")

        logger.info(f"✓ 类型修正完成: 修正了 {len(type_corrections)} 个结果的类型信息")

        # 2. 季度修正（只对电视剧进行）
        tv_results = [item for item in search_results if item.type == 'tv_series']
        if tv_results:
            season_corrections = await ai_season_mapping_and_correction(
                search_title=search_title,
                search_results=search_results,
                metadata_manager=metadata_manager,
                ai_matcher=ai_matcher,
                logger=logger,
                similarity_threshold=similarity_threshold
            )

            # 应用季度修正到原始搜索结果
            for correction in season_corrections:
                item = correction['item']
                item.season = correction['corrected_season']
                logger.info(f"  ✓ 季度修正应用: '{item.title}' → S{item.season}")

        # 3. 构建修正后的结果列表
        corrected_results = search_results.copy()

        total_corrections = len(type_corrections) + len(season_corrections)
        logger.info(f"✓ 统一AI映射修正完成: 类型修正 {len(type_corrections)} 个, 季度修正 {len(season_corrections)} 个, 总计 {total_corrections} 个")

        return {
            'type_corrections': type_corrections,
            'season_corrections': season_corrections,
            'total_corrections': total_corrections,
            'corrected_results': corrected_results
        }

    except Exception as e:
        logger.warning(f"统一AI映射修正失败: {e}")
        return {
            'type_corrections': [],
            'season_corrections': [],
            'total_corrections': 0,
            'corrected_results': search_results
        }


async def _get_cached_tmdb_search(search_title: str, metadata_manager, logger) -> List[models.MetadataDetailsResponse]:
    """
    获取TMDB搜索结果，带6小时缓存

    Args:
        search_title: 搜索标题
        metadata_manager: 元数据管理器
        logger: 日志记录器

    Returns:
        List[models.MetadataDetailsResponse]: TMDB搜索结果
    """

    # 生成缓存键
    cache_key = f"tmdb_search_{hashlib.md5(search_title.encode('utf-8')).hexdigest()}"

    # 检查缓存
    async with metadata_manager._session_factory() as session:
        cached_result = await crud.get_cache(session, cache_key)
        if cached_result:
            logger.info(f"TMDB搜索缓存命中: {search_title}")
            return [models.MetadataDetailsResponse(**r) for r in cached_result]

    # 缓存未命中，执行搜索
    logger.debug(f"TMDB搜索缓存未命中，执行搜索: {search_title}")
    try:
        tmdb_results = await metadata_manager.search("tmdb", search_title, None, mediaType='multi')

        # 缓存结果（6小时 = 21600秒）
        async with metadata_manager._session_factory() as session:
            await crud.set_cache(
                session,
                cache_key,
                [r.model_dump() for r in tmdb_results],
                ttl_seconds=21600,  # 6小时
                provider="tmdb"
            )
            logger.info(f"TMDB搜索结果已缓存: {search_title} (6小时)")

        return tmdb_results
    except Exception as e:
        logger.error(f"TMDB搜索失败: {search_title}, 错误: {e}")
        return []




