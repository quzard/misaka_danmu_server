"""
NotificationService — 通知系统的通用内部 API

核心框架：命令路由 / 回调路由 / 对话状态管理 / 事件分发。
所有菜单业务逻辑已拆分到 src/notification/menus/ 目录下，
通过 Mixin 多继承引入。
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from src.notification.base import CommandResult, ConversationState, ChannelCapabilities
from src.notification.menus import (
    ImportBaseMixin,
    SearchMenuMixin,
    AutoMenuMixin,
    UrlMenuMixin,
    LibraryMenuMixin,
    TokensMenuMixin,
    TasksMenuMixin,
    CacheMenuMixin,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 5


class NotificationService(
    ImportBaseMixin,
    SearchMenuMixin,
    AutoMenuMixin,
    UrlMenuMixin,
    LibraryMenuMixin,
    TokensMenuMixin,
    TasksMenuMixin,
    CacheMenuMixin,
):
    """通知系统核心服务：命令处理 / 回调处理 / 对话状态 / 事件分发"""

    def __init__(self, session_factory: Callable):
        self._session_factory = session_factory
        # 以下依赖在 main.py 中通过 set_dependencies 注入
        self.scraper_manager = None
        self.metadata_manager = None
        self.task_manager = None
        self.scheduler_manager = None
        self.config_manager = None
        self.rate_limiter = None
        self.title_recognition_manager = None
        self.ai_matcher_manager = None
        # 渠道管理器引用（由 NotificationManager 设置）
        self.notification_manager = None
        # 对话状态: user_id -> ConversationState
        self._conversations: Dict[str, ConversationState] = {}

    def set_dependencies(self, **kwargs):
        """注入系统依赖"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    # ═══════════════════════════════════════════
    # 菜单命令定义
    # ═══════════════════════════════════════════

    # 命令定义：{"/command": "描述"}
    MENU_COMMANDS = {
        "/search": "搜索弹幕源",
        "/auto": "自动导入（多平台）",
        "/url": "从URL导入弹幕",
        "/refresh": "弹幕库管理",
        "/tokens": "Token管理",
        "/tasks": "定时任务列表",
        "/cache": "清除缓存",
        "/cancel": "取消当前操作",
        "/help": "显示帮助",
    }

    def get_menu_commands(self) -> Dict[str, str]:
        """返回菜单命令定义，供渠道层注册 BotCommand 等菜单"""
        return self.MENU_COMMANDS

    # ═══════════════════════════════════════════
    # 能力感知辅助
    # ═══════════════════════════════════════════

    @staticmethod
    def _buttons_to_text_fallback(text: str, buttons: List[List[Dict[str, str]]]) -> str:
        """将按钮列表降级为纯文本附加到消息末尾（用于不支持按钮的渠道）"""
        if not buttons:
            return text
        lines = [text, "", "可用操作："]
        idx = 1
        for row in buttons:
            for btn in row:
                btn_text = btn.get("text", "")
                callback = btn.get("callback_data", "")
                if callback:
                    lines.append(f"  {idx}. {btn_text}")
                    idx += 1
        return "\n".join(lines)

    # ═══════════════════════════════════════════
    # 对话状态管理
    # ═══════════════════════════════════════════

    def get_conversation(self, user_id: str) -> Optional[ConversationState]:
        """获取用户当前对话状态（自动清理过期状态）"""
        conv = self._conversations.get(user_id)
        if conv and conv.is_expired:
            del self._conversations[user_id]
            return None
        return conv

    def set_conversation(self, user_id: str, state: str, data: dict = None,
                         message_id: int = None, chat_id: int = None):
        """设置用户对话状态"""
        self._conversations[user_id] = ConversationState(
            state=state,
            data=data or {},
            message_id=message_id,
            chat_id=chat_id,
        )

    def clear_conversation(self, user_id: str):
        """清除用户对话状态"""
        self._conversations.pop(user_id, None)

    def update_conversation_message_id(self, user_id: str, message_id: int):
        """更新对话关联的消息ID（由渠道层回写）"""
        conv = self._conversations.get(user_id)
        if conv:
            conv.message_id = message_id

    # ═══════════════════════════════════════════
    # 入站：命令处理（用户 → 系统）
    # ═══════════════════════════════════════════

    async def handle_command(self, command: str, user_id: str, args: str,
                             channel, **kwargs) -> CommandResult:
        """统一命令分发"""
        # 新命令进来时清除旧对话状态
        self.clear_conversation(user_id)
        handler_map = {
            "start": self.cmd_start,
            "help": self.cmd_help,
            "search": self.cmd_search,
            "tasks": self.cmd_list_tasks,
            "tokens": self.cmd_list_tokens,
            "auto": self.cmd_auto,
            "refresh": self.cmd_refresh,
            "url": self.cmd_url,
            "cache": self.cmd_cache,
        }
        handler = handler_map.get(command)
        if not handler:
            return CommandResult(success=False, text=f"未知命令: /{command}\n使用 /help 查看可用命令。")
        try:
            return await handler(args, user_id, channel, **kwargs)
        except Exception as e:
            logger.error(f"命令 /{command} 执行失败: {e}", exc_info=True)
            return CommandResult(success=False, text=f"命令执行出错: {e}")

    async def handle_callback(self, callback_data: str, user_id: str,
                               channel, **kwargs) -> CommandResult:
        """统一回调分发 — callback_data 格式: action:param1:param2:..."""
        parts = callback_data.split(":")
        action = parts[0] if parts else ""
        params = parts[1:] if len(parts) > 1 else []
        callback_map = {
            # tasks
            "tasks_refresh": self.cb_tasks_refresh,
            # tokens
            "tokens_refresh": self.cb_tokens_refresh,
            "token_toggle": self.cb_token_toggle,
            "token_delete": self.cb_token_delete,
            "token_confirm_delete": self.cb_token_confirm_delete,
            "token_cancel_delete": self.cb_token_cancel_delete,
            "token_add": self.cb_token_add,
            "token_validity": self.cb_token_validity,
            # search
            "search_page": self.cb_search_page,
            "search_import": self.cb_search_import,
            "search_episodes": self.cb_search_episodes,
            "ep_page": self.cb_episode_page,
            # search → edit import
            "search_edit": self.cb_search_edit,
            "edit_ep_toggle": self.cb_edit_ep_toggle,
            "edit_ep_page": self.cb_edit_ep_page,
            "edit_ep_all": self.cb_edit_ep_all,
            "edit_ep_none": self.cb_edit_ep_none,
            "edit_type": self.cb_edit_type,
            "edit_season": self.cb_edit_season,
            "edit_title": self.cb_edit_title,
            "edit_confirm": self.cb_edit_confirm,
            "edit_back": self.cb_edit_back,
            # auto
            "auto_type": self.cb_auto_type,
            "auto_media_type": self.cb_auto_media_type,
            "auto_season": self.cb_auto_season,
            # refresh / library
            "refresh_anime": self.cb_refresh_anime,
            "refresh_source": self.cb_refresh_source,
            "refresh_ep_page": self.cb_refresh_ep_page,
            "refresh_do": self.cb_refresh_do,
            "lib_page": self.cb_lib_page,
            # delete source
            "delete_source_do": self.cb_delete_source_do,
            "delete_source_confirm": self.cb_delete_source_confirm,
            # delete episodes
            "delete_ep_all": self.cb_delete_ep_all,
            "delete_ep_range": self.cb_delete_ep_range,
            # task detail
            "task_detail": self.cb_task_detail,
            # help inline buttons
            "help_cmd": self.cb_help_cmd,
            # noop
            "noop": self.cb_noop,
        }
        handler = callback_map.get(action)
        if not handler:
            return CommandResult(text="", answer_callback_text="未知操作")
        try:
            return await handler(params, user_id, channel, **kwargs)
        except Exception as e:
            logger.error(f"回调 {action} 执行失败: {e}", exc_info=True)
            return CommandResult(text="", answer_callback_text=f"操作失败: {e}")

    async def handle_text_input(self, text: str, user_id: str,
                                 channel, **kwargs) -> Optional[CommandResult]:
        """处理对话状态机中的文本输入"""
        conv = self.get_conversation(user_id)
        if not conv:
            return None  # 没有活跃对话，忽略
        state = conv.state
        text_handler_map = {
            "token_name_input": self._text_token_name,
            "auto_keyword_input": self._text_auto_keyword,
            "auto_id_input": self._text_auto_id,
            "url_input": self._text_url_input,
            "refresh_keyword_input": self._text_refresh_keyword,
            "search_episode_range": self._text_search_episode_range,
            "refresh_episode_range": self._text_refresh_episode_range,
            "delete_episode_range": self._text_delete_episode_range,
            "edit_title_input": self._text_edit_title,
        }
        handler = text_handler_map.get(state)
        if not handler:
            return None
        try:
            return await handler(text, user_id, channel, **kwargs)
        except Exception as e:
            logger.error(f"文本处理 {state} 失败: {e}", exc_info=True)
            self.clear_conversation(user_id)
            return CommandResult(text=f"处理出错: {e}")

    async def handle_cancel(self, user_id: str) -> CommandResult:
        """取消当前对话"""
        conv = self.get_conversation(user_id)
        self.clear_conversation(user_id)
        if conv:
            return CommandResult(text="✅ 已取消当前操作。")
        return CommandResult(text="当前没有进行中的操作。")

    # ═══════════════════════════════════════════
    # 出站：通知发送（系统 → 用户）
    # ═══════════════════════════════════════════

    async def emit_event(self, event_type: str, data: Dict[str, Any]):
        """向所有订阅了该事件的渠道发送通知"""
        if not self.notification_manager:
            return
        channels = self.notification_manager.get_all_channels()
        for ch_id, channel_instance in channels.items():
            try:
                events_cfg = channel_instance.config.get("__events_config", {})
                if not events_cfg.get(event_type, False):
                    continue
                title, text = self._format_event_message(event_type, data)
                image_url: str = data.get("image_url", "") or ""
                await channel_instance.send_message(title=title, text=text, image=image_url)
            except Exception as e:
                logger.error(f"渠道 {ch_id} 发送事件 {event_type} 失败: {e}")

    # ═══════════════════════════════════════════
    # 事件消息格式化
    # ═══════════════════════════════════════════

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
    }

    def _format_event_message(self, event_type: str, data: Dict[str, Any]) -> tuple:
        """根据事件类型格式化通知消息，返回 (title, text)"""
        label_info = self.EVENT_LABELS.get(event_type)
        if not label_info:
            return (event_type, data.get("text", ""))

        label, is_success = label_info
        task_title = data.get("task_title", "")
        message = data.get("message", "")

        if event_type == "system_start":
            return (label, "弹幕服务器已启动完成 ✓")

        if event_type == "webhook_triggered":
            anime = data.get("anime_title", "未知")
            source = data.get("webhook_source", "")
            delayed = data.get("delayed", False)
            delay_hours = data.get("delay_hours", "")
            wh_lines = [f"📺 媒体：{anime}", f"📡 来源：{source}"]
            if delayed:
                wh_lines.append(f"⏳ 延迟入库：{delay_hours} 小时后执行")
            else:
                wh_lines.append("⚡ 即时导入")
            return (label, "\n".join(wh_lines))

        # 通用任务类消息
        icon = "✅" if is_success else "❌"
        search_term = data.get("search_term", "")
        search_type = data.get("search_type", "")
        season = data.get("season")
        episode = data.get("episode")
        task_id = data.get("task_id", "")
        anime_title = data.get("anime_title", "")
        ep_count = data.get("episode_count")
        webhook_source = data.get("webhook_source", "")
        lines = []
        if task_title:
            lines.append(f"📋 任务：{task_title}")
        if anime_title and anime_title != task_title:
            lines.append(f"📺 媒体：{anime_title}")
        if search_term:
            type_label = {"keyword": "关键词", "tmdb": "TMDB", "tvdb": "TVDB",
                          "douban": "豆瓣", "imdb": "IMDB", "bangumi": "Bangumi"}.get(search_type, search_type)
            suffix = f"（{type_label}）" if type_label else ""
            lines.append(f"🔍 搜索词：{search_term}{suffix}")
        if season is not None:
            ep_str = f"  E{episode}" if episode else ""
            lines.append(f"📅 季集：第 {season} 季{ep_str}")
        if ep_count is not None:
            lines.append(f"📝 导入集数：{ep_count} 集")
        if webhook_source:
            lines.append(f"📡 来源：{webhook_source}")
        if message:
            msg_prefix = "💬 结果" if is_success else "⚠️ 错误"
            msg_short = message if len(message) <= 200 else message[:197] + "..."
            lines.append(f"{msg_prefix}：{msg_short}")
        if task_id:
            lines.append(f"🆔 任务ID：`{task_id}`")
        return (f"{icon} {label}", "\n".join(lines) if lines else label)

    # ═══════════════════════════════════════════
    # 命令实现
    # ═══════════════════════════════════════════

    HELP_TEXT = (
        "📖 *命令列表:*\n\n"
        "🔍 /search <关键词> - 搜索弹幕源\n"
        "  _支持指定季集，如: /search 刀剑神域 S01E10_\n"
        "🔄 /auto - 自动导入（多平台）\n"
        "🔗 /url - 从URL导入弹幕\n"
        "♻️ /refresh - 弹幕库管理\n"
        "🔑 /tokens - Token管理\n"
        "📋 /tasks - 定时任务列表\n"
        "🗑️ /cache - 清除缓存\n"
        "❌ /cancel - 取消当前操作\n"
        "📖 /help - 显示此帮助\n\n"
        "💡 点击下方按钮可快速执行命令"
    )

    HELP_BUTTONS = [
        [{"text": "🔍 搜索弹幕", "callback_data": "help_cmd:search"},
         {"text": "🔄 自动导入", "callback_data": "help_cmd:auto"}],
        [{"text": "🔗 URL导入", "callback_data": "help_cmd:url"},
         {"text": "♻️ 弹幕库管理", "callback_data": "help_cmd:refresh"}],
        [{"text": "🔑 Token管理", "callback_data": "help_cmd:tokens"},
         {"text": "📋 任务列表", "callback_data": "help_cmd:tasks"}],
        [{"text": "🗑️ 清除缓存", "callback_data": "help_cmd:cache"}],
    ]

    async def cmd_start(self, args: str, user_id: str, channel, **kw) -> CommandResult:
        return CommandResult(
            text=f"👋 欢迎使用弹幕服务器通知机器人！\n\n{self.HELP_TEXT}",
            reply_markup=self.HELP_BUTTONS,
            parse_mode="Markdown",
        )

    async def cmd_help(self, args: str, user_id: str, channel, **kw) -> CommandResult:
        return CommandResult(
            text=self.HELP_TEXT,
            reply_markup=self.HELP_BUTTONS,
            parse_mode="Markdown",
        )

    # ── /tasks ──

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
        msg_id = kw.get("message_id")
        return await self._build_tasks_result(edit_message_id=msg_id)

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

    # ═══════════════════════════════════════════
    # 以下方法均已迁移到 src/notification/menus/ 下的 Mixin，
    # 此处保留注释占位，便于 IDE 识别继承关系
    # ═══════════════════════════════════════════
    # （所有 cmd_*/cb_*/_{text/do/build/submit}* 方法已通过 Mixin 继承）
