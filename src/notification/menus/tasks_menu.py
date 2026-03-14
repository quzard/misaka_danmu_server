"""
/tasks 菜单 Mixin — 定时任务列表 + 任务详情
（文件名 tasks_menu.py 避免与 src/tasks 包冲突）
"""
import re
import logging
from src.notification.base import CommandResult

logger = logging.getLogger(__name__)


class TasksMenuMixin:
    """处理 /tasks 命令及任务详情回调的所有方法"""

    async def cmd_list_tasks(self, args: str, user_id: str, channel, **kw) -> CommandResult:
        return await self._build_tasks_result()

    async def _build_tasks_result(self, edit_message_id: int = None) -> CommandResult:
        if not self.scheduler_manager:
            return CommandResult(success=False, text="调度服务未就绪。")
        try:
            tasks = await self.scheduler_manager.get_all_tasks()
            if not tasks:
                return CommandResult(text="📋 当前没有定时任务。")
            lines = ["📋 定时任务列表:\n"]
            for t in tasks:
                status = "✅" if t.get("isEnabled") else "⏸️"
                name = t.get("name", "未知")
                cron = t.get("cron", "")
                lines.append(f"{status} {name} ({cron})")
            return CommandResult(
                text="\n".join(lines),
                reply_markup=[[{"text": "🔄 刷新", "callback_data": "tasks_refresh"}]],
                edit_message_id=edit_message_id,
            )
        except Exception as e:
            logger.error(f"获取任务列表失败: {e}", exc_info=True)
            return CommandResult(success=False, text=f"获取任务列表出错: {e}")

    async def cb_tasks_refresh(self, params, user_id, channel, **kw):
        return await self._build_tasks_result(edit_message_id=kw.get("message_id"))

    async def cb_noop(self, params, user_id, channel, **kw):
        return CommandResult(text="", answer_callback_text="")

    async def cb_help_cmd(self, params, user_id, channel, **kw):
        """帮助页内联按钮 — 点击后触发对应命令"""
        cmd = params[0] if params else ""
        handler_map = {
            "search": self.cmd_search,
            "auto": self.cmd_auto,
            "url": self.cmd_url,
            "refresh": self.cmd_refresh,
            "tokens": self.cmd_list_tokens,
            "tasks": self.cmd_list_tasks,
            "cache": self.cmd_cache,
        }
        handler = handler_map.get(cmd)
        if not handler:
            return CommandResult(text="", answer_callback_text="未知命令")
        self.clear_conversation(user_id)
        result = await handler("", user_id, channel, **kw)
        result.answer_callback_text = ""
        result.edit_message_id = kw.get("message_id")
        return result

    async def cb_task_detail(self, params, user_id, channel, **kw):
        """查看单个任务的实时状态，支持追踪子任务链"""
        task_id = params[0] if params else ""
        if not task_id:
            return CommandResult(text="", answer_callback_text="缺少任务ID")
        try:
            from src.db import crud
            async with self._session_factory() as session:
                detail = await crud.get_task_details_from_history(session, task_id)
            if not detail:
                return CommandResult(text="", answer_callback_text="任务不存在或已被清理")

            status = detail.get("status", "未知")
            progress = detail.get("progress", 0)
            title = detail.get("title", "")
            desc = detail.get("description", "")
            status_icon = {
                "排队中": "⏳", "运行中": "▶️", "已完成": "✅",
                "失败": "❌", "已暂停": "⏸️",
            }.get(status, "❓")

            lines = [
                f"{status_icon} 调度任务: {title}",
                f"状态: {status} | 进度: {progress}%",
            ]
            if desc:
                short_desc = desc[:200] + "..." if len(desc) > 200 else desc
                lines.append(f"详情: {short_desc}")

            buttons = [[{"text": "🔄 刷新状态", "callback_data": f"task_detail:{task_id}"}]]

            # 追踪子任务链：从描述中解析 "执行任务ID: xxx"
            exec_task_id = None
            if desc:
                m = re.search(r'执行任务ID:\s*([a-f0-9\-]+)', desc)
                if m:
                    exec_task_id = m.group(1)

            if exec_task_id:
                async with self._session_factory() as session:
                    exec_detail = await crud.get_task_details_from_history(session, exec_task_id)
                if exec_detail:
                    exec_status = exec_detail.get("status", "未知")
                    exec_progress = exec_detail.get("progress", 0)
                    exec_title = exec_detail.get("title", "")
                    exec_desc = exec_detail.get("description", "")
                    exec_icon = {
                        "排队中": "⏳", "运行中": "▶️", "已完成": "✅",
                        "失败": "❌", "已暂停": "⏸️",
                    }.get(exec_status, "❓")
                    lines.append("")
                    lines.append(f"{exec_icon} 执行任务: {exec_title}")
                    lines.append(f"状态: {exec_status} | 进度: {exec_progress}%")
                    if exec_desc:
                        short_exec = exec_desc[:200] + "..." if len(exec_desc) > 200 else exec_desc
                        lines.append(f"详情: {short_exec}")
                    buttons.append([{"text": "📦 查看执行任务", "callback_data": f"task_detail:{exec_task_id}"}])

            return CommandResult(
                text="\n".join(lines),
                reply_markup=buttons,
                edit_message_id=kw.get("message_id"),
            )
        except Exception as e:
            logger.error(f"查询任务详情失败: {e}", exc_info=True)
            return CommandResult(text="", answer_callback_text=f"查询失败: {e}")

