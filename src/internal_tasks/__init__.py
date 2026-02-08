"""
内置轮询任务模块

包含所有内置的后台轮询任务处理器。
"""
from .scraper_update import scraper_auto_update_handler

__all__ = ["scraper_auto_update_handler"]

