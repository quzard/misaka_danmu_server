"""
API端点模块
按功能模块组织的API路由
"""

from . import (
    config, auth, scraper, metadata_source, media_server,
    anime, source, episode, search, import_api, task,
    token, config_extra, settings, scheduled_task, webhook, system, auth_extra
)

__all__ = [
    'config', 'auth', 'scraper', 'metadata_source', 'media_server',
    'anime', 'source', 'episode', 'search', 'import_api', 'task',
    'token', 'config_extra', 'settings', 'scheduled_task', 'webhook', 'system', 'auth_extra'
]

