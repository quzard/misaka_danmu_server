"""
工具函数模块

使用方式:
    from src.utils import parse_search_keyword, unified_search
    from src.utils import SearchTimer, SEARCH_TYPE_WEBHOOK
    from src.utils import convert_to_chinese_title, clean_xml_string
"""

# 通用工具
from .common import parse_search_keyword, sample_comments_evenly, clean_xml_string

# 搜索工具
from .search import unified_search

# 搜索计时器
from .search_timer import (
    SearchTimer,
    SubStepTiming,
    SEARCH_TYPE_WEBHOOK,
    SEARCH_TYPE_FALLBACK_SEARCH,
    SEARCH_TYPE_FALLBACK_MATCH,
    SEARCH_TYPE_CONTROL_AUTO_IMPORT,
    SEARCH_TYPE_CONTROL_SEARCH,
    SEARCH_TYPE_HOME,
)

# 季度映射
from .season_mapper import (
    ai_type_and_season_mapping_and_correction,
    title_contains_season_name,
)

# 名称转换
from .name_converter import convert_to_chinese_title

# 路径模板
from .path_template import (
    DanmakuPathTemplate,
    create_danmaku_context,
    generate_danmaku_path,
)

# 图片工具
from .image_utils import download_image, resize_image

# Docker工具
from .docker_utils import is_docker_environment

# 播放历史
from .play_history import record_play_history

# 内部轮询
from .internal_polling import InternalPollingManager

# 代理中间件
from .proxy_middleware import init_proxy_middleware

# HTTP Transport 管理
from .transport_manager import TransportManager

__all__ = [
    # 通用工具
    'parse_search_keyword',
    'sample_comments_evenly',
    'clean_xml_string',
    # 搜索工具
    'unified_search',
    # 搜索计时器
    'SearchTimer',
    'SubStepTiming',
    'SEARCH_TYPE_WEBHOOK',
    'SEARCH_TYPE_FALLBACK_SEARCH',
    'SEARCH_TYPE_FALLBACK_MATCH',
    'SEARCH_TYPE_CONTROL_AUTO_IMPORT',
    'SEARCH_TYPE_CONTROL_SEARCH',
    'SEARCH_TYPE_HOME',
    # 季度映射
    'ai_type_and_season_mapping_and_correction',
    'title_contains_season_name',
    # 名称转换
    'convert_to_chinese_title',
    # 路径模板
    'DanmakuPathTemplate',
    'create_danmaku_context',
    'generate_danmaku_path',
    # 图片工具
    'download_image',
    'resize_image',
    # Docker工具
    'is_docker_environment',
    # 播放历史
    'record_play_history',
    # 内部轮询
    'InternalPollingManager',
    # 代理中间件
    'init_proxy_middleware',
    # HTTP Transport 管理
    'TransportManager',
]

