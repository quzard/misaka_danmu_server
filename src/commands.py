"""
指令系统模块（向后兼容桥接）

此文件保持向后兼容，实际功能已迁移到 commands/ 目录下的模块化系统。
新的模块化系统支持：
- 自动加载命令处理器
- 每个命令独立模块
- 通用的响应构建方法
- 更好的可扩展性

使用方式保持不变：
    from .commands import handle_command, parse_command
"""
import logging
from typing import TYPE_CHECKING

# 从新的模块化系统导入所有公共接口
from .commands import (
    CommandHandler,
    parse_command,
    get_all_handlers,
    get_handler,
    handle_command,
)

if TYPE_CHECKING:
    from .dandan_api import DandanSearchAnimeResponse

logger = logging.getLogger(__name__)


# 为了保持向后兼容，保留对 COMMAND_HANDLERS 的访问
# 实际上是对新系统的 get_all_handlers() 的包装
class _CommandHandlersProxy:
    """命令处理器字典代理，保持向后兼容"""
    
    def get(self, key, default=None):
        """获取命令处理器"""
        handler = get_handler(key)
        return handler if handler else default
    
    def __getitem__(self, key):
        """通过索引访问"""
        handler = get_handler(key)
        if handler is None:
            raise KeyError(f"Command handler '{key}' not found")
        return handler
    
    def __contains__(self, key):
        """检查命令是否存在"""
        return get_handler(key) is not None
    
    def items(self):
        """返回所有命令处理器"""
        return get_all_handlers().items()
    
    def keys(self):
        """返回所有命令名称"""
        return get_all_handlers().keys()
    
    def values(self):
        """返回所有命令处理器实例"""
        return get_all_handlers().values()


# 创建全局代理实例
COMMAND_HANDLERS = _CommandHandlersProxy()


# 导出所有公共接口
__all__ = [
    'CommandHandler',
    'parse_command',
    'get_all_handlers',
    'get_handler',
    'handle_command',
    'COMMAND_HANDLERS',  # 向后兼容
]

