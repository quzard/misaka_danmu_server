"""
/search 菜单 Mixin — 搜索弹幕源、编辑导入流程
"""
import re
import logging
from typing import TYPE_CHECKING

from src.notification.base import CommandResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

PAGE_SIZE = 5


class SearchMenuMixin:
    """处理 /search 命令及编辑导入子流程的所有 cmd_/cb_/_text_ 方法"""

    EDIT_EP_PAGE_SIZE = 8  # 编辑导入分集每页显示数

    # ── 工具 ──

    @staticmethod
    def _parse_season_episode(keyword: str):
        """从关键词中解析 S01E10 / S01 格式，返回 (clean_keyword, season, episode)"""
        m = re.search(r'\bS(\d{1,2})E(\d{1,3})\b', keyword, re.IGNORECASE)
        if m:
            clean = keyword[:m.start()].strip() + ' ' + keyword[m.end():].strip()
            return clean.strip(), int(m.group(1)), str(int(m.group(2)))
        m = re.search(r'\bS(\d{1,2})\b', keyword, re.IGNORECASE)
        if m:
            clean = keyword[:m.start()].strip() + ' ' + keyword[m.end():].strip()
            return clean.strip(), int(m.group(1)), None
        return keyword, None, None

    # ── /search ──

    async def cmd_search(self, args: str, user_id: str, channel, **kw) -> CommandResult:
        if not args or not args.strip():
            return CommandResult(success=False, text=(
                "请提供搜索关键词。\n\n"
                "用法: /search <关键词>\n"
                "示例:\n"
                "  /search 刀剑神域 — 搜索并整季导入\n"
                "  /search 刀剑神域 S01 — 指定第1季导入\n"
                "  /search 刀剑神域 S01E10 — 仅导入第1季第10集"
            ))
        raw_keyword = args.strip()
        keyword, parsed_season, parsed_episode = self._parse_season_episode(raw_keyword)
        if not keyword:
            keyword = raw_keyword
        if not self.scraper_manager:
            return CommandResult(success=False, text="搜索服务未就绪。")
        try:
            async with self._session_factory() as session:
                from src.services.search import unified_search
                results = await unified_search(
                    search_term=keyword,
                    session=session,
                    scraper_manager=self.scraper_manager,
                    use_title_filtering=True,
                    use_source_priority_sorting=True,
                    progress_callback=None,
                )
            if not results:
                return CommandResult(text=f"🔍 未找到与「{keyword}」相关的结果。")
            serialized = []
            for r in results:
                if hasattr(r, 'model_dump'):
                    d = r.model_dump()
                elif isinstance(r, dict):
                    d = r
                else:
                    d = vars(r) if hasattr(r, '__dict__') else {}
                serialized.append({
                    "title": d.get('title', '未知'),
                    "provider": d.get('provider', '未知源'),
                    "mediaId": d.get('mediaId'),
                    "type": d.get('type', ''),
                    "season": d.get('season', 1),
                    "year": d.get('year'),
                    "episodeCount": d.get('episodeCount'),
                    "imageUrl": d.get('imageUrl'),
                })
            conv_data = {"keyword": keyword, "results": serialized}
            if parsed_season is not None:
                conv_data["parsed_season"] = parsed_season
            if parsed_episode is not None:
                conv_data["parsed_episode"] = parsed_episode
            self.set_conversation(user_id, "search_results", conv_data,
                                  chat_id=kw.get("chat_id"))
            suffix = ""
            if parsed_season is not None:
                suffix += f" S{parsed_season:02d}"
            if parsed_episode is not None:
                suffix += f"E{parsed_episode}"
            display_keyword = keyword + suffix if suffix else keyword
            return self._build_search_page(serialized, display_keyword, 0)
        except Exception as e:
            logger.error(f"搜索失败: {e}", exc_info=True)
            return CommandResult(success=False, text=f"搜索出错: {e}")

    def _build_search_page(self, results: list, keyword: str, page: int,
                           edit_message_id: int = None) -> CommandResult:
        total = len(results)
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_items = results[start:end]
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

        lines = [f"🔍 搜索「{keyword}」({start+1}-{end}/{total}):\n"]
        buttons = []
        articles = []
        for i, r in enumerate(page_items):
            idx = start + i
            year_str = f" ({r['year']})" if r.get('year') else ""
            ep_str = f" {r.get('episodeCount', '?')}集" if r.get('episodeCount') else ""
            lines.append(f"{idx+1}. [{r['provider']}] {r['title']}{year_str}{ep_str}")
            row = [
                {"text": f"📥 导入 {idx+1}", "callback_data": f"search_import:{idx}"},
                {"text": f"✏️ 编辑 {idx+1}", "callback_data": f"search_edit:{idx}"},
            ]
            buttons.append(row)
            articles.append({
                "title": f"{idx+1}. {r['title']}{year_str}{ep_str}",
                "description": f"[{r['provider']}]  回复 {idx+1} 导入",
                "picurl": r.get("imageUrl") or "",
                "url": "",
            })

        nav = []
        if page > 0:
            nav.append({"text": "⬅️ 上一页", "callback_data": f"search_page:{page-1}"})
        if page < total_pages - 1:
            nav.append({"text": "➡️ 下一页", "callback_data": f"search_page:{page+1}"})
        if nav:
            buttons.append(nav)

        return CommandResult(
            text="\n".join(lines),
            reply_markup=buttons,
            edit_message_id=edit_message_id,
            articles=articles,
        )

    async def cb_search_page(self, params, user_id, channel, **kw):
        page = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "search_results":
            return CommandResult(text="", answer_callback_text="搜索已过期，请重新搜索")
        return self._build_search_page(
            conv.data.get("results", []),
            conv.data.get("keyword", ""),
            page,
            edit_message_id=kw.get("message_id"),
        )

    async def cb_search_import(self, params, user_id, channel, **kw):
        """直接导入选中的搜索结果"""
        idx = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "search_results":
            return CommandResult(text="", answer_callback_text="搜索已过期")
        results = conv.data.get("results", [])
        if idx >= len(results):
            return CommandResult(text="", answer_callback_text="无效的选择")
        item = results[idx]
        media_id = item.get("mediaId")
        title = item.get("title", "未知")
        if not media_id:
            return CommandResult(text="", answer_callback_text="该结果无法直接导入")
        parsed_season = conv.data.get("parsed_season")
        parsed_episode = conv.data.get("parsed_episode")
        season = parsed_season if parsed_season is not None else item.get("season")
        self.clear_conversation(user_id)
        return await self._submit_auto_import(
            search_type="keyword", search_term=title,
            media_type=item.get("type"), season=season,
            episode=parsed_episode,
            edit_message_id=kw.get("message_id"),
        )

    async def cb_search_episodes(self, params, user_id, channel, **kw):
        return CommandResult(text="", answer_callback_text="分集导入暂未实现")

    async def cb_episode_page(self, params, user_id, channel, **kw):
        return CommandResult(text="", answer_callback_text="分集分页暂未实现")

    # ── 编辑导入流程 ──

    async def cb_search_edit(self, params, user_id, channel, **kw):
        """点击「编辑导入」→ 获取分集列表 → 进入编辑界面"""
        idx = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "search_results":
            return CommandResult(text="", answer_callback_text="搜索已过期")
        results = conv.data.get("results", [])
        if idx >= len(results):
            return CommandResult(text="", answer_callback_text="无效的选择")
        item = results[idx]
        provider = item.get("provider", "")
        media_id = item.get("mediaId")
        if not media_id or not provider:
            return CommandResult(text="", answer_callback_text="该结果不支持编辑导入")
        if not self.scraper_manager:
            return CommandResult(text="", answer_callback_text="搜索服务未就绪")
        try:
            scraper = self.scraper_manager.get_scraper(provider)
            episodes = await scraper.get_episodes(media_id, db_media_type=item.get("type"))
            if not episodes:
                return CommandResult(text="", answer_callback_text="未获取到分集列表")
            ep_list = []
            for ep in episodes:
                if hasattr(ep, 'model_dump'):
                    d = ep.model_dump()
                elif isinstance(ep, dict):
                    d = ep
                else:
                    d = vars(ep) if hasattr(ep, '__dict__') else {}
                ep_list.append({
                    "provider": d.get("provider", provider),
                    "episodeId": d.get("episodeId", ""),
                    "title": d.get("title", f"第{d.get('episodeIndex', '?')}集"),
                    "episodeIndex": d.get("episodeIndex", 0),
                    "url": d.get("url"),
                })
            selected = list(range(len(ep_list)))
            edit_data = {
                "item": item,
                "episodes": ep_list,
                "selected": selected,
                "title": item.get("title", ""),
                "type": item.get("type", "tv_series"),
                "season": item.get("season", 1),
                "_search_snapshot": conv.data,
            }
            self.set_conversation(user_id, "edit_import", edit_data,
                                  chat_id=kw.get("chat_id"))
            return self._build_edit_page(edit_data, 0, edit_message_id=kw.get("message_id"))
        except Exception as e:
            logger.error(f"获取分集列表失败: {e}", exc_info=True)
            return CommandResult(text=f"❌ 获取分集列表失败: {e}",
                                 edit_message_id=kw.get("message_id"))

    def _build_edit_page(self, edit_data: dict, page: int,
                         edit_message_id: int = None) -> CommandResult:
        episodes = edit_data.get("episodes", [])
        selected = set(edit_data.get("selected", []))
        item = edit_data.get("item", {})
        title = edit_data.get("title", item.get("title", ""))
        media_type = edit_data.get("type", "tv_series")
        season = edit_data.get("season", 1)
        type_label = "📺 电视剧" if media_type == "tv_series" else "🎬 电影"

        total_eps = len(episodes)
        ps = self.EDIT_EP_PAGE_SIZE
        start = page * ps
        end = min(start + ps, total_eps)
        total_pages = (total_eps + ps - 1) // ps

        lines = [
            f"✏️ 编辑导入: {title}",
            f"源: {item.get('provider', '?')} | {type_label} | S{season:02d}",
            f"已选: {len(selected)}/{total_eps} 集\n",
        ]
        buttons = []
        for i in range(start, end):
            ep = episodes[i]
            check = "✅" if i in selected else "⬜"
            ep_label = f"{check} {ep['episodeIndex']}. {ep['title']}"
            if len(ep_label) > 40:
                ep_label = ep_label[:37] + "..."
            buttons.append([{
                "text": ep_label,
                "callback_data": f"edit_ep_toggle:{i}:{page}",
            }])

        nav = []
        if page > 0:
            nav.append({"text": "⬅️ 上一页", "callback_data": f"edit_ep_page:{page-1}"})
        if page < total_pages - 1:
            nav.append({"text": "➡️ 下一页", "callback_data": f"edit_ep_page:{page+1}"})
        if nav:
            buttons.append(nav)

        buttons.append([
            {"text": "☑️ 全选", "callback_data": f"edit_ep_all:{page}"},
            {"text": "⬜ 取消全选", "callback_data": f"edit_ep_none:{page}"},
        ])
        buttons.append([
            {"text": f"🔄 改类型", "callback_data": f"edit_type:{media_type}"},
            {"text": f"S{season:02d} 改季度", "callback_data": "edit_season"},
        ])
        buttons.append([
            {"text": "🔙 返回搜索", "callback_data": "edit_back"},
            {"text": f"✅ 确认导入 ({len(selected)}集)", "callback_data": "edit_confirm"},
        ])

        return CommandResult(
            text="\n".join(lines),
            reply_markup=buttons,
            edit_message_id=edit_message_id,
        )

    async def cb_edit_ep_toggle(self, params, user_id, channel, **kw):
        ep_idx = int(params[0]) if len(params) > 0 else 0
        page = int(params[1]) if len(params) > 1 else 0
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        selected: list = conv.data.get("selected", [])
        if ep_idx in selected:
            selected.remove(ep_idx)
        else:
            selected.append(ep_idx)
        conv.data["selected"] = selected
        self.set_conversation(user_id, "edit_import", conv.data,
                              chat_id=kw.get("chat_id"))
        return self._build_edit_page(conv.data, page, edit_message_id=kw.get("message_id"))

    async def cb_edit_ep_page(self, params, user_id, channel, **kw):
        page = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        return self._build_edit_page(conv.data, page, edit_message_id=kw.get("message_id"))

    async def cb_edit_ep_all(self, params, user_id, channel, **kw):
        page = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        conv.data["selected"] = list(range(len(conv.data.get("episodes", []))))
        self.set_conversation(user_id, "edit_import", conv.data,
                              chat_id=kw.get("chat_id"))
        return self._build_edit_page(conv.data, page, edit_message_id=kw.get("message_id"))

    async def cb_edit_ep_none(self, params, user_id, channel, **kw):
        page = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        conv.data["selected"] = []
        self.set_conversation(user_id, "edit_import", conv.data,
                              chat_id=kw.get("chat_id"))
        return self._build_edit_page(conv.data, page, edit_message_id=kw.get("message_id"))

    async def cb_edit_type(self, params, user_id, channel, **kw):
        current_type = params[0] if params else "tv_series"
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        new_type = "movie" if current_type == "tv_series" else "tv_series"
        conv.data["type"] = new_type
        self.set_conversation(user_id, "edit_import", conv.data,
                              chat_id=kw.get("chat_id"))
        return self._build_edit_page(conv.data, 0, edit_message_id=kw.get("message_id"))

    async def cb_edit_season(self, params, user_id, channel, **kw):
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        current_season = conv.data.get("season", 1)
        return CommandResult(
            text=f"当前季度: S{current_season:02d}\n请选择季度：",
            reply_markup=[
                [{"text": f"S{i:02d}", "callback_data": f"auto_season:{i}"} for i in range(1, 5)],
                [{"text": f"S{i:02d}", "callback_data": f"auto_season:{i}"} for i in range(5, 9)],
            ],
            edit_message_id=kw.get("message_id"),
        )

    async def cb_edit_title(self, params, user_id, channel, **kw):
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        self.set_conversation(user_id, "edit_title_input", conv.data,
                              chat_id=kw.get("chat_id"))
        return CommandResult(
            text=f"当前标题: {conv.data.get('title', '')}\n请输入新标题：",
            edit_message_id=kw.get("message_id"),
        )

    async def _text_edit_title(self, text: str, user_id: str, channel, **kw):
        conv = self.get_conversation(user_id)
        if not conv:
            return CommandResult(text="操作已过期。")
        conv.data["title"] = text.strip()
        self.set_conversation(user_id, "edit_import", conv.data,
                              chat_id=kw.get("chat_id"))
        return self._build_edit_page(conv.data, 0)

    async def cb_edit_confirm(self, params, user_id, channel, **kw):
        """确认编辑导入 → 提交任务"""
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        episodes = conv.data.get("episodes", [])
        selected: list = conv.data.get("selected", [])
        item = conv.data.get("item", {})
        title = conv.data.get("title", item.get("title", ""))
        media_type = conv.data.get("type", "tv_series")
        season = conv.data.get("season", 1)

        if not selected:
            return CommandResult(text="", answer_callback_text="请至少选择一集")

        selected_episodes = [episodes[i] for i in sorted(selected) if i < len(episodes)]
        self.clear_conversation(user_id)

        return await self._submit_edited_import(
            provider=item.get("provider", ""),
            media_id=item.get("mediaId", ""),
            title=title,
            media_type=media_type,
            season=season,
            year=item.get("year"),
            image_url=item.get("imageUrl"),
            episodes=selected_episodes,
            edit_message_id=kw.get("message_id"),
        )

    async def cb_edit_back(self, params, user_id, channel, **kw):
        """返回搜索结果"""
        conv = self.get_conversation(user_id)
        if not conv or conv.state != "edit_import":
            return CommandResult(text="", answer_callback_text="操作已过期")
        snapshot = conv.data.get("_search_snapshot")
        if not snapshot or not snapshot.get("results"):
            self.clear_conversation(user_id)
            return CommandResult(
                text="已退出编辑。请使用 /search 重新搜索。",
                edit_message_id=kw.get("message_id"),
            )
        self.set_conversation(user_id, "search_results", snapshot,
                              chat_id=kw.get("chat_id"))
        keyword = snapshot.get("keyword", "")
        return self._build_search_page(
            snapshot["results"], keyword, 0,
            edit_message_id=kw.get("message_id"),
        )

    async def _text_search_episode_range(self, text: str, user_id: str, channel, **kw):
        """搜索结果的集数范围输入"""
        conv = self.get_conversation(user_id)
        if not conv:
            return CommandResult(text="操作已过期。")
        search_term = conv.data.get("search_term", "")
        self.clear_conversation(user_id)
        return await self._submit_auto_import(
            search_type="keyword", search_term=search_term,
            episode=text.strip(),
        )

