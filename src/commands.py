"""
指令系统模块
支持以@开头的搜索词作为指令，提供通用的指令处理框架
"""
import time
import logging
from typing import Optional, Tuple, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from .dandan_api import (
    DandanSearchAnimeResponse, 
    DandanSearchAnimeItem,
    _get_db_cache,
    _set_db_cache
)
from . import crud

logger = logging.getLogger(__name__)


def parse_command(search_term: str) -> Optional[Tuple[str, List[str]]]:
    """
    解析指令
    
    Args:
        search_term: 搜索词
        
    Returns:
        (指令名称, 参数列表) 或 None（不是指令）
    """
    if not search_term.startswith('@'):
        return None
    
    parts = search_term[1:].strip().split()
    command_name = parts[0].upper() if parts else ""
    args = parts[1:] if len(parts) > 1 else []
    
    return (command_name, args) if command_name else None


class CommandHandler:
    """指令处理器基类"""
    
    def __init__(self, name: str, description: str, cooldown_seconds: int = 0):
        """
        初始化指令处理器
        
        Args:
            name: 指令名称
            description: 指令描述
            cooldown_seconds: 冷却时间（秒），0表示无冷却
        """
        self.name = name
        self.description = description
        self.cooldown_seconds = cooldown_seconds
    
    async def can_execute(self, token: str, session: AsyncSession) -> Tuple[bool, Optional[int]]:
        """
        检查是否可以执行（频率限制）
        
        Args:
            token: 用户token
            session: 数据库会话
            
        Returns:
            (是否可执行, 剩余冷却秒数)
        """
        if self.cooldown_seconds == 0:
            return (True, None)
        
        cache_key = f"{token}_{self.name}"
        last_exec_time = await _get_db_cache(session, "command_cooldown_", cache_key)
        
        if last_exec_time:
            elapsed = time.time() - last_exec_time
            if elapsed < self.cooldown_seconds:
                remaining = int(self.cooldown_seconds - elapsed)
                return (False, remaining)
        
        return (True, None)
    
    async def execute(self, token: str, args: List[str], session: AsyncSession, 
                     config_manager, **kwargs) -> DandanSearchAnimeResponse:
        """
        执行指令，子类需要实现
        
        Args:
            token: 用户token
            args: 指令参数
            session: 数据库会话
            config_manager: 配置管理器
            **kwargs: 其他依赖
            
        Returns:
            DandanSearchAnimeResponse
        """
        raise NotImplementedError
    
    async def record_execution(self, token: str, session: AsyncSession):
        """
        记录执行时间
        
        Args:
            token: 用户token
            session: 数据库会话
        """
        if self.cooldown_seconds > 0:
            cache_key = f"{token}_{self.name}"
            await _set_db_cache(session, "command_cooldown_", cache_key, time.time(), self.cooldown_seconds)


class ClearCacheCommand(CommandHandler):
    """清理缓存指令"""
    
    def __init__(self):
        super().__init__(
            name="QLHC",
            description="清理缓存",
            cooldown_seconds=30
        )
    
    async def execute(self, token: str, args: List[str], session: AsyncSession,
                     config_manager, **kwargs) -> DandanSearchAnimeResponse:
        """执行清理缓存"""
        # 获取自定义域名
        custom_domain = await config_manager.get("customApiDomain", "")
        image_url = f"{custom_domain}/static/logo.png" if custom_domain else "/static/logo.png"
        
        try:
            # 获取cache_manager
            cache_manager = kwargs.get('cache_manager')
            
            # 清理内存缓存
            config_manager.clear_cache()
            
            # 清理数据库缓存
            await crud.clear_all_cache(session)
            
            # 记录执行时间
            await self.record_execution(token, session)
            
            logger.info(f"指令 @{self.name} 执行成功，token={token}")
            
            return DandanSearchAnimeResponse(animes=[
                DandanSearchAnimeItem(
                    animeId=999999998,  # 指令响应专用ID
                    bangumiId="999999998",
                    animeTitle="✓ 缓存清理成功",
                    type="other",
                    typeDescription="指令执行成功",
                    imageUrl=image_url,
                    startDate="2025-01-01T00:00:00+08:00",
                    year=2025,
                    episodeCount=0,
                    rating=0.0,
                    isFavorited=False
                )
            ])
        except Exception as e:
            logger.error(f"指令 @{self.name} 执行失败: {e}", exc_info=True)
            return DandanSearchAnimeResponse(animes=[
                DandanSearchAnimeItem(
                    animeId=999999998,
                    bangumiId="999999998",
                    animeTitle=f"✗ 缓存清理失败: {str(e)}",
                    type="other",
                    typeDescription="指令执行失败",
                    imageUrl=image_url,
                    startDate="2025-01-01T00:00:00+08:00",
                    year=2025,
                    episodeCount=0,
                    rating=0.0,
                    isFavorited=False
                )
            ])


# 全局指令注册表
COMMAND_HANDLERS: Dict[str, CommandHandler] = {
    "QLHC": ClearCacheCommand(),
    # 未来可以添加更多指令：
    # "HELP": HelpCommand(),
    # "STATUS": StatusCommand(),
}


async def handle_command(search_term: str, token: str, session: AsyncSession,
                        config_manager, cache_manager, **kwargs) -> Optional[DandanSearchAnimeResponse]:
    """
    处理指令

    Args:
        search_term: 搜索词
        token: 用户token
        session: 数据库会话
        config_manager: 配置管理器
        cache_manager: 缓存管理器
        **kwargs: 其他依赖

    Returns:
        指令响应 或 None（不是指令）
    """
    parsed = parse_command(search_term)
    if not parsed:
        return None

    command_name, args = parsed
    handler = COMMAND_HANDLERS.get(command_name)

    # 获取自定义域名
    custom_domain = await config_manager.get("customApiDomain", "")
    image_url = f"{custom_domain}/static/logo.png" if custom_domain else "/static/logo.png"

    if not handler:
        # 未知指令
        available_commands = ', '.join(['@' + k for k in COMMAND_HANDLERS.keys()])
        logger.warning(f"未知指令: @{command_name}, token={token}")

        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999998,
                bangumiId="999999998",
                animeTitle=f"✗ 未知指令: @{command_name}",
                type="other",
                typeDescription=f"可用指令: {available_commands}",
                imageUrl=image_url,
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=0,
                rating=0.0,
                isFavorited=False
            )
        ])

    # 检查频率限制
    can_exec, remaining = await handler.can_execute(token, session)
    if not can_exec:
        logger.info(f"指令 @{command_name} 冷却中, token={token}, 剩余{remaining}秒")

        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999998,
                bangumiId="999999998",
                animeTitle=f"⏱ 指令冷却中",
                type="other",
                typeDescription=f"你已在30秒内触发过 @{command_name} 指令，还有 {remaining} 秒才能再次使用",
                imageUrl=image_url,
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=0,
                rating=0.0,
                isFavorited=False
            )
        ])

    # 执行指令
    return await handler.execute(token, args, session, config_manager, cache_manager=cache_manager, **kwargs)

