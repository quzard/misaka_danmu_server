"""
名称转换模块 - 将非中文标题转换为中文标题

用于搜索时自动将日文、英文等非中文标题转换为中文，以提高弹幕源搜索的匹配率。
"""

import asyncio
import json
import logging
from typing import Optional, Tuple, List

from .tasks.utils import is_chinese_title
from .config_manager import ConfigManager
from .metadata_manager import MetadataSourceManager
from .ai.ai_matcher_manager import AIMatcherManager
from . import models

logger = logging.getLogger(__name__)


async def convert_to_chinese_title(
    title: str,
    config_manager: ConfigManager,
    metadata_manager: MetadataSourceManager,
    ai_matcher_manager: Optional[AIMatcherManager],
    user: models.User
) -> Tuple[str, bool]:
    """
    将非中文标题转换为中文标题
    
    Args:
        title: 原始标题
        config_manager: 配置管理器
        metadata_manager: 元数据管理器
        ai_matcher_manager: AI匹配器管理器（可选）
        user: 当前用户
        
    Returns:
        Tuple[str, bool]: (转换后的标题, 是否成功转换)
    """
    # 检查是否启用名称转换
    name_conversion_enabled_str = await config_manager.get("nameConversionEnabled", "false")
    logger.info(f"名称转换配置检查: nameConversionEnabled='{name_conversion_enabled_str}'")
    if name_conversion_enabled_str.lower() != "true":
        logger.info(f"○ 名称转换功能未启用，跳过: '{title}'")
        return title, False
    
    # 如果已经是中文标题，无需转换
    if is_chinese_title(title):
        return title, False
    
    logger.info(f"检测到非中文标题: '{title}'，尝试名称转换...")
    
    try:
        # 1. 尝试通过元数据源转换
        converted = await _convert_via_metadata_sources(
            title, config_manager, metadata_manager, user
        )
        if converted:
            logger.info(f"✓ 名称转换成功 ({converted[0]}): '{title}' → '{converted[1]}'")
            return converted[1], True
        
        # 2. 元数据源失败，尝试AI兜底
        ai_converted = await _convert_via_ai(
            title, config_manager, ai_matcher_manager
        )
        if ai_converted:
            logger.info(f"✓ AI名称转换成功: '{title}' → '{ai_converted}'")
            return ai_converted, True
        
        logger.info(f"○ 名称转换未找到中文名: '{title}'")
        return title, False
        
    except Exception as e:
        logger.warning(f"名称转换过程出错: {e}")
        return title, False


async def _convert_via_metadata_sources(
    title: str,
    config_manager: ConfigManager,
    metadata_manager: MetadataSourceManager,
    user: models.User
) -> Optional[Tuple[str, str]]:
    """
    通过元数据源转换标题
    
    Returns:
        Optional[Tuple[str, str]]: (源名称, 中文标题) 或 None
    """
    # 获取元数据源优先级配置
    priority_config_str = await config_manager.get(
        "nameConversionSourcePriority",
        '[{"key":"bangumi","enabled":true},{"key":"tmdb","enabled":true},{"key":"tvdb","enabled":true},{"key":"douban","enabled":true},{"key":"imdb","enabled":true}]'
    )
    try:
        priority_config = json.loads(priority_config_str)
    except json.JSONDecodeError:
        priority_config = [{"key": "bangumi", "enabled": True}, {"key": "tmdb", "enabled": True}]
    
    # 按优先级顺序获取启用的元数据源
    enabled_sources = [item["key"] for item in priority_config if item.get("enabled", True)]
    
    if not enabled_sources:
        return None
    
    # 定义单个源的搜索函数
    async def search_source(source_name: str) -> Optional[Tuple[str, str]]:
        try:
            media_type = 'multi' if source_name == 'tmdb' else None
            results = await metadata_manager.search(source_name, title, user, mediaType=media_type)
            if results:
                for result in results:
                    # 检查标题是否有中文
                    if result.title and is_chinese_title(result.title):
                        return (source_name, result.title)
                    # 检查别名
                    if result.aliases:
                        for alias in result.aliases:
                            if is_chinese_title(alias):
                                return (source_name, alias)

                    # 🔧 如果搜索结果标题不是中文，尝试获取详情以获取中文别名
                    # 这对 TMDB 特别重要，因为搜索结果可能返回原始语言标题
                    if result.id and source_name in ['tmdb', 'tvdb', 'imdb']:
                        try:
                            # 确定媒体类型用于 get_details
                            detail_media_type = result.type if hasattr(result, 'type') and result.type else 'tv'
                            details = await metadata_manager.get_details(
                                source_name, result.id, user, mediaType=detail_media_type
                            )
                            if details:
                                # 检查详情中的标题
                                if details.title and is_chinese_title(details.title):
                                    return (source_name, details.title)
                                # 检查中文别名列表
                                if hasattr(details, 'aliasesCn') and details.aliasesCn:
                                    for alias in details.aliasesCn:
                                        if is_chinese_title(alias):
                                            return (source_name, alias)
                                # 检查通用别名
                                if details.aliases:
                                    for alias in details.aliases:
                                        if is_chinese_title(alias):
                                            return (source_name, alias)
                        except Exception as detail_err:
                            logger.debug(f"名称转换 - {source_name} 获取详情失败: {detail_err}")
            return None
        except Exception as e:
            logger.debug(f"名称转换 - {source_name} 查询失败: {e}")
            return None
    
    # 并行执行所有查询
    tasks = [search_source(source) for source in enabled_sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 按优先级顺序检查结果
    for result in results:
        if result and not isinstance(result, Exception):
            return result

    return None


async def _convert_via_ai(
    title: str,
    config_manager: ConfigManager,
    ai_matcher_manager: Optional[AIMatcherManager]
) -> Optional[str]:
    """
    通过AI转换标题（兜底方案）

    Returns:
        Optional[str]: 中文标题 或 None
    """
    # 检查是否启用AI名称转换
    ai_enabled_str = await config_manager.get("aiNameConversionEnabled", "false")
    if ai_enabled_str.lower() != "true":
        return None

    if not ai_matcher_manager:
        return None

    logger.info("元数据源名称转换失败，尝试AI兜底...")

    try:
        ai_matcher = await ai_matcher_manager.get_matcher()
        if not ai_matcher:
            return None

        # 获取AI名称转换提示词
        ai_prompt = await config_manager.get("aiNameConversionPrompt", "")
        if not ai_prompt:
            ai_prompt = "请将以下非中文标题翻译为其官方中文名称。如果是日本动漫/电视剧，请提供其官方中文译名。只返回中文名称，不要其他内容。"

        full_prompt = f"{ai_prompt}\n\n标题: {title}"
        ai_response = await ai_matcher.query(full_prompt)

        if ai_response and is_chinese_title(ai_response):
            return ai_response.strip()

        return None

    except Exception as e:
        logger.warning(f"AI名称转换失败: {e}")
        return None

