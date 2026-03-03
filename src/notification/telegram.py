"""
Telegram 通知渠道实现
使用 pyTelegramBotAPI (telebot) 库，支持 Polling 和 Webhook 两种模式。
支持 InlineKeyboard、CallbackQuery、多步对话等交互能力。
"""

import asyncio
import json
import logging
import threading
from typing import Any, Dict, List, Optional

from src.notification.base import (
    BaseNotificationChannel, CommandResult,
    ChannelCapability, ChannelCapabilities,
)

logger = logging.getLogger(__name__)
bot_raw_logger = logging.getLogger("bot_raw")


def _get_telebot():
    """延迟导入 telebot，避免未安装时影响启动"""
    try:
        import telebot
        return telebot
    except ImportError:
        raise ImportError("请安装 pyTelegramBotAPI: pip install pyTelegramBotAPI")


class TelegramChannel(BaseNotificationChannel):
    """Telegram 通知渠道"""

    channel_type = "telegram"
    display_name = "Telegram"

    # Telegram 渠道能力配置
    _CAPABILITIES = ChannelCapabilities(
        capabilities={
            ChannelCapability.INLINE_BUTTONS,
            ChannelCapability.MENU_COMMANDS,
            ChannelCapability.MESSAGE_EDITING,
            ChannelCapability.MESSAGE_DELETION,
            ChannelCapability.CALLBACK_QUERIES,
            ChannelCapability.RICH_TEXT,
            ChannelCapability.IMAGES,
            ChannelCapability.LINKS,
        },
        max_buttons_per_row=4,
        max_button_rows=10,
        max_button_text_length=30,
    )

    def __init__(self, channel_id: int, name: str, config: dict, notification_service):
        super().__init__(channel_id, name, config, notification_service)
        self._bot = None
        self._polling_thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # 主事件循环引用

    def get_capabilities(self) -> ChannelCapabilities:
        """返回 Telegram 渠道能力"""
        return self._CAPABILITIES

    @staticmethod
    def get_config_schema() -> list:
        return [
            {
                "key": "bot_token",
                "label": "Bot Token",
                "type": "password",
                "description": "从 @BotFather 获取的 Bot Token",
                "placeholder": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
                "required": True,
            },
            {
                "key": "chat_id",
                "label": "Chat ID",
                "type": "string",
                "description": "默认消息接收者的 Chat ID，用于接收系统通知",
                "placeholder": "123456789",
            },
            {
                "key": "admin_ids",
                "label": "管理员用户ID",
                "type": "string",
                "description": "拥有管理权限的用户ID，多个用逗号分隔",
                "placeholder": "123456789,987654321",
            },
            {
                "key": "allowed_ids",
                "label": "允许的用户ID",
                "type": "string",
                "description": "允许使用 Bot 交互的用户ID，多个用逗号分隔。留空则仅管理员可用",
                "placeholder": "",
            },
            {
                "key": "mode",
                "label": "交互模式",
                "type": "switch",
                "description": "消息接收方式",
                "switchLabels": {"checked": "Webhook", "unchecked": "轮询"},
                "switchValues": {"checked": "webhook", "unchecked": "polling"},
                "default": "polling",
            },
            {
                "key": "webhook_base_url",
                "label": "外部访问地址",
                "type": "string",
                "description": "你的服务器公网地址（如 https://my-domain.com），系统会自动拼接完整回调路径",
                "placeholder": "https://your-domain.com",
                "visibleWhen": {"mode": "webhook"},
            },
            {
                "key": "log_raw",
                "label": "记录原始交互",
                "type": "boolean",
                "description": "启用后，Bot 的所有收发消息将记录到 config/logs/bot_raw.log 文件中，用于调试",
                "default": False,
            },
        ]

    def _is_log_raw(self) -> bool:
        """检查是否启用原始日志"""
        return str(self.config.get("log_raw", "false")).lower() == "true"

    def _log_raw(self, direction: str, data):
        """记录原始交互日志"""
        if self._is_log_raw():
            bot_raw_logger.info(
                f"[TG Bot #{self.channel_id}] {direction}\n"
                f"{json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else data}\n"
                f"{'─' * 60}"
            )

    def _parse_id_list(self, key: str) -> set:
        raw = self.config.get(key, "")
        if not raw:
            return set()
        return {s.strip() for s in str(raw).split(",") if s.strip()}

    def _is_allowed(self, user_id: int) -> bool:
        uid = str(user_id)
        admins = self._parse_id_list("admin_ids")
        allowed = self._parse_id_list("allowed_ids")
        if admins and uid in admins:
            return True
        if allowed:
            return uid in allowed
        # 如果没有配置 allowed_ids，则仅管理员可用
        return uid in admins if admins else True

    async def start(self):
        bot_token = self.config.get("bot_token", "")
        if not bot_token:
            self.logger.warning("Bot Token 未配置，跳过启动")
            return

        # 捕获主事件循环引用，供轮询线程中的回调使用
        self._loop = asyncio.get_running_loop()

        telebot = _get_telebot()

        # 配置代理（如果开启了代理开关且有代理 URL）
        if self.proxy_url:
            telebot.apihelper.proxy = {"https": self.proxy_url}
            self.logger.info(f"Telegram Bot 已启用代理: {self.proxy_url}")
        else:
            # 确保清除可能被其他实例设置过的代理
            telebot.apihelper.proxy = None

        self._bot = telebot.TeleBot(bot_token, threaded=False)
        self._register_handlers()

        mode = self.config.get("mode", "polling")
        if mode == "webhook":
            base_url = self.config.get("webhook_base_url", "").rstrip("/")
            if base_url:
                full_url = f"{base_url}/api/ui/notification/channels/{self.channel_id}/webhook"
                try:
                    self._bot.remove_webhook()
                    self._bot.set_webhook(url=full_url)
                    self.logger.info(f"Telegram Webhook 已设置: {full_url}")
                except Exception as e:
                    self.logger.error(f"设置 Webhook 失败: {e}")
            else:
                self.logger.warning("外部访问地址未配置，无法注册 Webhook")
        else:
            self._start_polling()

        self._running = True

        # 注册菜单命令（BotCommand）
        menu_commands = self.service.get_menu_commands()
        if menu_commands:
            self.register_commands(menu_commands)

    def register_commands(self, commands: Dict[str, str]) -> None:
        """注册 Telegram Bot 菜单命令（BotCommand）
        :param commands: {"/command": "描述"} 格式的命令字典
        """
        if not self._bot:
            return
        try:
            telebot = _get_telebot()
            bot_commands = [
                telebot.types.BotCommand(cmd.lstrip('/'), desc)
                for cmd, desc in commands.items()
            ]
            self._bot.delete_my_commands()
            self._bot.set_my_commands(bot_commands)
            self.logger.info(f"已注册 {len(bot_commands)} 个菜单命令")
        except Exception as e:
            self.logger.error(f"注册菜单命令失败: {e}")

    def _register_handlers(self):
        """注册消息处理器（命令 + 回调查询 + 对话文本）"""
        bot = self._bot

        # ── 命令处理 ──
        @bot.message_handler(commands=[
            'start', 'help', 'search', 'tasks', 'tokens',
            'auto', 'refresh', 'url', 'cache', 'cancel'
        ])
        def handle_command(message):
            self._log_raw("⬇ 收到命令", {"from": message.from_user.id, "text": message.text, "chat_id": message.chat.id})
            if not self._is_allowed(message.from_user.id):
                bot.reply_to(message, "⛔ 你没有权限使用此机器人。")
                return
            cmd = message.text.split()[0].lstrip('/').split('@')[0]
            args = message.text[len(message.text.split()[0]):].strip()
            loop = self._get_event_loop()
            if loop is None:
                bot.reply_to(message, "⚠️ 服务正在启动或关闭中，请稍后再试。")
                return
            asyncio.run_coroutine_threadsafe(
                self._handle_async_command(cmd, message, args), loop
            )

        # ── InlineKeyboard 回调查询处理 ──
        @bot.callback_query_handler(func=lambda call: True)
        def handle_callback_query(call):
            self._log_raw("⬇ 收到回调", {"from": call.from_user.id, "data": call.data, "chat_id": call.message.chat.id if call.message else None})
            if not self._is_allowed(call.from_user.id):
                bot.answer_callback_query(call.id, "⛔ 无权限")
                return
            loop = self._get_event_loop()
            if loop is None:
                bot.answer_callback_query(call.id, "⚠️ 服务不可用")
                return
            asyncio.run_coroutine_threadsafe(
                self._handle_async_callback(call), loop
            )

        # ── 普通文本消息处理（用于对话状态机） ──
        @bot.message_handler(func=lambda m: True, content_types=['text'])
        def handle_text_message(message):
            self._log_raw("⬇ 收到文本", {"from": message.from_user.id, "text": message.text, "chat_id": message.chat.id})
            if not self._is_allowed(message.from_user.id):
                return
            loop = self._get_event_loop()
            if loop is None:
                return
            asyncio.run_coroutine_threadsafe(
                self._handle_async_text(message), loop
            )



    def _get_event_loop(self):
        """获取主事件循环（使用 start() 时捕获的引用）"""
        if self._loop and self._loop.is_running():
            return self._loop
        self.logger.warning("主事件循环不可用，命令将无法执行")
        return None

    async def _handle_async_command(self, cmd: str, message, args: str):
        """异步处理命令 — 调用服务层并渲染结果"""
        user_id = str(message.from_user.id)
        chat_id = message.chat.id
        # cancel 命令直接清除对话状态
        if cmd == "cancel":
            result = await self.service.handle_cancel(user_id)
        else:
            result: CommandResult = await self.service.handle_command(
                cmd, user_id, args, self, chat_id=chat_id
            )
        self._render_result(result, chat_id, reply_to_message_id=message.message_id)

    async def _handle_async_callback(self, call):
        """异步处理 InlineKeyboard 回调"""
        user_id = str(call.from_user.id)
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        callback_data = call.data or ""
        result: CommandResult = await self.service.handle_callback(
            callback_data, user_id, self, chat_id=chat_id, message_id=message_id
        )
        # 应答回调（消除 TG 客户端的加载动画）
        try:
            self._bot.answer_callback_query(
                call.id, text=result.answer_callback_text or ""
            )
        except Exception:
            pass
        self._render_result(result, chat_id)

    async def _handle_async_text(self, message):
        """异步处理普通文本消息（对话状态机中的用户输入）"""
        user_id = str(message.from_user.id)
        chat_id = message.chat.id
        text = (message.text or "").strip()
        result: CommandResult = await self.service.handle_text_input(
            text, user_id, self, chat_id=chat_id
        )
        if result and result.text:
            self._render_result(result, chat_id, reply_to_message_id=message.message_id)

    # ── 渲染引擎 ──

    def _build_inline_markup(self, buttons: List[List[Dict[str, str]]]):
        """将平台无关的按钮定义转换为 telebot InlineKeyboardMarkup"""
        telebot = _get_telebot()
        markup = telebot.types.InlineKeyboardMarkup()
        for row in buttons:
            btn_row = []
            for btn in row:
                btn_row.append(telebot.types.InlineKeyboardButton(
                    text=btn.get("text", ""),
                    callback_data=btn.get("callback_data", "noop"),
                ))
            markup.row(*btn_row)
        return markup

    def _render_result(self, result: CommandResult, chat_id: int,
                       reply_to_message_id: int = None):
        """根据 CommandResult 渲染消息（发送新消息或编辑已有消息）"""
        if not result or not result.text:
            return
        try:
            markup = None
            if result.reply_markup:
                markup = self._build_inline_markup(result.reply_markup)

            parse_mode = result.parse_mode

            if result.edit_message_id:
                # 编辑已有消息
                self._log_raw("⬆ 编辑消息", {"chat_id": chat_id, "message_id": result.edit_message_id, "text": result.text[:200]})
                self._bot.edit_message_text(
                    text=result.text,
                    chat_id=chat_id,
                    message_id=result.edit_message_id,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                )
            else:
                # 发送新消息
                self._log_raw("⬆ 发送消息", {"chat_id": chat_id, "text": result.text[:200]})
                sent = self._bot.send_message(
                    chat_id,
                    result.text,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                    reply_to_message_id=reply_to_message_id,
                )
                # 如果服务层需要跟踪消息ID（用于后续编辑），回写到对话状态
                if result.next_state and sent:
                    self.service.update_conversation_message_id(
                        str(chat_id), sent.message_id
                    )
        except Exception as e:
            self.logger.error(f"渲染消息失败: {e}")
            # 降级为纯文本
            try:
                self._bot.send_message(chat_id, result.text)
            except Exception:
                pass

    def _start_polling(self):
        """在后台线程中启动长轮询"""
        if self._polling_thread and self._polling_thread.is_alive():
            return

        def polling_worker():
            self.logger.info("Telegram 轮询已启动")
            try:
                self._bot.remove_webhook()
                self._bot.infinity_polling(timeout=30, long_polling_timeout=30)
            except Exception as e:
                if self._running:
                    self.logger.error(f"Telegram 轮询异常退出: {e}")

        self._polling_thread = threading.Thread(
            target=polling_worker,
            name=f"tg-poll-{self.channel_id}",
            daemon=True,
        )
        self._polling_thread.start()

    async def stop(self):
        self._running = False
        self._loop = None  # 清除事件循环引用，防止关闭后仍有 coroutine 被调度
        if self._bot:
            try:
                self._bot.stop_polling()
            except Exception:
                pass
            try:
                self._bot.remove_webhook()
            except Exception:
                pass
        self._bot = None
        self.logger.info("Telegram 渠道已停止")

    async def send_message(self, title: str, text: str, **kwargs):
        if not self._bot:
            return
        chat_id = kwargs.get("chat_id") or self.config.get("chat_id", "")
        if not chat_id:
            self.logger.warning("未配置 Chat ID，无法发送消息")
            return
        content = f"*{title}*\n{text}" if title else text
        try:
            self._bot.send_message(chat_id, content, parse_mode="Markdown")
        except Exception as e:
            self.logger.error(f"发送消息失败: {e}")
            # 降级为纯文本
            try:
                plain = f"{title}\n{text}" if title else text
                self._bot.send_message(chat_id, plain)
            except Exception:
                pass

    async def test_connection(self) -> Dict[str, Any]:
        bot_token = self.config.get("bot_token", "")
        if not bot_token:
            return {"success": False, "message": "Bot Token 未配置"}
        try:
            telebot = _get_telebot()
            # 测试时同样应用代理配置
            if self.proxy_url:
                telebot.apihelper.proxy = {"https": self.proxy_url}
            else:
                telebot.apihelper.proxy = None
            bot = telebot.TeleBot(bot_token, threaded=False)
            info = bot.get_me()
            # 发送测试消息到配置的 chat_id
            chat_id = self.config.get("chat_id", "")
            if chat_id:
                try:
                    bot.send_message(
                        chat_id,
                        f"🔔 测试连接成功！\nBot: @{info.username} ({info.first_name})\n来自 Misaka 弹幕服务器的测试消息。",
                    )
                except Exception as e:
                    self.logger.warning(f"测试消息发送失败: {e}")
            return {
                "success": True,
                "message": f"连接成功！Bot: @{info.username} ({info.first_name})" + (f"，测试消息已发送到 {chat_id}" if chat_id else ""),
                "botInfo": {"username": info.username, "firstName": info.first_name, "id": info.id},
            }
        except Exception as e:
            return {"success": False, "message": f"连接失败: {e}"}

    def process_webhook_update(self, update_json: dict) -> bool:
        """处理 Webhook 推送的 update（由通用 webhook 回调路由调用）"""
        if not self._bot:
            return False
        if self.config.get("mode") != "webhook":
            return False
        telebot = _get_telebot()
        update = telebot.types.Update.de_json(update_json)
        self._bot.process_new_updates([update])
        return True
    