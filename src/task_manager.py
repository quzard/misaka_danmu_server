import asyncio
import logging
import traceback
from enum import Enum
import time
import json
from typing import Any, Callable, Coroutine, Dict, List, Tuple, Optional # Add HTTPException, status
from uuid import uuid4, UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from .config_manager import ConfigManager

from . import models, crud

logger = logging.getLogger(__name__)
from fastapi import HTTPException, status

class TaskStatus(str, Enum):
    PENDING = "排队中"
    RUNNING = "运行中"
    COMPLETED = "已完成"
    FAILED = "失败"
    PAUSED = "已暂停"

class TaskSuccess(Exception):
    """自定义异常，用于表示任务成功完成并附带一条最终消息。"""
    pass

class Task:
    def __init__(self, task_id: str, title: str, coro_factory: Callable[[Callable], Coroutine], scheduled_task_id: Optional[str] = None, unique_key: Optional[str] = None, task_type: Optional[str] = None, task_parameters: Optional[Dict] = None, queue_type: str = "download"):
        self.task_id = task_id
        self.title = title
        self.coro_factory: Callable[[AsyncSession, Callable], Coroutine] = coro_factory
        self.done_event = asyncio.Event()
        self.pause_event = asyncio.Event()
        self.running_coro_task: Optional[asyncio.Task] = None
        self.scheduled_task_id = scheduled_task_id
        self.last_update_time: float = 0.0
        self.update_lock = asyncio.Lock()
        self.unique_key = unique_key
        self.task_type = task_type  # 任务类型，用于恢复
        self.task_parameters = task_parameters or {}  # 任务参数，用于恢复
        self.queue_type = queue_type  # 队列类型: "download" 或 "management"
        self.pause_event.set() # 默认为运行状态 (事件被设置)

class TaskManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager):
        self._session_factory = session_factory
        # 三队列架构: 下载队列、管理队列、后备队列
        self._download_queue: asyncio.Queue = asyncio.Queue()
        self._management_queue: asyncio.Queue = asyncio.Queue()
        self._fallback_queue: asyncio.Queue = asyncio.Queue()
        self._download_worker_task: asyncio.Task | None = None
        self._management_worker_task: asyncio.Task | None = None
        self._fallback_worker_task: asyncio.Task | None = None
        self._current_download_task: Optional[Task] = None
        self._current_management_task: Optional[Task] = None
        self._current_fallback_task: Optional[Task] = None
        self._pending_titles: set[str] = set()
        self._active_unique_keys: set[str] = set()
        self._lock = asyncio.Lock()
        self.config_manager = config_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    def start(self):
        """启动后台工作协程来处理任务队列。"""
        if self._download_worker_task is None:
            self._download_worker_task = asyncio.create_task(self._download_worker())
            self._management_worker_task = asyncio.create_task(self._management_worker())
            self._fallback_worker_task = asyncio.create_task(self._fallback_worker())
            # 启动时处理中断的任务
            asyncio.create_task(self._handle_interrupted_tasks())
            self.logger.info("任务管理器已启动 (下载队列 + 管理队列 + 后备队列)。")

    async def _run_task_wrapper(self, task: Task, queue_type: str = "download"):
        """
        一个独立的包装器，用于在后台安全地执行单个任务。
        这可以防止单个任务的失败或阻塞影响到整个任务管理器。

        Args:
            task: 要执行的任务
            queue_type: 队列类型 ("download" 或 "management")
        """
        self.logger.info(f"开始执行任务 '{task.title}' (ID: {task.task_id}) [队列: {queue_type}]")
        try:
            # This task is now running, remove it from pending titles
            # This is now the single point of responsibility for this cleanup.
            async with self._lock:
                self._pending_titles.discard(task.title)

            async with self._session_factory() as session:
                await crud.update_task_progress_in_history(
                    session, task.task_id, TaskStatus.RUNNING, 0, "正在初始化..."
                )

                # 保存任务状态到缓存表（如果有任务类型和参数）
                if task.task_type and task.task_parameters:
                    await crud.save_task_state_cache(
                        session, task.task_id, task.task_type, json.dumps(task.task_parameters)
                    )

                progress_callback = self._get_progress_callback(task)
                actual_coroutine = task.coro_factory(session, progress_callback)

                running_task = asyncio.create_task(actual_coroutine)
                task.running_coro_task = running_task
                await running_task

                await crud.finalize_task_in_history(
                    session, task.task_id, TaskStatus.COMPLETED, "任务成功完成"
                )
                self.logger.info(f"任务 '{task.title}' (ID: {task.task_id}) 已成功完成 [队列: {queue_type}]。")
        except TaskSuccess as e:
            self.logger.debug(f"捕获到 TaskSuccess 异常: {e}")
            final_message = str(e) if str(e) else "任务成功完成"
            async with self._session_factory() as final_session:
                await crud.finalize_task_in_history(
                    final_session, task.task_id, TaskStatus.COMPLETED, final_message
                )
            self.logger.info(f"任务 '{task.title}' (ID: {task.task_id}) 已成功完成，消息: {final_message}")
        except asyncio.CancelledError:
            self.logger.info(f"任务 '{task.title}' (ID: {task.task_id}) 已被用户取消。")
            async with self._session_factory() as final_session:
                await crud.finalize_task_in_history(
                    final_session, task.task_id, TaskStatus.FAILED, "任务已被用户取消"
                )
        except Exception:
            error_message = f"任务执行失败 - {traceback.format_exc()}"
            async with self._session_factory() as final_session:
                await crud.finalize_task_in_history(
                    final_session, task.task_id, TaskStatus.FAILED, error_message.splitlines()[-1]
                )
            self.logger.error(f"任务 '{task.title}' (ID: {task.task_id}) 执行失败: {traceback.format_exc()}")
        finally:
            async with self._lock:
                if task.unique_key:
                    self._active_unique_keys.discard(task.unique_key)
                # Also remove from pending_titles again just in case of race conditions.
                self._pending_titles.discard(task.title)
            task.done_event.set()

    async def stop(self):
        """停止任务管理器。"""
        if self._download_worker_task:
            self._download_worker_task.cancel()
            try:
                await self._download_worker_task
            except asyncio.CancelledError:
                pass
            self._download_worker_task = None

        if self._management_worker_task:
            self._management_worker_task.cancel()
            try:
                await self._management_worker_task
            except asyncio.CancelledError:
                pass
            self._management_worker_task = None

        if self._fallback_worker_task:
            self._fallback_worker_task.cancel()
            try:
                await self._fallback_worker_task
            except asyncio.CancelledError:
                pass
            self._fallback_worker_task = None

        self.logger.info("任务管理器已停止。")

    async def _download_worker(self):
        """从下载队列中获取并执行任务。"""
        while True:
            task: Task = await self._download_queue.get()
            try:
                self._current_download_task = task
                # The wrapper now handles removing the title from the pending set.
                await self._run_task_wrapper(task, queue_type="download")
            except Exception as e:
                # 防止 worker 崩溃 - 捕获所有未被 _run_task_wrapper 处理的异常
                self.logger.error(f"❌ Download Worker 捕获到未处理的异常: {type(e).__name__}: {e}", exc_info=True)
            finally:
                self._current_download_task = None
                self._download_queue.task_done()

    async def _management_worker(self):
        """从管理队列中获取并执行任务。"""
        while True:
            task: Task = await self._management_queue.get()
            try:
                self._current_management_task = task
                # The wrapper now handles removing the title from the pending set.
                await self._run_task_wrapper(task, queue_type="management")
            except Exception as e:
                # 防止 worker 崩溃 - 捕获所有未被 _run_task_wrapper 处理的异常
                self.logger.error(f"❌ Management Worker 捕获到未处理的异常: {type(e).__name__}: {e}", exc_info=True)
            finally:
                self._current_management_task = None
                self._management_queue.task_done()

    async def _fallback_worker(self):
        """从后备队列中获取并执行任务。"""
        while True:
            task: Task = await self._fallback_queue.get()
            try:
                self._current_fallback_task = task
                # The wrapper now handles removing the title from the pending set.
                await self._run_task_wrapper(task, queue_type="fallback")
            except Exception as e:
                # 防止 worker 崩溃 - 捕获所有未被 _run_task_wrapper 处理的异常
                self.logger.error(f"❌ Fallback Worker 捕获到未处理的异常: {type(e).__name__}: {e}", exc_info=True)
            finally:
                self._current_fallback_task = None
                self._fallback_queue.task_done()

    async def submit_task(
        self,
        coro_factory: Callable[[AsyncSession, Callable], Coroutine],
        title: str,
        scheduled_task_id: Optional[str] = None,
        unique_key: Optional[str] = None,
        run_immediately: bool = False,
        task_type: Optional[str] = None,
        task_parameters: Optional[Dict] = None,
        queue_type: str = "download"
    ) -> Tuple[str, asyncio.Event]:
        """提交一个新任务到队列，并在数据库中创建记录。返回任务ID和完成事件。

        Args:
            queue_type: 队列类型，"download" (下载队列)、"management" (管理队列) 或 "fallback" (后备队列)
        """
        async with self._lock:
            # 检查是否有同名任务正在排队或运行
            if title in self._pending_titles:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"任务 '{title}' 已在队列中，请勿重复提交。"
                )
            # 检查三个队列的当前任务
            if (self._current_download_task and self._current_download_task.title == title) or \
               (self._current_management_task and self._current_management_task.title == title) or \
               (self._current_fallback_task and self._current_fallback_task.title == title):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"任务 '{title}' 已在运行中，请勿重复提交。"
                )

            # 新增：检查唯一键，防止同一资源的多个任务同时进行
            if unique_key:
                if unique_key in self._active_unique_keys:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"一个针对此媒体的相似任务已在队列中或正在运行，请勿重复提交。"
                    )
                self._active_unique_keys.add(unique_key)
            self._pending_titles.add(title)

        task_id = str(uuid4())
        task = Task(task_id, title, coro_factory, scheduled_task_id=scheduled_task_id, unique_key=unique_key, task_type=task_type, task_parameters=task_parameters, queue_type=queue_type)

        async with self._session_factory() as session:
            await crud.create_task_in_history(
                session, task_id, title, TaskStatus.PENDING, "等待执行...", scheduled_task_id=scheduled_task_id, queue_type=queue_type
            )

        if run_immediately:
            self.logger.info(f"立即执行任务 '{title}' (ID: {task_id})，绕过队列 [{queue_type}]。")
            asyncio.create_task(self._run_task_wrapper(task, queue_type=queue_type))
        else:
            # 根据队列类型选择队列
            if queue_type == "download":
                target_queue = self._download_queue
            elif queue_type == "management":
                target_queue = self._management_queue
            elif queue_type == "fallback":
                target_queue = self._fallback_queue
            else:
                raise ValueError(f"无效的队列类型: {queue_type}")

            await target_queue.put(task)
            self.logger.info(f"任务 '{title}' 已提交到 {queue_type} 队列，ID: {task_id}")
        return task_id, task.done_event

    def _get_progress_callback(self, task: Task) -> Callable:
        """为特定任务创建一个可暂停的回调闭包。"""
        async def pausable_callback(progress: int, description: str, status: Optional[TaskStatus] = None):
            # 核心暂停逻辑：在每次更新进度前，检查暂停事件。
            # 如果事件被清除 (cleared)，.wait() 将会阻塞，直到事件被重新设置 (set)。
            await task.pause_event.wait()

            now = time.time()
            # 只在状态改变、首次、完成或距离上次更新超过0.5秒时才更新数据库
            is_status_change = status is not None
            force_update = progress == 0 or progress >= 100 or is_status_change
            
            # 使用锁来防止并发更新 last_update_time
            async with task.update_lock:
                if not force_update and (now - task.last_update_time < 0.5):
                    return
                task.last_update_time = now

            # 数据库更新现在是同步的（在回调的协程内），但由于此逻辑，它不会频繁发生。
            # 这避免了创建大量并发任务，从而保护了数据库连接池。
            try:
                async with self._session_factory() as session:
                    await crud.update_task_progress_in_history(
                        session, task.task_id, status or TaskStatus.RUNNING, int(progress), description
                    )
            except Exception as e:
                self.logger.error(f"任务进度更新失败 (ID: {task.task_id}): {e}", exc_info=False)

        return pausable_callback

    async def cancel_pending_task(self, task_id: str) -> bool:
        """
        从队列中移除一个待处理的任务。
        注意：此操作不是线程安全的，但对于单工作线程模型是可接受的。
        """
        found_and_removed = False
        task_to_remove: Optional[Task] = None

        # 检查下载队列
        temp_list = []
        while not self._download_queue.empty():
            try:
                task = self._download_queue.get_nowait()
                if task.task_id == task_id:
                    found_and_removed = True
                    task_to_remove = task
                    task.done_event.set()
                    self.logger.info(f"已从下载队列中取消待处理任务 '{task.title}' (ID: {task_id})。")
                else:
                    temp_list.append(task)
            except asyncio.QueueEmpty:
                break

        for task in temp_list:
            await self._download_queue.put(task)

        # 如果在下载队列中没找到，检查管理队列
        if not found_and_removed:
            temp_list = []
            while not self._management_queue.empty():
                try:
                    task = self._management_queue.get_nowait()
                    if task.task_id == task_id:
                        found_and_removed = True
                        task_to_remove = task
                        task.done_event.set()
                        self.logger.info(f"已从管理队列中取消待处理任务 '{task.title}' (ID: {task_id})。")
                    else:
                        temp_list.append(task)
                except asyncio.QueueEmpty:
                    break

            for task in temp_list:
                await self._management_queue.put(task)

        # 如果在管理队列中也没找到，检查后备队列
        if not found_and_removed:
            temp_list = []
            while not self._fallback_queue.empty():
                try:
                    task = self._fallback_queue.get_nowait()
                    if task.task_id == task_id:
                        found_and_removed = True
                        task_to_remove = task
                        task.done_event.set()
                        self.logger.info(f"已从后备队列中取消待处理任务 '{task.title}' (ID: {task_id})。")
                    else:
                        temp_list.append(task)
                except asyncio.QueueEmpty:
                    break

            for task in temp_list:
                await self._fallback_queue.put(task)

        # 修正：如果一个待处理任务被取消，必须同时清理其在管理器中的状态（任务标题和唯一键），
        # 以允许用户重新提交该任务。
        if found_and_removed and task_to_remove:
            async with self._lock:
                self._pending_titles.discard(task_to_remove.title)
                if task_to_remove.unique_key:
                    self._active_unique_keys.discard(task_to_remove.unique_key)
                    self.logger.info(f"已为已取消的待处理任务释放唯一键: {task_to_remove.unique_key}")

        return found_and_removed

    async def abort_current_task(self, task_id: str) -> bool:
        """如果ID匹配，则中止当前正在运行或暂停的任务。"""
        # 检查下载队列的当前任务
        if self._current_download_task and self._current_download_task.task_id == task_id and self._current_download_task.running_coro_task:
            self.logger.info(f"正在中止下载队列任务 '{self._current_download_task.title}' (ID: {task_id})")
            # 解除暂停，以便任务可以接收到取消异常
            self._current_download_task.pause_event.set()
            # 取消底层的协程
            self._current_download_task.running_coro_task.cancel()
            return True

        # 检查管理队列的当前任务
        if self._current_management_task and self._current_management_task.task_id == task_id and self._current_management_task.running_coro_task:
            self.logger.info(f"正在中止管理队列任务 '{self._current_management_task.title}' (ID: {task_id})")
            # 解除暂停，以便任务可以接收到取消异常
            self._current_management_task.pause_event.set()
            # 取消底层的协程
            self._current_management_task.running_coro_task.cancel()
            return True

        # 检查后备队列的当前任务
        if self._current_fallback_task and self._current_fallback_task.task_id == task_id and self._current_fallback_task.running_coro_task:
            self.logger.info(f"正在中止后备队列任务 '{self._current_fallback_task.title}' (ID: {task_id})")
            # 解除暂停，以便任务可以接收到取消异常
            self._current_fallback_task.pause_event.set()
            # 取消底层的协程
            self._current_fallback_task.running_coro_task.cancel()
            return True

        self.logger.warning(f"尝试中止任务 {task_id} 失败，因为它不是当前任务或未在运行。")
        return False

    async def pause_task(self, task_id: str) -> bool:
        """如果ID匹配，则暂停当前正在运行的任务。"""
        # 检查下载队列的当前任务
        if self._current_download_task and self._current_download_task.task_id == task_id:
            async with self._session_factory() as session:
                self._current_download_task.pause_event.clear()
                await crud.update_task_status(session, self._current_download_task.task_id, TaskStatus.PAUSED)
                self.logger.info(f"已暂停下载队列任务 '{self._current_download_task.title}' (ID: {task_id})。")
                return True

        # 检查管理队列的当前任务
        if self._current_management_task and self._current_management_task.task_id == task_id:
            async with self._session_factory() as session:
                self._current_management_task.pause_event.clear()
                await crud.update_task_status(session, self._current_management_task.task_id, TaskStatus.PAUSED)
                self.logger.info(f"已暂停管理队列任务 '{self._current_management_task.title}' (ID: {task_id})。")
                return True

        # 检查后备队列的当前任务
        if self._current_fallback_task and self._current_fallback_task.task_id == task_id:
            async with self._session_factory() as session:
                self._current_fallback_task.pause_event.clear()
                await crud.update_task_status(session, self._current_fallback_task.task_id, TaskStatus.PAUSED)
                self.logger.info(f"已暂停后备队列任务 '{self._current_fallback_task.title}' (ID: {task_id})。")
                return True

        self.logger.warning(f"尝试暂停任务 {task_id} 失败，因为它不是当前正在运行的任务。")
        return False

    async def resume_task(self, task_id: str) -> bool:
        """如果ID匹配，则恢复当前已暂停的任务。"""
        # 检查下载队列的当前任务
        if self._current_download_task and self._current_download_task.task_id == task_id:
            async with self._session_factory() as session:
                self._current_download_task.pause_event.set()
                await crud.update_task_status(session, self._current_download_task.task_id, TaskStatus.RUNNING)
                self.logger.info(f"已恢复下载队列任务 '{self._current_download_task.title}' (ID: {task_id})。")
                return True

        # 检查管理队列的当前任务
        if self._current_management_task and self._current_management_task.task_id == task_id:
            async with self._session_factory() as session:
                self._current_management_task.pause_event.set()
                await crud.update_task_status(session, self._current_management_task.task_id, TaskStatus.RUNNING)
                self.logger.info(f"已恢复管理队列任务 '{self._current_management_task.title}' (ID: {task_id})。")
                return True

        # 检查后备队列的当前任务
        if self._current_fallback_task and self._current_fallback_task.task_id == task_id:
            async with self._session_factory() as session:
                self._current_fallback_task.pause_event.set()
                await crud.update_task_status(session, self._current_fallback_task.task_id, TaskStatus.RUNNING)
                self.logger.info(f"已恢复后备队列任务 '{self._current_fallback_task.title}' (ID: {task_id})。")
                return True

        self.logger.warning(f"尝试恢复任务 {task_id} 失败，因为它不是当前已暂停的任务。")
        return False

    async def _handle_interrupted_tasks(self):
        """处理服务重启时中断的任务"""
        try:
            async with self._session_factory() as session:
                # 获取所有运行中的任务状态
                running_tasks = await crud.get_all_running_task_states(session)

                if running_tasks:
                    self.logger.info(f"发现 {len(running_tasks)} 个中断的任务，正在处理...")

                    # 尝试恢复任务或标记为失败
                    for task_info in running_tasks:
                        await self._try_recover_task(task_info)

                    # 清理所有中断的任务状态
                    await crud.mark_interrupted_tasks_as_failed(session)
                    self.logger.info("已处理所有中断的任务")
                else:
                    self.logger.info("没有发现中断的任务")

        except Exception as e:
            self.logger.error(f"处理中断任务时发生错误: {e}", exc_info=True)

    async def _try_recover_task(self, task_info: Dict):
        """尝试恢复单个任务，如果无法恢复则记录日志"""
        task_id = task_info["taskId"]
        task_type = task_info["taskType"]
        task_title = task_info["taskTitle"]

        try:
            # 解析任务参数
            task_parameters = json.loads(task_info["taskParameters"])

            # 根据任务类型尝试恢复
            if task_type == "generic_import":
                await self._recover_generic_import_task(task_id, task_title, task_parameters)
            elif task_type == "match_fallback":
                await self._recover_match_fallback_task(task_id, task_title, task_parameters)
            else:
                self.logger.warning(f"未知的任务类型 '{task_type}'，无法恢复任务 '{task_title}' (ID: {task_id})")

        except Exception as e:
            self.logger.error(f"尝试恢复任务 '{task_title}' (ID: {task_id}) 时发生错误: {e}", exc_info=True)

    async def _recover_generic_import_task(self, task_id: str, task_title: str, task_parameters: Dict):
        """恢复通用导入任务"""
        try:
            # 这里可以根据需要重新创建任务
            # 由于任务可能已经部分完成，我们选择不自动重启，而是记录日志
            self.logger.info(f"通用导入任务 '{task_title}' (ID: {task_id}) 因服务中断而失败，参数: {task_parameters}")

            # 可以在这里添加逻辑来检查任务是否已经部分完成
            # 并决定是否需要重新启动任务

        except Exception as e:
            self.logger.error(f"恢复通用导入任务时发生错误: {e}", exc_info=True)

    async def _recover_match_fallback_task(self, task_id: str, task_title: str, task_parameters: Dict):
        """恢复匹配后备任务"""
        try:
            # 匹配后备任务通常可以安全地重新启动
            self.logger.info(f"匹配后备任务 '{task_title}' (ID: {task_id}) 因服务中断而失败，参数: {task_parameters}")

            # 可以在这里添加逻辑来重新启动匹配后备任务
            # 由于这类任务通常是幂等的，可以安全重启

        except Exception as e:
            self.logger.error(f"恢复匹配后备任务时发生错误: {e}", exc_info=True)