"""元数据处理模块"""
import logging
import json
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models
from ..metadata_manager import MetadataSourceManager
from .utils import is_chinese_title

logger = logging.getLogger(__name__)


async def reverse_lookup_tmdb_chinese_title(
    metadata_manager: MetadataSourceManager,
    user: models.User,
    source_type: str,
    source_id: str,
    tmdb_id: Optional[str],
    imdb_id: Optional[str],
    tvdb_id: Optional[str],
    douban_id: Optional[str],
    bangumi_id: Optional[str]
) -> Optional[str]:
    """
    通过其他ID反查TMDB获取中文标题

    Args:
        metadata_manager: 元数据管理器
        user: 用户对象
        source_type: 原始搜索类型 (tvdb, imdb, douban, bangumi)
        source_id: 原始搜索ID
        tmdb_id: 已知的TMDB ID（如果有）
        imdb_id: IMDB ID
        tvdb_id: TVDB ID
        douban_id: 豆瓣ID
        bangumi_id: Bangumi ID

    Returns:
        中文标题（如果找到）
    """
    try:
        # 如果已经有TMDB ID，直接用它获取中文标题
        if tmdb_id:
            logger.info(f"使用已知TMDB ID {tmdb_id} 获取中文标题...")
            tmdb_details = await metadata_manager.get_details(
                provider='tmdb', item_id=tmdb_id, user=user, mediaType='tv'
            )
            if not tmdb_details:
                # 尝试movie类型
                tmdb_details = await metadata_manager.get_details(
                    provider='tmdb', item_id=tmdb_id, user=user, mediaType='movie'
                )

            if tmdb_details and tmdb_details.title and is_chinese_title(tmdb_details.title):
                return tmdb_details.title

        # 如果没有TMDB ID或TMDB查询失败，尝试通过其他ID反查
        external_ids = {}
        if imdb_id:
            external_ids['imdb_id'] = imdb_id
        if tvdb_id:
            external_ids['tvdb_id'] = tvdb_id
        if douban_id:
            external_ids['douban_id'] = douban_id
        if bangumi_id:
            external_ids['bangumi_id'] = bangumi_id

        if external_ids:
            logger.info(f"尝试通过外部ID反查TMDB: {external_ids}")
            # 尝试通过TMDB的find API查找
            tmdb_id_from_external = await find_tmdb_by_external_ids(metadata_manager, user, external_ids)
            if tmdb_id_from_external:
                logger.info(f"通过外部ID找到TMDB ID: {tmdb_id_from_external}")
                # 使用找到的TMDB ID获取中文标题
                tmdb_details = await metadata_manager.get_details(
                    provider='tmdb', item_id=tmdb_id_from_external, user=user, mediaType='tv'
                )
                if not tmdb_details:
                    tmdb_details = await metadata_manager.get_details(
                        provider='tmdb', item_id=tmdb_id_from_external, user=user, mediaType='movie'
                    )

                if tmdb_details and tmdb_details.title and is_chinese_title(tmdb_details.title):
                    return tmdb_details.title

        logger.info(f"未能通过 {source_type} ID {source_id} 反查到中文标题")
        return None

    except Exception as e:
        logger.warning(f"TMDB反查失败: {e}")
        return None


async def is_tmdb_reverse_lookup_enabled(session: AsyncSession, source_type: str) -> bool:
    """
    检查TMDB反查功能是否启用，以及指定的源类型是否在启用列表中

    Args:
        session: 数据库会话
        source_type: 源类型 (imdb, tvdb, douban, bangumi)

    Returns:
        是否启用TMDB反查
    """
    try:
        # 检查总开关
        enabled_value = await crud.get_config_value(session, "tmdbReverseLookupEnabled", "false")
        if enabled_value.lower() != "true":
            return False

        # 检查源类型是否在启用列表中
        sources_json = await crud.get_config_value(session, "tmdbReverseLookupSources", '["imdb", "tvdb", "douban", "bangumi"]')
        try:
            enabled_sources = json.loads(sources_json)
        except:
            enabled_sources = ["imdb", "tvdb", "douban", "bangumi"]  # 默认值

        return source_type in enabled_sources

    except Exception as e:
        logger.warning(f"检查TMDB反查配置失败: {e}")
        return False


async def find_tmdb_by_external_ids(
    metadata_manager: MetadataSourceManager,
    user: models.User,
    external_ids: Dict[str, str]
) -> Optional[str]:
    """
    通过外部ID查找TMDB ID

    Args:
        metadata_manager: 元数据管理器
        user: 用户对象
        external_ids: 外部ID字典，如 {'imdb_id': 'tt1234567', 'tvdb_id': '12345'}

    Returns:
        TMDB ID（如果找到）
    """
    try:
        # 目前简化实现：通过搜索来查找
        # TODO: 实现真正的TMDB find API调用

        # 如果有IMDB ID，尝试通过IMDB搜索然后查看结果中的TMDB ID
        if 'imdb_id' in external_ids:
            imdb_id = external_ids['imdb_id']
            logger.info(f"尝试通过IMDB ID {imdb_id} 查找TMDB...")

            # 通过IMDB搜索
            imdb_results = await metadata_manager.search('imdb', imdb_id, user)
            for result in imdb_results:
                if hasattr(result, 'tmdbId') and result.tmdbId:
                    logger.info(f"通过IMDB找到TMDB ID: {result.tmdbId}")
                    return result.tmdbId

        # 如果有TVDB ID，类似处理
        if 'tvdb_id' in external_ids:
            tvdb_id = external_ids['tvdb_id']
            logger.info(f"尝试通过TVDB ID {tvdb_id} 查找TMDB...")

            # 通过TVDB搜索
            tvdb_results = await metadata_manager.search('tvdb', tvdb_id, user)
            for result in tvdb_results:
                if hasattr(result, 'tmdbId') and result.tmdbId:
                    logger.info(f"通过TVDB找到TMDB ID: {result.tmdbId}")
                    return result.tmdbId

        # 如果有Douban ID，类似处理
        if 'douban_id' in external_ids:
            douban_id = external_ids['douban_id']
            logger.info(f"尝试通过Douban ID {douban_id} 查找TMDB...")

            # 通过Douban搜索
            douban_results = await metadata_manager.search('douban', douban_id, user)
            for result in douban_results:
                if hasattr(result, 'tmdbId') and result.tmdbId:
                    logger.info(f"通过Douban找到TMDB ID: {result.tmdbId}")
                    return result.tmdbId

        # 如果有Bangumi ID，类似处理
        if 'bangumi_id' in external_ids:
            bangumi_id = external_ids['bangumi_id']
            logger.info(f"尝试通过Bangumi ID {bangumi_id} 查找TMDB...")

            # 通过Bangumi搜索
            bangumi_results = await metadata_manager.search('bangumi', bangumi_id, user)
            for result in bangumi_results:
                if hasattr(result, 'tmdbId') and result.tmdbId:
                    logger.info(f"通过Bangumi找到TMDB ID: {result.tmdbId}")
                    return result.tmdbId

        return None

    except Exception as e:
        logger.warning(f"通过外部ID查找TMDB失败: {e}")
        return None

