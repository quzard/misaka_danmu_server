"""
服务层 - 各种 Manager 服务

使用方式:
    from src.services import TaskManager, TaskStatus, TaskSuccess, TaskPauseForRateLimit
    from src.services import ScraperManager, MetadataSourceManager
    from src.services import SchedulerManager, setup_logging, get_logs
"""

# 任务管理
from .task_manager import TaskManager, TaskStatus, TaskSuccess, TaskPauseForRateLimit

# 弹幕源管理
from .scraper_manager import ScraperManager

# 元数据源管理
from .metadata_manager import MetadataSourceManager

# Webhook管理
from .webhook_manager import WebhookManager

# 媒体服务器管理
from .media_server_manager import MediaServerManager, get_media_server_manager

# 标题识别
from .title_recognition import TitleRecognitionManager

# 下载任务管理
from .download_task_manager import DownloadTaskManager, DownloadTask, get_download_task_manager

# 传输管理
from .transport_manager import TransportManager

# 调度器
from .scheduler import SchedulerManager

# 日志管理
from .log_manager import LogManager, setup_logging, get_logs, subscribe_to_logs, unsubscribe_from_logs

__all__ = [
    # 任务管理
    'TaskManager',
    'TaskStatus',
    'TaskSuccess',
    'TaskPauseForRateLimit',
    # 弹幕源管理
    'ScraperManager',
    # 元数据源管理
    'MetadataSourceManager',
    # Webhook管理
    'WebhookManager',
    # 媒体服务器管理
    'MediaServerManager',
    'get_media_server_manager',
    # 标题识别
    'TitleRecognitionManager',
    # 下载任务管理
    'DownloadTaskManager',
    'DownloadTask',
    'get_download_task_manager',
    # 传输管理
    'TransportManager',
    # 调度器
    'SchedulerManager',
    # 日志管理
    'LogManager',
    'setup_logging',
    'get_logs',
    'subscribe_to_logs',
    'unsubscribe_from_logs',
]

