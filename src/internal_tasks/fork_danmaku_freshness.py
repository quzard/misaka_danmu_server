"""
内置轮询任务：弹幕保鲜（fork 扩展）

每 5 分钟处理一次到期的弹幕重抓计划，逻辑在 src/fork_freshness.py。
开关是配置项 forkDanmakuFreshnessEnabled，默认开启。
"""
from fastapi import FastAPI

from .base import BasePollingTask


class ForkDanmakuFreshnessTask(BasePollingTask):
    """弹幕保鲜"""
    name = "fork_danmaku_freshness"
    enabled_key = ""  # 空字符串表示始终启用，开关在 handler 内部判断
    interval_key = ""  # 空字符串表示使用硬编码默认值
    default_interval = 5
    min_interval = 5
    startup_delay = 90

    @staticmethod
    async def handler(app: FastAPI) -> None:
        from src.fork_freshness import tick
        await tick(app)
