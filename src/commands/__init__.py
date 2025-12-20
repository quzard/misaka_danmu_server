"""
指令系统模块
提供命令的自动加载和注册功能
"""
import os
import importlib
import inspect
import logging
from typing import Dict, Optional, Tuple, List, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession

from .base import CommandHandler, parse_command

if TYPE_CHECKING:
    from ..dandan_api import DandanSearchAnimeResponse

logger = logging.getLogger(__name__)

# 全局指令注册表
_COMMAND_HANDLERS: Dict[str, CommandHandler] = {}


def _get_commands_path():
    """获取 commands 目录的绝对路径"""
    return os.path.dirname(os.path.abspath(__file__))


def _load_commands():
    """
    自动加载所有命令处理器
    扫描 commands 目录下的所有 Python 模块，查找 CommandHandler 子类并注册
    """
    global _COMMAND_HANDLERS
    
    if _COMMAND_HANDLERS:
        # 已加载，避免重复
        return
    
    commands_path = _get_commands_path()
    
    # 遍历 commands 目录中的所有 .py 文件
    for filename in os.listdir(commands_path):
        # 跳过特殊文件
        if filename.startswith('_') or filename == 'base.py' or not filename.endswith('.py'):
            continue
        
        module_name = filename[:-3]  # 去掉 .py 后缀
        
        try:
            # 动态导入模块
            module = importlib.import_module(f'.{module_name}', package='src.commands')
            
            # 查找模块中的 CommandHandler 子类
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # 检查是否是 CommandHandler 的子类（但不是 CommandHandler 本身）
                if issubclass(obj, CommandHandler) and obj is not CommandHandler:
                    # 实例化并注册
                    handler = obj()
                    _COMMAND_HANDLERS[handler.name] = handler
                    logger.info(f"已加载命令处理器: @{handler.name} (来自模块 {module_name})")
                    
        except Exception as e:
            logger.error(f"加载命令模块 {module_name} 失败: {e}", exc_info=True)
    
    logger.info(f"命令系统初始化完成，共加载 {len(_COMMAND_HANDLERS)} 个命令")


def get_all_handlers() -> Dict[str, CommandHandler]:
    """
    获取所有已注册的命令处理器
    
    Returns:
        命令名称到处理器的映射字典
    """
    if not _COMMAND_HANDLERS:
        _load_commands()
    
    return _COMMAND_HANDLERS


def get_handler(command_name: str) -> Optional[CommandHandler]:
    """
    获取指定名称的命令处理器
    
    Args:
        command_name: 命令名称（大写）
        
    Returns:
        命令处理器实例，如果不存在则返回 None
    """
    handlers = get_all_handlers()
    return handlers.get(command_name.upper())


async def handle_command(search_term: str, token: str, session: AsyncSession,
                        config_manager, cache_manager, **kwargs) -> Optional["DandanSearchAnimeResponse"]:
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
    from ..dandan_api import DandanSearchAnimeResponse, DandanSearchAnimeItem
    
    # 解析指令
    parsed = parse_command(search_term)
    if not parsed:
        return None
    
    command_name, args = parsed
    
    # 确保命令已加载
    handlers = get_all_handlers()
    handler = handlers.get(command_name)
    
    # 获取自定义域名和图片URL
    custom_domain = await config_manager.get("customApiDomain", "")
    image_url = f"{custom_domain}/static/logo.png" if custom_domain else "/static/logo.png"
    
    if not handler:
        # 未知指令
        logger.warning(f"未知指令: @{command_name}, token={token}")
        
        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999998,
                bangumiId="999999998",
                animeTitle=f"✗ 未知指令: @{command_name}",
                type="other",
                typeDescription=f"该指令不存在\n\n💡 提示：输入 @ 或 @HELP 查看所有可用指令",
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
                typeDescription=f"你已在 {handler.cooldown_seconds} 秒内触发过 @{command_name} 指令，还有 {remaining} 秒才能再次使用",
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


# 导出公共接口
__all__ = [
    'CommandHandler',
    'parse_command',
    'get_all_handlers',
    'get_handler',
    'handle_command',
]

