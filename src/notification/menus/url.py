"""
/url 菜单 Mixin — 从 URL 导入弹幕
"""
import logging
from src.notification.base import CommandResult

logger = logging.getLogger(__name__)


class UrlMenuMixin:
    """处理 /url 命令的所有 cmd_/_text_/_process_ 方法"""

    async def cmd_url(self, args: str, user_id: str, channel, **kw) -> CommandResult:
        """从URL导入弹幕"""
        if args and args.strip():
            return await self._process_url_input(args.strip(), user_id, **kw)
        self.set_conversation(user_id, "url_input", {},
                              chat_id=kw.get("chat_id"))
        return CommandResult(text="🔗 请输入视频页面URL：")

    async def _text_url_input(self, text: str, user_id: str, channel, **kw):
        """URL输入 → 解析并导入"""
        self.clear_conversation(user_id)
        return await self._process_url_input(text.strip(), user_id, **kw)

    async def _process_url_input(self, url: str, user_id: str, **kw) -> CommandResult:
        """解析URL并尝试匹配弹幕源"""
        if not self.scraper_manager:
            return CommandResult(success=False, text="搜索服务未就绪。")
        try:
            scraper = self.scraper_manager.get_scraper_by_domain(url)
            if not scraper:
                return CommandResult(text="❌ 无法识别该URL的平台。\n支持的平台取决于已启用的弹幕源。")
            info = await scraper.get_info_from_url(url)
            if not info:
                return CommandResult(text="❌ 无法从该URL解析出媒体信息。")
            platform = getattr(scraper, 'provider_name', '未知')
            title = info.get("title", "未知") if isinstance(info, dict) else getattr(info, "title", "未知")
            return CommandResult(
                text=f"🔗 URL解析成功\n平台: {platform}\n标题: {title}\n\n正在提交导入任务...",
            )
        except Exception as e:
            logger.error(f"URL解析失败: {e}", exc_info=True)
            return CommandResult(text=f"❌ URL解析失败: {e}")

