"""
notification/menus — 按菜单条目拆分的 Mixin 模块

每个文件对应一个 /command 菜单，通过 Mixin 继承到 NotificationService。
"""
from ._base import ImportBaseMixin
from .search import SearchMenuMixin
from .auto import AutoMenuMixin
from .url import UrlMenuMixin
from .library import LibraryMenuMixin
from .tokens import TokensMenuMixin
from .tasks_menu import TasksMenuMixin
from .cache import CacheMenuMixin

__all__ = [
    "ImportBaseMixin",
    "SearchMenuMixin",
    "AutoMenuMixin",
    "UrlMenuMixin",
    "LibraryMenuMixin",
    "TokensMenuMixin",
    "TasksMenuMixin",
    "CacheMenuMixin",
]

