"""任务模块 - 保持向后兼容的导入入口"""
import logging

logger = logging.getLogger(__name__)

# 从新的模块化任务导入(保持向后兼容)
from .tasks import *
