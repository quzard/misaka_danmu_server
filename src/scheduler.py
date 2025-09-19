import asyncio
import importlib
import pkgutil
import inspect
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import crud
from .rate_limiter import RateLimiter
from .jobs.base import BaseJob
from .jobs.webhook_processor import WebhookProcessorJob
from .timezone import get_app_timezone
from .task_manager import TaskManager
from .scraper_manager import ScraperManager
from .metadata_manager import MetadataSourceManager
from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

def cron_is_valid(cron: str, min_hours: int) -> bool:
    """
    一个简单的CRON表达式验证器，用于检查轮询间隔是否满足最小小时数。
    注意：这是一个非常简化的检查，只处理常见的 '*/X' 小时格式。
    """
    try:
        parts = cron.split()
        if len(parts) != 5:
            # 不支持带秒或年的格式，但允许它通过，因为这可能是高级用法
            return True

        hour_part = parts[1]
        
        # Case 1: '*/X' - every X hours
        if hour_part.startswith('*/'):
            interval = int(hour_part[2:])
            if interval < min_hours:
                return False
        elif hour_part == '*': # every hour
            return False
    except (ValueError, IndexError): return False
    return True

# --- Scheduler Manager ---

class SchedulerManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], task_manager: TaskManager, scraper_manager: ScraperManager, rate_limiter: RateLimiter, metadata_manager: MetadataSourceManager, config_manager: ConfigManager):
        self._session_factory = session_factory
        self.task_manager = task_manager
        self.scraper_manager = scraper_manager
        self.rate_limiter = rate_limiter
        self.metadata_manager = metadata_manager
        self.config_manager = config_manager
        self.scheduler = AsyncIOScheduler(timezone=str(get_app_timezone()))
        self._job_classes: Dict[str, Type[BaseJob]] = {}

    def _load_jobs(self):
        """
        动态发现并加载 'jobs' 目录下的所有任务类。
        """
        jobs_package_path = [str(Path("/app/src/jobs"))]
        for finder, name, ispkg in pkgutil.iter_modules(jobs_package_path):
            if name.startswith("_") or name == "base":
                continue

            try:
                module_name = f"src.jobs.{name}"
                module = importlib.import_module(module_name)
                for class_name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseJob) and obj is not BaseJob:
                        if obj.job_type in self._job_classes:
                            logger.warning(f"发现重复的定时任务类型 '{obj.job_type}'。将被覆盖。")
                        self._job_classes[obj.job_type] = obj
                        logger.info(f"定时任务 '{obj.job_name}' (类型: {obj.job_type}, 来自模块 {name}) 已加载。")
            except Exception as e:
                logger.error(f"从模块 {name} 加载定时任务失败: {e}")

    def get_available_jobs(self) -> List[Dict[str, str]]:
        """获取所有已加载的可用任务类型及其名称。"""
        return [{"jobType": job.job_type, "name": job.job_name} for job in self._job_classes.values()]

    def _create_job_runner(self, job_type: str, scheduled_task_id: str) -> Callable:
        """创建一个包装器，用于在 TaskManager 中运行任务，并等待其完成。"""
        job_class = self._job_classes[job_type]
        
        async def runner():
            # 修正：智能地将依赖项传递给任务的构造函数
            # 这使得像 TmdbAutoMapJob 这样的任务可以选择不接收 rate_limiter
            init_params = inspect.signature(job_class.__init__).parameters
            
            dependencies = {
                "session_factory": self._session_factory,
                "task_manager": self.task_manager,
                "scraper_manager": self.scraper_manager,
                "rate_limiter": self.rate_limiter,
                "metadata_manager": self.metadata_manager,
                "config_manager": self.config_manager,
            }
            
            args_to_pass = {name: dep for name, dep in dependencies.items() if name in init_params}
            job_instance = job_class(**args_to_pass)
            task_coro_factory = lambda session, callback: job_instance.run(session, callback)
            task_id, done_event = await self.task_manager.submit_task(
                task_coro_factory,
                job_instance.job_name,
                scheduled_task_id=scheduled_task_id
            )
            # The apscheduler job now waits for the actual task to complete.
            await done_event.wait()
            logger.info(f"定时任务的运行器已确认任务 '{job_instance.job_name}' (ID: {task_id}) 执行完毕。")
        
        return runner

    def _event_handler_wrapper(self, event: JobExecutionEvent):
        """
        一个同步的包装器，用于调度异步的事件处理器。
        这是为了解决 'coroutine was never awaited' 的 RuntimeWarning，
        确保我们的异步逻辑能被正确执行。
        """
        # 将真正的异步处理函数作为一个新任务在事件循环中运行
        asyncio.create_task(self._handle_job_event(event))

    async def _handle_job_event(self, event: JobExecutionEvent):
        job = self.scheduler.get_job(event.job_id)
        if job:
            # 修正：使用 event.scheduled_run_time 作为 last_run_at 时间。
            # 这比 job.last_run_time 更可靠，因为它直接来自刚刚发生的事件，
            # 并且能确保手动触发的任务也能正确记录运行时间。并将其转换为 naive datetime。
            last_run_time = event.scheduled_run_time.replace(tzinfo=None) if event.scheduled_run_time else None
            next_run_time = job.next_run_time.replace(tzinfo=None) if job.next_run_time else None
            async with self._session_factory() as session:
                await crud.update_scheduled_task_run_times(session, job.id, last_run_time, next_run_time)
            logger.info(f"已更新定时任务 '{job.name}' (ID: {job.id}) 的运行时间。")

    async def start(self):
        self._load_jobs()
        # 修正：使用同步的包装器作为监听器
        self.scheduler.add_listener(self._event_handler_wrapper, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        self.scheduler.start()
        await self.load_jobs_from_db()
        logger.info("定时任务调度器已启动。")

    async def stop(self):
        self.scheduler.shutdown()

    async def load_jobs_from_db(self):
        async with self._session_factory() as session:
            tasks = await crud.get_scheduled_tasks(session)
            for task in tasks:
                if task['jobType'] in self._job_classes:
                    try:
                        runner = self._create_job_runner(task['jobType'], task['taskId'])
                        job = self.scheduler.add_job(runner, CronTrigger.from_crontab(task['cronExpression']), id=task['taskId'], name=task['name'], replace_existing=True)
                        if not task['isEnabled']: self.scheduler.pause_job(task['taskId'])
                        next_run_time = job.next_run_time.replace(tzinfo=None) if job.next_run_time else None
                        await crud.update_scheduled_task_run_times(session, job.id, task['lastRunAt'], next_run_time)
                    except Exception as e:
                        logger.error(f"加载定时任务 '{task['name']}' (ID: {task['taskId']}) 失败: {e}")

    def _is_system_task(self, job_type: str) -> bool:
        """通过Job类判断是否为系统任务"""
        if job_type in self._job_classes:
            return getattr(self._job_classes[job_type], 'is_system_task', False)
        return False

    async def get_all_tasks(self) -> List[Dict[str, Any]]:
        """从数据库获取所有定时任务的列表，并标记系统任务。"""
        async with self._session_factory() as session:
            tasks = await crud.get_scheduled_tasks(session)
            # 为每个任务添加系统任务标识
            for task in tasks:
                task['isSystemTask'] = self._is_system_task(task['jobType'])
            return tasks

    async def add_task(self, name: str, job_type: str, cron: str, is_enabled: bool) -> Dict[str, Any]:
        # 新增：禁止前端创建系统内置任务
        if job_type == "tokenReset":
            raise ValueError("系统内置任务 'tokenReset' 不允许手动创建。")
        
        if job_type not in self._job_classes:
            raise ValueError(f"未知的任务类型: {job_type}")
        
        # 确保增量更新任务的轮询间隔不低于3小时
        if job_type == "incrementalRefresh" and not cron_is_valid(cron, 3):
            raise ValueError("定时增量更新任务的轮询间隔不得低于3小时。请使用如 '0 */3 * * *' (每3小时) 或更长的间隔。")
        
        # 确保某些任务类型只能创建一个
        async with self._session_factory() as session:
            if job_type == "incrementalRefresh":
                exists = await crud.check_scheduled_task_exists_by_type(session, "incrementalRefresh")
                if exists:
                    raise ValueError("定时追更任务已存在，无法重复创建。")
            elif job_type == "tmdbAutoMap":
                exists = await crud.check_scheduled_task_exists_by_type(session, "tmdbAutoMap")
                if exists:
                    raise ValueError("TMDB自动映射与更新任务已存在，无法重复创建。")
            elif job_type == "webhookProcessor":
                exists = await crud.check_scheduled_task_exists_by_type(session, "webhookProcessor")
                if exists:
                    raise ValueError("Webhook 延时任务处理器已存在，无法重复创建。")

            task_id = str(uuid4())
            await crud.create_scheduled_task(session, task_id, name, job_type, cron, is_enabled)
            runner = self._create_job_runner(job_type, task_id)
            job = self.scheduler.add_job(runner, CronTrigger.from_crontab(cron), id=task_id, name=name)
            if not is_enabled: job.pause()
            next_run_time = job.next_run_time.replace(tzinfo=None) if job.next_run_time else None
            await crud.update_scheduled_task_run_times(session, task_id, None, next_run_time)
            return await crud.get_scheduled_task(session, task_id)

    async def update_task(self, task_id: str, name: str, cron: str, is_enabled: bool) -> Optional[Dict[str, Any]]:
        async with self._session_factory() as session:
            task_info = await crud.get_scheduled_task(session, task_id)
            if not task_info: return None
            
            # 新增：防止修改系统任务
            if self._is_system_task(task_info['jobType']):
                raise ValueError("系统内置任务不允许修改")
            
            # 确保增量更新任务的轮询间隔不低于3小时
            if task_info['jobType'] == "incrementalRefresh" and not cron_is_valid(cron, 3):
                raise ValueError("定时增量更新任务的轮询间隔不得低于3小时。请使用如 '0 */3 * * *' (每3小时) 或更长的间隔。")
            await crud.update_scheduled_task(session, task_id, name, cron, is_enabled)
            job.modify(name=name)
            job.reschedule(trigger=CronTrigger.from_crontab(cron))
            if is_enabled: job.resume()
            else: job.pause()
            next_run_time = job.next_run_time.replace(tzinfo=None) if job.next_run_time else None
            await crud.update_scheduled_task_run_times(session, task_id, task_info['lastRunAt'], next_run_time)
            return await crud.get_scheduled_task(session, task_id)

    async def delete_task(self, task_id: str) -> bool:
        async with self._session_factory() as session:
            task_info = await crud.get_scheduled_task(session, task_id)
            if not task_info: return False
            
            # 新增：防止删除系统任务
            if self._is_system_task(task_info['jobType']):
                raise ValueError("系统内置任务不允许删除")
            
            if self.scheduler.get_job(task_id): self.scheduler.remove_job(task_id)
            await crud.delete_scheduled_task(session, task_id)
            return True

    async def run_task_now(self, task_id: str):
        """立即运行指定的定时任务"""
        async with self._session_factory() as session:
            task_info = await crud.get_scheduled_task(session, task_id)
            if not task_info:
                raise ValueError(f"找不到ID为 '{task_id}' 的定时任务")
            
            # 新增：防止手动运行系统任务
            if self._is_system_task(task_info['jobType']):
                raise ValueError("系统内置任务不允许手动运行")

        job = self.scheduler.get_job(task_id)
        if not job:
            raise ValueError(f"调度器中找不到ID为 '{task_id}' 的任务")

        # 修正：直接使用数据库中的 jobType，而不是从 job.func.keywords 获取
        runner = self._create_job_runner(task_info['jobType'], task_id)
        await runner()

    async def run_task_now_by_type(self, job_type: str):
        """根据任务类型查找任务并立即运行它。"""
        # 新增：防止手动运行系统任务类型
        if self._is_system_task(job_type):
            raise ValueError("系统内置任务不允许手动运行")
            
        async with self._session_factory() as session:
            task_id = await crud.get_scheduled_task_id_by_type(session, job_type)
        
        if not task_id:
            raise ValueError(f"找不到类型为 '{job_type}' 的定时任务")

        await self.run_task_now(task_id)    



