"""
/refresh 菜单 Mixin — 弹幕库管理（浏览、刷新、删除源/分集）
"""
import logging
from src.notification.base import CommandResult

logger = logging.getLogger(__name__)

PAGE_SIZE = 5


class LibraryMenuMixin:
    """处理 /refresh 命令及弹幕库管理所有 cmd_/cb_/_text_/_do_ 方法"""

    # ── /refresh 入口 ──

    async def cmd_refresh(self, args: str, user_id: str, channel, **kw) -> CommandResult:
        """弹幕库管理 — 浏览媒体库或搜索"""
        if args and args.strip():
            return await self._refresh_search_library(args.strip(), user_id, 0, **kw)
        return await self._build_library_page(user_id, 0, **kw)

    # ── 媒体库列表页 ──

    async def _build_library_page(self, user_id: str, page: int,
                                   edit_message_id: int = None, **kw) -> CommandResult:
        """构建弹幕库管理分页列表"""
        try:
            from src.db import crud
            async with self._session_factory() as session:
                result = await crud.get_library_anime(
                    session, page=page + 1, page_size=PAGE_SIZE,
                )
            total = result.get("total", 0)
            items = result.get("list", [])
            if not items:
                return CommandResult(
                    text="📚 弹幕库为空。\n\n提示: 使用 /refresh <关键词> 搜索",
                    edit_message_id=edit_message_id,
                )
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            start = page * PAGE_SIZE
            lines = [f"📚 弹幕库管理 ({start+1}-{min(start+PAGE_SIZE, total)}/{total}):\n"]
            buttons = []
            articles = []
            for item in items:
                anime_id = item.get("animeId") or item.get("id")
                title = item.get("title", "未知")
                ep_count = item.get("episodeCount", 0)
                lines.append(f"• {title} ({ep_count}集)")
                buttons.append([{
                    "text": f"📂 {title}",
                    "callback_data": f"refresh_anime:{anime_id}",
                }])
                articles.append({
                    "title": title,
                    "description": f"{ep_count}集",
                    "picurl": item.get("imageUrl") or "",
                    "url": "",
                })
            nav = []
            if page > 0:
                nav.append({"text": "⬅️ 上一页", "callback_data": f"lib_page:{page-1}"})
            if page < total_pages - 1:
                nav.append({"text": "➡️ 下一页", "callback_data": f"lib_page:{page+1}"})
            if nav:
                buttons.append(nav)
            self.set_conversation(user_id, "refresh_keyword_input", {},
                                  chat_id=kw.get("chat_id"))
            return CommandResult(
                text="\n".join(lines) + "\n\n💡 也可发送关键词搜索媒体库",
                reply_markup=buttons,
                edit_message_id=edit_message_id or kw.get("message_id"),
                articles=articles,
            )
        except Exception as e:
            logger.error(f"获取媒体库失败: {e}", exc_info=True)
            return CommandResult(text=f"获取媒体库出错: {e}")

    async def _refresh_search_library(self, keyword: str, user_id: str,
                                       page: int, edit_message_id: int = None,
                                       **kw) -> CommandResult:
        """在媒体库中搜索"""
        try:
            from src.db import crud
            async with self._session_factory() as session:
                result = await crud.get_library_anime(
                    session, keyword=keyword, page=page + 1, page_size=PAGE_SIZE,
                )
            total = result.get("total", 0)
            items = result.get("list", [])
            if not items:
                return CommandResult(text=f"📚 弹幕库中未找到「{keyword}」。")
            self.set_conversation(user_id, "refresh_library_browse", {
                "keyword": keyword,
            }, chat_id=kw.get("chat_id"))
            total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            start = page * PAGE_SIZE
            lines = [f"📚 弹幕库管理 搜索「{keyword}」({start+1}-{min(start+PAGE_SIZE, total)}/{total}):\n"]
            buttons = []
            articles = []
            for item in items:
                anime_id = item.get("animeId") or item.get("id")
                title = item.get("title", "未知")
                lines.append(f"• {title}")
                buttons.append([{
                    "text": f"📂 {title}",
                    "callback_data": f"refresh_anime:{anime_id}",
                }])
                articles.append({
                    "title": title,
                    "description": "点击管理",
                    "picurl": item.get("imageUrl") or "",
                    "url": "",
                })
            nav = []
            if page > 0:
                nav.append({"text": "⬅️", "callback_data": f"lib_page:{page-1}"})
            if page < total_pages - 1:
                nav.append({"text": "➡️", "callback_data": f"lib_page:{page+1}"})
            if nav:
                buttons.append(nav)
            return CommandResult(
                text="\n".join(lines),
                reply_markup=buttons,
                edit_message_id=edit_message_id or kw.get("message_id"),
                articles=articles,
            )
        except Exception as e:
            return CommandResult(text=f"搜索媒体库出错: {e}")

    async def cb_lib_page(self, params, user_id, channel, **kw):
        page = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        if conv and conv.data.get("keyword"):
            return await self._refresh_search_library(
                conv.data["keyword"], user_id, page,
                edit_message_id=kw.get("message_id"), **kw,
            )
        return await self._build_library_page(
            user_id, page, edit_message_id=kw.get("message_id"), **kw,
        )

    async def _text_refresh_keyword(self, text: str, user_id: str, channel, **kw):
        """刷新命令中的关键词搜索"""
        return await self._refresh_search_library(text.strip(), user_id, 0, **kw)

    # ── 数据源列表页 ──

    async def cb_refresh_anime(self, params, user_id, channel, **kw):
        """选择作品 → 显示数据源列表（刷新 + 删除）"""
        anime_id = int(params[0]) if params else 0
        try:
            from src.db import crud
            async with self._session_factory() as session:
                sources = await crud.get_anime_sources(session, anime_id)
                details = await crud.get_anime_full_details(session, anime_id)
            title = details.get("title", "未知") if details else "未知"
            if not sources:
                return CommandResult(
                    text=f"📂 {title}\n暂无数据源。",
                    edit_message_id=kw.get("message_id"),
                )
            lines = [f"📂 {title}\n选择数据源操作：\n"]
            buttons = []
            image_url = (details or {}).get("imageUrl") or "" if details else ""
            for s in sources:
                sid = s.get("sourceId")
                provider = s.get("providerName", "未知")
                ep_count = s.get("episodeCount", 0)
                lines.append(f"• [{provider}] {ep_count}集")
                buttons.append([
                    {"text": f"🔄 [{provider}] {ep_count}集",
                     "callback_data": f"refresh_source:{anime_id}:{sid}"},
                    {"text": "🗑️ 删除源",
                     "callback_data": f"delete_source_do:{anime_id}:{sid}"},
                ])
            articles = [{
                "title": title,
                "description": f"共 {sum(s.get('episodeCount', 0) for s in sources)} 集，{len(sources)} 个源",
                "picurl": image_url,
                "url": "",
            }] if image_url else []
            buttons.append([{"text": "🔙 返回媒体库", "callback_data": "lib_page:0"}])
            return CommandResult(
                text="\n".join(lines),
                reply_markup=buttons,
                edit_message_id=kw.get("message_id"),
                articles=articles,
            )
        except Exception as e:
            return CommandResult(text=f"获取数据源失败: {e}")

    # ── 源操作页（刷新/删除分集）──

    async def cb_refresh_source(self, params, user_id, channel, **kw):
        """选择数据源 → 显示分集预览 + 刷新/删除操作"""
        anime_id = int(params[0]) if len(params) > 0 else 0
        source_id = int(params[1]) if len(params) > 1 else 0
        try:
            from src.db import crud
            async with self._session_factory() as session:
                ep_result = await crud.get_episodes_for_source(session, source_id)
                source_info = await crud.get_anime_source_info(session, source_id)
            episodes = ep_result.get("episodes", [])
            total = ep_result.get("total", 0)
            provider = source_info.get("providerName", "未知") if source_info else "未知"
            title = source_info.get("title", "未知") if source_info else "未知"

            self.set_conversation(user_id, "refresh_episode_select", {
                "anime_id": anime_id, "source_id": source_id,
                "provider": provider, "title": title,
            }, chat_id=kw.get("chat_id"))

            lines = [f"📂 {title} [{provider}]\n共 {total} 集\n"]
            for ep in episodes[:8]:
                idx = ep.get("episodeIndex", "?")
                ep_title = ep.get("title", "")
                count = ep.get("commentCount", 0)
                lines.append(f"  第{idx}集 {ep_title} ({count}条弹幕)")
            if total > 8:
                lines.append(f"  ... 还有 {total - 8} 集")

            buttons = [
                [{"text": "🔄 全部刷新", "callback_data": f"refresh_do:{source_id}:all"},
                 {"text": "✏️ 选择刷新", "callback_data": f"refresh_do:{source_id}:input"}],
                [{"text": "🗑️ 全部删除弹幕", "callback_data": f"delete_ep_all:{source_id}"},
                 {"text": "✏️ 选择删除", "callback_data": f"delete_ep_range:{source_id}"}],
                [{"text": "🔙 返回数据源", "callback_data": f"refresh_anime:{anime_id}"}],
            ]
            return CommandResult(
                text="\n".join(lines),
                reply_markup=buttons,
                edit_message_id=kw.get("message_id"),
            )
        except Exception as e:
            return CommandResult(text=f"获取分集列表失败: {e}")

    async def cb_refresh_ep_page(self, params, user_id, channel, **kw):
        """分集列表分页（预留）"""
        return CommandResult(text="", answer_callback_text="分集分页暂未实现")

    # ── 刷新操作 ──

    async def cb_refresh_do(self, params, user_id, channel, **kw):
        """执行刷新"""
        source_id = int(params[0]) if len(params) > 0 else 0
        mode = params[1] if len(params) > 1 else "all"

        if mode == "input":
            conv = self.get_conversation(user_id)
            data = conv.data if conv else {}
            data["source_id"] = source_id
            self.set_conversation(user_id, "refresh_episode_range", data,
                                  chat_id=kw.get("chat_id"))
            return CommandResult(
                text="✏️ 选择刷新 — 请输入要刷新的集数范围：\n"
                     "格式: 1,3,5  /  7-13  /  all（全部）",
                edit_message_id=kw.get("message_id"),
            )
        return await self._do_refresh_source(source_id, None, kw.get("message_id"))

    async def _do_refresh_source(self, source_id: int, episode_range: str = None,
                                  edit_message_id: int = None) -> CommandResult:
        """执行数据源刷新 — 全量用 full_refresh_task，指定集数用 refresh_bulk_episodes_task"""
        if not self.task_manager:
            return CommandResult(success=False, text="任务管理器未就绪。")
        try:
            from src.db import crud
            async with self._session_factory() as session:
                source_info = await crud.get_anime_source_info(session, source_id)
            if not source_info:
                return CommandResult(text="数据源未找到。")
            provider = source_info.get("providerName", "未知")
            title = source_info.get("title", "未知")

            if episode_range:
                from src.tasks import parse_episode_ranges, refresh_bulk_episodes_task
                indices = parse_episode_ranges(episode_range)
                async with self._session_factory() as session:
                    ep_result = await crud.get_episodes_for_source(session, source_id)
                episodes = ep_result.get("episodes", [])
                ep_ids = [e["episodeId"] for e in episodes
                          if e.get("episodeIndex") in indices]
                if not ep_ids:
                    return CommandResult(text=f"未找到匹配的集数: {episode_range}")
                ep_desc = episode_range
                task_title = f"TG刷新: {title} [{provider}] (E{ep_desc})"
                task_coro = lambda session, cb: refresh_bulk_episodes_task(
                    ep_ids, session, self.scraper_manager,
                    self.rate_limiter, cb, self.config_manager,
                )
            else:
                from src.tasks import full_refresh_task
                ep_desc = "全部"
                task_title = f"TG刷新: {title} [{provider}] (全部)"
                task_coro = lambda session, cb: full_refresh_task(
                    source_id, session, self.scraper_manager,
                    self.task_manager, self.rate_limiter, cb,
                    self.metadata_manager, self.config_manager,
                )

            task_id, _ = await self.task_manager.submit_task(
                coro_factory=task_coro, title=task_title,
                task_type="tg_refresh",
                task_parameters={"sourceId": source_id}
            )
            return CommandResult(
                text=f"✅ 刷新任务已提交\n{title} [{provider}]\n集数: {ep_desc}\n任务ID: {task_id}",
                reply_markup=[[{"text": "📋 查看任务状态", "callback_data": f"task_detail:{task_id}"}]],
                edit_message_id=edit_message_id,
            )
        except Exception as e:
            logger.error(f"提交刷新任务失败: {e}", exc_info=True)
            return CommandResult(text=f"❌ 提交刷新任务失败: {e}")

    async def _text_refresh_episode_range(self, text: str, user_id: str, channel, **kw):
        """集数范围输入 → 执行刷新"""
        conv = self.get_conversation(user_id)
        if not conv:
            return CommandResult(text="操作已过期。")
        source_id = conv.data.get("source_id", 0)
        self.clear_conversation(user_id)
        episode_range = None if text.strip().lower() == "all" else text.strip()
        return await self._do_refresh_source(source_id, episode_range)

    # ── 删除源 ──

    async def cb_delete_source_do(self, params, user_id, channel, **kw):
        """点击「删除源」→ 弹出确认框"""
        anime_id = int(params[0]) if len(params) > 0 else 0
        source_id = int(params[1]) if len(params) > 1 else 0
        try:
            from src.db import crud
            async with self._session_factory() as session:
                source_info = await crud.get_anime_source_info(session, source_id)
            if not source_info:
                return CommandResult(text="", answer_callback_text="数据源不存在")
            provider = source_info.get("providerName", "未知")
            title = source_info.get("title", "未知")
            ep_count = source_info.get("episodeCount", 0)
            return CommandResult(
                text=f"⚠️ 确认删除数据源？\n\n"
                     f"番剧: {title}\n"
                     f"源: [{provider}]  共 {ep_count} 集\n\n"
                     f"此操作将删除该源及所有弹幕文件，不可撤销！",
                reply_markup=[[
                    {"text": "✅ 确认删除",
                     "callback_data": f"delete_source_confirm:{anime_id}:{source_id}"},
                    {"text": "❌ 取消",
                     "callback_data": f"refresh_anime:{anime_id}"},
                ]],
            )
        except Exception as e:
            return CommandResult(text=f"获取数据源信息失败: {e}")

    async def cb_delete_source_confirm(self, params, user_id, channel, **kw):
        """确认删除源 → 提交删除任务"""
        anime_id = int(params[0]) if len(params) > 0 else 0
        source_id = int(params[1]) if len(params) > 1 else 0
        if not self.task_manager:
            return CommandResult(text="任务管理器未就绪")
        try:
            from src.db import crud
            from src import tasks
            async with self._session_factory() as session:
                source_info = await crud.get_anime_source_info(session, source_id)
            if not source_info:
                return CommandResult(text="数据源不存在")
            provider = source_info.get("providerName", "未知")
            title = source_info.get("title", "未知")
            task_title = f"TG删除源: {title} [{provider}]"
            unique_key = f"delete-source-{source_id}"

            async def _task_coro(session, cb):
                return await tasks.delete_source_task(source_id, session, cb)

            task_id, _ = await self.task_manager.submit_task(
                coro_factory=_task_coro, title=task_title,
                unique_key=unique_key,
                task_type="tg_delete",
                task_parameters={"sourceId": source_id},
            )
            return CommandResult(
                text=f"✅ 删除任务已提交\n{title} [{provider}]\n任务ID: {task_id}",
                reply_markup=[[
                    {"text": "📋 查看任务状态", "callback_data": f"task_detail:{task_id}"},
                    {"text": "🔙 返回媒体库", "callback_data": "lib_page:0"},
                ]],
                edit_message_id=kw.get("message_id"),
            )
        except Exception as e:
            logger.error(f"提交删除源任务失败: {e}", exc_info=True)
            return CommandResult(text=f"❌ 提交删除任务失败: {e}")

    # ── 删除分集 ──

    async def cb_delete_ep_all(self, params, user_id, channel, **kw):
        """全部删除该源的所有分集弹幕"""
        source_id = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        anime_id = (conv.data.get("anime_id", 0) if conv else 0)
        if not self.task_manager:
            return CommandResult(text="任务管理器未就绪")
        try:
            from src.db import crud
            from src import tasks
            async with self._session_factory() as session:
                source_info = await crud.get_anime_source_info(session, source_id)
            if not source_info:
                return CommandResult(text="数据源不存在")
            provider = source_info.get("providerName", "未知")
            title = source_info.get("title", "未知")
            task_title = f"TG删除弹幕: {title} [{provider}] (全部)"
            unique_key = f"delete-bulk-sources-{source_id}-all"

            async def _task_coro(session, cb):
                ep_result = await crud.get_episodes_for_source(session, source_id)
                ep_ids = [e["episodeId"] for e in ep_result.get("episodes", [])]
                if not ep_ids:
                    return
                return await tasks.delete_bulk_episodes_task(ep_ids, session, cb)

            task_id, _ = await self.task_manager.submit_task(
                coro_factory=_task_coro, title=task_title,
                unique_key=unique_key,
                task_type="tg_delete",
                task_parameters={"sourceId": source_id},
            )
            return CommandResult(
                text=f"✅ 全部删除任务已提交\n{title} [{provider}]\n任务ID: {task_id}",
                reply_markup=[[
                    {"text": "📋 查看任务状态", "callback_data": f"task_detail:{task_id}"},
                    {"text": "🔙 返回", "callback_data": f"refresh_source:{anime_id}:{source_id}"},
                ]],
                edit_message_id=kw.get("message_id"),
            )
        except Exception as e:
            logger.error(f"提交全部删除任务失败: {e}", exc_info=True)
            return CommandResult(text=f"❌ 提交删除任务失败: {e}")

    async def cb_delete_ep_range(self, params, user_id, channel, **kw):
        """「选择删除」→ 进入集数范围输入状态"""
        source_id = int(params[0]) if params else 0
        conv = self.get_conversation(user_id)
        data = conv.data if conv else {}
        data["source_id"] = source_id
        self.set_conversation(user_id, "delete_episode_range", data,
                              chat_id=kw.get("chat_id"))
        return CommandResult(
            text="✏️ 选择删除 — 请输入要删除的集数范围：\n"
                 "格式: 1,3,5  /  7-13  /  all（全部）",
            edit_message_id=kw.get("message_id"),
        )

    async def _text_delete_episode_range(self, text: str, user_id: str, channel, **kw):
        """集数范围输入 → 执行删除"""
        conv = self.get_conversation(user_id)
        if not conv:
            return CommandResult(text="操作已过期。")
        source_id = conv.data.get("source_id", 0)
        anime_id = conv.data.get("anime_id", 0)
        self.clear_conversation(user_id)
        return await self._do_delete_source_episodes(source_id, anime_id, text.strip())

    async def _do_delete_source_episodes(self, source_id: int, anime_id: int,
                                          episode_range: str) -> CommandResult:
        """执行按集数范围删除弹幕"""
        if not self.task_manager:
            return CommandResult(text="任务管理器未就绪")
        try:
            from src.db import crud
            from src import tasks
            async with self._session_factory() as session:
                source_info = await crud.get_anime_source_info(session, source_id)
            if not source_info:
                return CommandResult(text="数据源不存在")
            provider = source_info.get("providerName", "未知")
            title = source_info.get("title", "未知")

            async with self._session_factory() as session:
                ep_result = await crud.get_episodes_for_source(session, source_id)
            episodes = ep_result.get("episodes", [])

            if episode_range.lower() == "all":
                ep_ids = [e["episodeId"] for e in episodes]
                ep_desc = "全部"
            else:
                from src.tasks import parse_episode_ranges
                indices = parse_episode_ranges(episode_range)
                ep_ids = [e["episodeId"] for e in episodes if e.get("episodeIndex") in indices]
                ep_desc = episode_range

            if not ep_ids:
                return CommandResult(text=f"未找到匹配的集数: {episode_range}")

            task_title = f"TG删除弹幕: {title} [{provider}] (E{ep_desc})"
            unique_key = f"delete-bulk-sources-{source_id}-{ep_desc}"

            async def _task_coro(session, cb):
                return await tasks.delete_bulk_episodes_task(ep_ids, session, cb)

            task_id, _ = await self.task_manager.submit_task(
                coro_factory=_task_coro, title=task_title,
                unique_key=unique_key,
                task_type="tg_delete",
                task_parameters={"sourceId": source_id},
            )
            return CommandResult(
                text=f"✅ 删除任务已提交\n{title} [{provider}]\n集数: {ep_desc}\n任务ID: {task_id}",
                reply_markup=[[
                    {"text": "📋 查看任务状态", "callback_data": f"task_detail:{task_id}"},
                    {"text": "🔙 返回", "callback_data": f"refresh_source:{anime_id}:{source_id}"},
                ]],
            )
        except Exception as e:
            logger.error(f"提交删除任务失败: {e}", exc_info=True)
            return CommandResult(text=f"❌ 提交删除任务失败: {e}")

