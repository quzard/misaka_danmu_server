"""
内置轮询任务管理器

用于管理应用程序内置的后台轮询任务，如资源自动更新等。
与 SchedulerManager（用户可配置的定时任务）不同，这里的任务是内置的、由配置开关控制的。
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict

from fastapi import FastAPI


@dataclass
class PollingTaskInfo:
    """轮询任务信息"""
    name: str
    handler: Callable[[FastAPI], Coroutine[Any, Any, None]]
    enabled_key: str  # 配置键：是否启用 (值为 "true"/"false")
    interval_key: str  # 配置键：间隔时间（分钟）
    default_interval: int  # 默认间隔（分钟）
    min_interval: int  # 最小间隔（分钟）
    startup_delay: int  # 启动延迟（秒）


class InternalPollingManager:
    """
    内置轮询任务管理器
    
    用法：
    1. 创建管理器实例
    2. 使用 register() 注册轮询任务
    3. 调用 start() 启动所有轮询
    4. 应用关闭时调用 stop() 停止所有轮询
    """
    
    def __init__(self, app: FastAPI):
        self.app = app
        self.config_manager = app.state.config_manager
        self._polling_tasks: Dict[str, PollingTaskInfo] = {}
        self._running_coroutines: Dict[str, asyncio.Task] = {}
        self._running = False
        self.logger = logging.getLogger("InternalPollingManager")
    
    def register(
        self,
        name: str,
        handler: Callable[[FastAPI], Coroutine[Any, Any, None]],
        enabled_key: str,
        interval_key: str,
        default_interval: int = 15,
        min_interval: int = 5,
        startup_delay: int = 60
    ):
        """
        注册一个轮询任务
        
        Args:
            name: 任务名称（唯一标识）
            handler: 异步处理函数，接收 FastAPI app 作为参数
            enabled_key: 配置键名，用于检查是否启用（值应为 "true" 或 "false"）
            interval_key: 配置键名，用于获取轮询间隔（分钟）
            default_interval: 默认轮询间隔（分钟）
            min_interval: 最小轮询间隔（分钟），防止过于频繁
            startup_delay: 启动延迟（秒），避免应用启动时负载过高
        """
        self._polling_tasks[name] = PollingTaskInfo(
            name=name,
            handler=handler,
            enabled_key=enabled_key,
            interval_key=interval_key,
            default_interval=default_interval,
            min_interval=min_interval,
            startup_delay=startup_delay
        )
        self.logger.info(f"已注册内置轮询任务: {name}")
    
    def _register_builtin_tasks(self):
        """注册所有内置轮询任务"""
        # 延迟导入避免循环依赖
        from src.internal_tasks.scraper_update import scraper_auto_update_handler

        # 资源仓库自动更新
        self.register(
            name="scraper_auto_update",
            handler=scraper_auto_update_handler,
            enabled_key="scraperAutoUpdateEnabled",
            interval_key="scraperAutoUpdateInterval",
            default_interval=30,  # 30分钟
            min_interval=15,      # 最小15分钟
            startup_delay=60      # 启动后60秒开始
        )

    async def start(self):
        """启动所有已注册的轮询任务"""
        # 自动注册内置任务
        self._register_builtin_tasks()

        self._running = True
        for name, task_info in self._polling_tasks.items():
            self._running_coroutines[name] = asyncio.create_task(
                self._run_polling_loop(task_info)
            )
            self.logger.info(f"内置轮询任务 '{name}' 已启动")
    
    async def stop(self):
        """停止所有轮询任务"""
        self._running = False
        for name, task in self._running_coroutines.items():
            task.cancel()
            self.logger.info(f"内置轮询任务 '{name}' 已停止")
        
        if self._running_coroutines:
            await asyncio.gather(*self._running_coroutines.values(), return_exceptions=True)
        self._running_coroutines.clear()
    
    async def _get_interval(self, task_info: PollingTaskInfo) -> int:
        """获取轮询间隔（分钟）"""
        try:
            interval_str = await self.config_manager.get(task_info.interval_key, str(task_info.default_interval))
            interval = int(interval_str)
            return max(interval, task_info.min_interval)
        except (ValueError, TypeError):
            return task_info.default_interval
    
    async def _is_enabled(self, task_info: PollingTaskInfo) -> bool:
        """检查任务是否启用"""
        enabled_str = await self.config_manager.get(task_info.enabled_key, "false")
        return enabled_str.lower() == "true"
    
    async def _run_polling_loop(self, task_info: PollingTaskInfo):
        """运行单个任务的轮询循环"""
        # 启动延迟
        await asyncio.sleep(task_info.startup_delay)
        
        while self._running:
            try:
                # 获取间隔时间
                interval_minutes = await self._get_interval(task_info)
                
                # 检查是否启用
                if await self._is_enabled(task_info):
                    try:
                        await task_info.handler(self.app)
                    except Exception as e:
                        self.logger.error(f"轮询任务 '{task_info.name}' 执行出错: {e}", exc_info=True)
                
                # 等待下一次轮询
                await asyncio.sleep(interval_minutes * 60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"轮询任务 '{task_info.name}' 循环出错: {e}", exc_info=True)
                await asyncio.sleep(300)  # 出错后等待5分钟再重试

