"""季度映射模块 - 通过元数据源获取季度名称"""
import logging
from typing import Optional, List, Any
from sqlalchemy.ext.asyncio import AsyncSession

from . import models, crud

logger = logging.getLogger(__name__)


class SeasonInfo(models.BaseModel):
    """通用季度信息模型"""
    season_number: int
    name: Optional[str] = None
    episode_count: int = 0
    air_date: Optional[str] = None
    overview: Optional[str] = None


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
            user = models.User(userId=0, username="system", isAdmin=True)

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

                seasons.append(SeasonInfo(
                    season_number=season_number,
                    name=season_data.get("name"),
                    episode_count=season_data.get("episode_count", 0),
                    air_date=season_data.get("air_date"),
                    overview=season_data.get("overview")
                ))

            return seasons

