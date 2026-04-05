"""
事件消息格式化 Mixin — EVENT_LABELS / _format_event_message / _format_task_progress_message
从 notification_service.py 中拆分，集中管理所有通知消息模板。
"""
from typing import Any, Dict


class MessagesMixin:
    """事件消息格式化：将事件类型和数据转换为 (title, text) 元组"""

    EVENT_LABELS = {
        "import_success": ("导入成功", True),
        "import_failed": ("导入失败", False),
        "refresh_success": ("刷新成功", True),
        "refresh_failed": ("刷新失败", False),
        "auto_import_success": ("自动导入成功", True),
        "auto_import_failed": ("自动导入失败", False),
        "webhook_triggered": ("Webhook 触发", True),
        "webhook_import_success": ("Webhook 导入成功", True),
        "webhook_import_failed": ("Webhook 导入失败", False),
        "incremental_refresh_success": ("追更刷新成功", True),
        "incremental_refresh_failed": ("追更刷新失败", False),
        "media_scan_complete": ("媒体库扫描完成", True),
        "scheduled_task_complete": ("定时任务完成", True),
        "scheduled_task_failed": ("定时任务失败", False),
        "system_start": ("系统启动", True),
        # 后备下载任务（旧，保留兼容）
        "download_fallback_success": ("后备弹幕下载完成", True),
        "download_fallback_failed": ("后备弹幕下载失败", False),
        # 后备任务（拆分三种子类型）
        "fallback_search_success": ("后备搜索完成", True),
        "fallback_search_failed": ("后备搜索失败", False),
        "predownload_success": ("预下载完成", True),
        "predownload_failed": ("预下载失败", False),
        "match_fallback_success": ("匹配后备完成", True),
        "match_fallback_failed": ("匹配后备失败", False),
    }

    def _format_event_message(self, event_type: str, data: Dict[str, Any]) -> tuple:
        """根据事件类型格式化通知消息，返回 (title, text)"""
        label_info = self.EVENT_LABELS.get(event_type)
        if not label_info:
            return (event_type, data.get("text", ""))

        label, is_success = label_info
        message     = data.get("message", "")
        anime_title = data.get("anime_title", "")
        season      = data.get("season")
        episode     = data.get("episode")
        source      = data.get("source", "")
        webhook_src = data.get("webhook_source", "")
        task_id     = data.get("task_id", "")
        task_title  = data.get("task_title", "")
        tmdb_id     = data.get("tmdb_id", "")
        media_type  = data.get("media_type", "")
        finished_at = data.get("finished_at", "")
        icon        = "✅" if is_success else "❌"
        status_str  = "处理完成" if is_success else "处理失败"
        msg_short   = (message[:300] + "…") if len(message) > 300 else message

        # ── 系统启动 ──────────────────────────────────────
        if event_type == "system_start":
            return (label, "弹幕服务器已启动完成 ✓")

        # ── Webhook 触发 ───────────────────────────────────
        if event_type == "webhook_triggered":
            anime  = anime_title or "未知"
            source = webhook_src
            delayed     = data.get("delayed", False)
            delay_hours = data.get("delay_hours", "")
            lines = [
                "📺 *媒体信息*",
                f"• 名称: {anime}",
                f"• 来源: {source}",
                f"• 操作: {'⏳ 延迟入库 ' + str(delay_hours) + ' 小时后执行' if delayed else '⚡ 即时导入'}",
            ]
            return (label, "\n".join(lines))

        # ── 后备弹幕下载（旧，保留兼容） ────────────────────────
        if event_type in ("download_fallback_success", "download_fallback_failed"):
            token_name = data.get("token_name", "")
            lines = [
                "📺 *媒体信息*",
                f"• 任务: {task_title}" if task_title else "",
                f"• 调用者: {token_name}" if token_name else "",
                "",
                "⚙️ *任务执行信息*",
                f"• TaskID: `{task_id}`" if task_id else "",
                f"  └─ 状态: {icon} {'已完成 (100%)' if is_success else '失败'}",
                f"  └─ 📋 {msg_short}" if msg_short else "",
                f"• 时间: {finished_at}" if finished_at else "",
            ]
            return (f"{icon} 后备任务{'完成' if is_success else '失败'}", "\n".join(l for l in lines if l))

        # ── 后备搜索 ─────────────────────────────────────────
        if event_type in ("fallback_search_success", "fallback_search_failed"):
            token_name = data.get("token_name", "")
            lines = [
                "📺 *媒体信息*",
                f"• 任务: {task_title}" if task_title else "",
                f"• 调用者: {token_name}" if token_name else "",
                "",
                "⚙️ *执行结果*",
                f"• TaskID: `{task_id}`" if task_id else "",
                f"  └─ 状态: {icon} {'已完成' if is_success else '失败'}",
                f"  └─ 📋 {msg_short}" if msg_short else "",
                f"• 时间: {finished_at}" if finished_at else "",
            ]
            return (f"{icon} 后备任务{'完成' if is_success else '失败'}", "\n".join(l for l in lines if l))

        # ── 预下载弹幕 ───────────────────────────────────────
        if event_type in ("predownload_success", "predownload_failed"):
            lines = [
                "📺 *媒体信息*",
                f"• 任务: {task_title}" if task_title else "",
                "",
                "⚙️ *执行结果*",
                f"• 状态: {icon} {'处理完成' if is_success else '处理失败'}",
                f"  └─ 📋 {msg_short}" if msg_short else "",
                f"• 时间: {finished_at}" if finished_at else "",
            ]
            return (f"{icon} 后备任务{'完成' if is_success else '失败'}", "\n".join(l for l in lines if l))

        # ── 匹配后备 ─────────────────────────────────────────
        if event_type in ("match_fallback_success", "match_fallback_failed"):
            # 从 task_parameters 读取匹配详情
            task_params = data.get("task_parameters", {})
            provider = task_params.get("provider", "")
            final_title = task_params.get("final_title", "")
            final_season = task_params.get("final_season")
            episode_number = task_params.get("episode_number")
            is_movie = task_params.get("is_movie", False)

            lines = [
                "📺 *媒体信息*",
                f"• 任务: {task_title}" if task_title else "",
            ]

            # 显示匹配详情
            if provider:
                lines.append(f"• 弹幕源: {provider}")
            if final_title:
                lines.append(f"• 番剧: {final_title}")
            if final_season is not None and episode_number is not None:
                if is_movie:
                    lines.append(f"• 类型: 电影")
                else:
                    lines.append(f"• 季集: S{final_season:02d}E{episode_number:02d}")

            lines.extend([
                "",
                "⚙️ *执行结果*",
                f"• 状态: {icon} {'处理完成' if is_success else '处理失败'}",
                f"  └─ 📋 {msg_short}" if msg_short else "",
                f"• 时间: {finished_at}" if finished_at else "",
            ])
            return (f"{icon} 后备任务{'完成' if is_success else '失败'}", "\n".join(l for l in lines if l))

        # ── 定时任务 ──────────────────────────────────────
        if event_type in ("scheduled_task_complete", "scheduled_task_failed"):
            if msg_short:
                msg_lines = [l for l in msg_short.splitlines() if l.strip()]
                if len(msg_lines) <= 1:
                    detail_lines = [f"  └─ 📋 {msg_short}"]
                else:
                    detail_lines = [f"  ├─ 📋 {l}" for l in msg_lines[:-1]]
                    detail_lines.append(f"  └─ 📋 {msg_lines[-1]}")
            else:
                detail_lines = []
            lines = [
                "⚙️ *执行结果*",
                f"• 任务: {task_title}" if task_title else "",
                f"• 状态: {icon} {'已完成' if is_success else '执行失败'}",
                *detail_lines,
                f"• 时间: {finished_at}" if finished_at else "",
                f"• TaskID: `{task_id[:8]}…`" if task_id else "",
            ]
            return (f"{icon} {label}", "\n".join(l for l in lines if l))

        # ── 刷新类 ────────────────────────────────────────
        if "refresh" in event_type:
            s_str = f"S{int(season):02d}" if season is not None else ""
            e_str = f"E{int(episode):02d}" if episode is not None else ""
            lines = [
                "📺 *媒体信息*",
                f"• 名称: {anime_title}" if anime_title else "",
                f"• 季集: {s_str}{e_str}" if s_str else "",
                f"• 操作: 刷新弹幕",
                f"• 状态: {icon} {status_str}",
                f"• 信息: {msg_short}" if msg_short else "",
                f"• 时间: {finished_at}" if finished_at else "",
            ]
            return (f"{icon} {label}", "\n".join(l for l in lines if l))

        # ── 导入 / 自动导入 / Webhook 导入 ────────────────
        s_str = f"S{int(season):02d}" if season is not None else ""
        e_str = f"E{int(episode):02d}" if episode is not None else ""
        tmdb_str = f"TMDB:{tmdb_id}" if tmdb_id else ""
        type_str = media_type or ""
        lines = [
            "📺 *媒体信息*",
            f"• 名称: {anime_title}" if anime_title else "",
            f"• 季集: {s_str}{e_str}" if s_str or e_str else "",
            f"• 类型: {type_str}" if type_str else "",
            f"• 来源: {source}" if source else "",
            f"• ID: {tmdb_str}" if tmdb_str else "",
            "",
            "⚙️ *任务执行信息*",
            f"• TaskID: `{task_id}`" if task_id else "",
            f"  └─ 状态: {icon} {status_str}",
            f"  └─ 📋 {msg_short}" if msg_short else "",
            f"• 时间: {finished_at}" if finished_at else "",
        ]
        return (f"{icon} {label}", "\n".join(l for l in lines if l))

    def _format_task_progress_message(self, task_title: str, progress: int, description: str) -> tuple:
        """格式化任务进度消息，返回 (title, text)，适用于后备和普通下载任务"""
        filled = int(progress / 10)
        bar = "█" * filled + "░" * (10 - filled)
        # 转义 Markdown 特殊字符，避免 Telegram parse_mode="Markdown" 解析失败
        safe_title = self._escape_markdown(task_title) if task_title else ""
        safe_desc = self._escape_markdown(description) if description else ""
        lines = ["⚙️ *执行进度*", ""]
        if safe_title:
            lines.append(f"• 任务: {safe_title}")
        lines.append(f"• 进度: `[{bar}]` {progress}%")
        if safe_desc:
            lines.append(f"• 状态: {safe_desc}")
        return ("⬇️ 任务进行中", "\n".join(lines))

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """转义 Telegram Markdown V1 中的特殊字符: _ * ` ["""
        for ch in ('_', '*', '`', '['):
            text = text.replace(ch, f'\\{ch}')
        return text

