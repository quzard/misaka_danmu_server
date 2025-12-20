"""
指令系统模块
支持以@开头的搜索词作为指令，提供通用的指令处理框架
"""
import time
import json
import logging
from typing import Optional, Tuple, List, Dict, Any, TYPE_CHECKING
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from . import crud

if TYPE_CHECKING:
    from .dandan_api import DandanSearchAnimeResponse

logger = logging.getLogger(__name__)


# 数据库缓存辅助函数（避免循环导入）
async def _get_db_cache(session: AsyncSession, prefix: str, key: str) -> Optional[Any]:
    """从数据库缓存中获取数据"""
    cache_key = f"{prefix}{key}"
    cache_entry = await crud.get_cache(session, cache_key)
    if cache_entry:
        # cache_entry 可能是对象（有 .value 属性）或直接是值
        if hasattr(cache_entry, 'value'):
            return cache_entry.value
        else:
            return cache_entry
    return None


async def _set_db_cache(session: AsyncSession, prefix: str, key: str, value: Any, ttl: int):
    """设置数据库缓存"""
    cache_key = f"{prefix}{key}"
    await crud.set_cache(session, cache_key, value, ttl)


def parse_command(search_term: str) -> Optional[Tuple[str, List[str]]]:
    """
    解析指令
    
    Args:
        search_term: 搜索词
        
    Returns:
        (指令名称, 参数列表) 或 None（不是指令）
    """
    if not search_term.startswith('@'):
        return None
    
    parts = search_term[1:].strip().split()
    command_name = parts[0].upper() if parts else ""
    args = parts[1:] if len(parts) > 1 else []
    
    return (command_name, args) if command_name else None


class CommandHandler:
    """指令处理器基类"""
    
    def __init__(self, name: str, description: str, cooldown_seconds: int = 0):
        """
        初始化指令处理器
        
        Args:
            name: 指令名称
            description: 指令描述
            cooldown_seconds: 冷却时间（秒），0表示无冷却
        """
        self.name = name
        self.description = description
        self.cooldown_seconds = cooldown_seconds
    
    async def can_execute(self, token: str, session: AsyncSession) -> Tuple[bool, Optional[int]]:
        """
        检查是否可以执行（频率限制）
        
        Args:
            token: 用户token
            session: 数据库会话
            
        Returns:
            (是否可执行, 剩余冷却秒数)
        """
        if self.cooldown_seconds == 0:
            return (True, None)
        
        cache_key = f"{token}_{self.name}"
        last_exec_time = await _get_db_cache(session, "command_cooldown_", cache_key)
        
        if last_exec_time:
            elapsed = time.time() - last_exec_time
            if elapsed < self.cooldown_seconds:
                remaining = int(self.cooldown_seconds - elapsed)
                return (False, remaining)
        
        return (True, None)
    
    async def execute(self, token: str, args: List[str], session: AsyncSession,
                     config_manager, **kwargs):
        """
        执行指令，子类需要实现

        Args:
            token: 用户token
            args: 指令参数
            session: 数据库会话
            config_manager: 配置管理器
            **kwargs: 其他依赖

        Returns:
            DandanSearchAnimeResponse
        """
        raise NotImplementedError
    
    async def record_execution(self, token: str, session: AsyncSession):
        """
        记录执行时间
        
        Args:
            token: 用户token
            session: 数据库会话
        """
        if self.cooldown_seconds > 0:
            cache_key = f"{token}_{self.name}"
            await _set_db_cache(session, "command_cooldown_", cache_key, time.time(), self.cooldown_seconds)


class ClearCacheCommand(CommandHandler):
    """清理缓存指令"""
    
    def __init__(self):
        super().__init__(
            name="QLHC",
            description="清理缓存",
            cooldown_seconds=30
        )
    
    async def execute(self, token: str, args: List[str], session: AsyncSession,
                     config_manager, **kwargs):
        """执行清理缓存"""
        # 运行时导入，避免循环依赖
        from .dandan_api import DandanSearchAnimeResponse, DandanSearchAnimeItem

        # 获取自定义域名
        custom_domain = await config_manager.get("customApiDomain", "")
        image_url = f"{custom_domain}/static/logo.png" if custom_domain else "/static/logo.png"

        try:
            # 获取cache_manager
            cache_manager = kwargs.get('cache_manager')

            # 清理内存缓存
            config_manager.clear_cache()

            # 清理数据库缓存
            await crud.clear_all_cache(session)

            # 记录执行时间
            await self.record_execution(token, session)

            logger.info(f"指令 @{self.name} 执行成功，token={token}")

            return DandanSearchAnimeResponse(animes=[
                DandanSearchAnimeItem(
                    animeId=999999998,  # 指令响应专用ID
                    bangumiId="999999998",
                    animeTitle="✓ 缓存清理成功",
                    type="other",
                    typeDescription="指令执行成功",
                    imageUrl=image_url,
                    startDate="2025-01-01T00:00:00+08:00",
                    year=2025,
                    episodeCount=0,
                    rating=0.0,
                    isFavorited=False
                )
            ])
        except Exception as e:
            logger.error(f"指令 @{self.name} 执行失败: {e}", exc_info=True)
            return DandanSearchAnimeResponse(animes=[
                DandanSearchAnimeItem(
                    animeId=999999998,
                    bangumiId="999999998",
                    animeTitle=f"✗ 缓存清理失败: {str(e)}",
                    type="other",
                    typeDescription="指令执行失败",
                    imageUrl=image_url,
                    startDate="2025-01-01T00:00:00+08:00",
                    year=2025,
                    episodeCount=0,
                    rating=0.0,
                    isFavorited=False
                )
            ])


class RefreshDanmakuCommand(CommandHandler):
    """
    刷新弹幕指令: @SXDM

    交互流程:
    1. @SXDM → 显示最近播放的番剧列表（#A #B #C #D #E）
    2. @SXDM #A → 显示该番剧的分集列表
    3. @SXDM {分集序号} → 触发刷新任务
    """

    # 番剧标签映射
    ANIME_LABELS = ['#A', '#B', '#C', '#D', '#E']

    def __init__(self):
        super().__init__(
            name="SXDM",
            description="刷新最近播放的弹幕",
            cooldown_seconds=2
        )

    async def execute(self, token: str, args: List[str], session: AsyncSession,
                     config_manager, **kwargs):
        """执行刷新指令"""
        from .dandan_api import DandanSearchAnimeResponse, DandanSearchAnimeItem
        from .orm_models import Anime, AnimeSource, Episode
        from .task_manager import TaskManager
        from .scraper_manager import ScraperManager
        from .rate_limiter import RateLimiter
        from . import tasks

        # 获取自定义域名
        custom_domain = await config_manager.get("customApiDomain", "")
        image_url = f"{custom_domain}/static/logo.png" if custom_domain else "/static/logo.png"

        # 获取会话状态
        session_key = f"cmd_session_{token}"
        session_json = await crud.get_cache(session, session_key)
        session_state = json.loads(session_json) if session_json else {}

        # 阶段1: 没有参数 → 显示番剧列表
        if not args:
            return await self._show_anime_list(token, session, session_key, custom_domain, image_url)

        # 获取当前阶段
        current_stage = session_state.get("stage", "select_anime")
        arg = args[0].upper()

        # 阶段2: select_anime → 选择番剧，显示分集列表
        if current_stage == "select_anime":
            return await self._show_episode_list(
                token, session, session_key, session_state, arg, custom_domain, image_url
            )

        # 阶段3: select_episode → 选择分集，触发刷新
        elif current_stage == "select_episode":
            # 获取依赖
            task_manager: TaskManager = kwargs.get('task_manager')
            scraper_manager: ScraperManager = kwargs.get('scraper_manager')
            rate_limiter: RateLimiter = kwargs.get('rate_limiter')

            if not all([task_manager, scraper_manager, rate_limiter]):
                return self._error_response("系统依赖缺失", custom_domain, image_url)

            return await self._trigger_refresh(
                token, session, session_key, session_state, arg,
                task_manager, scraper_manager, rate_limiter, config_manager,
                custom_domain, image_url
            )

        return self._error_response("会话状态异常，请重新执行 @SXDM", custom_domain, image_url)

    async def _show_anime_list(
        self,
        token: str,
        session: AsyncSession,
        session_key: str,
        custom_domain: str,
        image_url: str
    ):
        """显示最近播放的番剧列表"""
        from .dandan_api import DandanSearchAnimeResponse, DandanSearchAnimeItem
        from .orm_models import Anime, AnimeSource, Episode

        # 读取播放历史
        cache_key = f"play_history_{token}"
        history_json = await crud.get_cache(session, cache_key)
        history: List[Dict] = json.loads(history_json) if history_json else []

        if not history:
            return DandanSearchAnimeResponse(animes=[
                DandanSearchAnimeItem(
                    animeId=999999997,
                    bangumiId="999999997",
                    animeTitle="❌ 未找到最近播放记录",
                    type="other",
                    typeDescription="💡 提示: 播放视频后会自动记录 (10分钟有效)",
                    imageUrl=image_url,
                    startDate="2025-01-01T00:00:00+08:00",
                    year=2025,
                    episodeCount=0,
                    rating=0.0,
                    isFavorited=False
                )
            ])

        # 查询每部番剧的总集数
        anime_list = []
        for idx, record in enumerate(history[:5]):  # 只显示最近5部
            anime_id = record["animeId"]

            # 查询总集数（通过 AnimeSource 关联）
            stmt = (
                select(func.count(Episode.id))
                .join(AnimeSource, Episode.sourceId == AnimeSource.id)
                .where(AnimeSource.animeId == anime_id)
            )
            result = await session.execute(stmt)
            total_episodes = result.scalar() or 0

            anime_list.append({
                "label": self.ANIME_LABELS[idx],
                "animeId": anime_id,
                "animeTitle": record["animeTitle"],
                "totalEpisodes": total_episodes
            })

        # 构建返回消息
        lines = ["📺 最近播放的番剧 (10分钟内):"]
        lines.append("=" * 30)
        for anime in anime_list:
            lines.append(f"[{anime['label']}] {anime['animeTitle']} ({anime['totalEpisodes']}集)")
        lines.append("=" * 30)
        lines.append("💡 输入 @SXDM {标签} 查看分集")
        lines.append("例如: @SXDM #A")

        message = "\n".join(lines)

        # 保存会话状态
        session_state = {
            "command": "SXDM",
            "stage": "select_anime",
            "data": {"animeList": anime_list},
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        await crud.set_cache(session, session_key, json.dumps(session_state, ensure_ascii=False), 120)

        # 记录执行时间
        await self.record_execution(token, session)

        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999997,
                bangumiId="999999997",
                animeTitle="📺 最近播放列表",
                type="other",
                typeDescription=message,
                imageUrl=image_url,
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=len(anime_list),
                rating=0.0,
                isFavorited=False
            )
        ])

    async def _show_episode_list(
        self,
        token: str,
        session: AsyncSession,
        session_key: str,
        session_state: Dict,
        selected_label: str,
        custom_domain: str,
        image_url: str
    ):
        """显示选中番剧的分集列表"""
        from .dandan_api import DandanSearchAnimeResponse, DandanSearchAnimeItem
        from .orm_models import Episode, AnimeSource

        anime_list = session_state.get("data", {}).get("animeList", [])

        # 查找选中的番剧
        selected_anime = None
        for anime in anime_list:
            if anime["label"] == selected_label:
                selected_anime = anime
                break

        if not selected_anime:
            return self._error_response(
                f"❌ 无效的标签: {selected_label}\n💡 请输入 @SXDM 查看可用标签",
                custom_domain, image_url
            )

        anime_id = selected_anime["animeId"]

        # 查询分集列表（通过 AnimeSource 关联）
        stmt = (
            select(Episode)
            .join(AnimeSource, Episode.sourceId == AnimeSource.id)
            .where(AnimeSource.animeId == anime_id)
            .order_by(Episode.id)
        )
        result = await session.execute(stmt)
        episodes = result.scalars().all()

        if not episodes:
            return self._error_response("❌ 未找到分集信息", custom_domain, image_url)

        # 构建分集信息（使用 Episode.commentCount 字段）
        episode_list = []
        for ep in episodes:
            count = ep.commentCount or 0
            status = "已缓存" if count > 0 else "未缓存"
            episode_list.append({
                "index": len(episode_list) + 1,
                "episodeId": ep.id,
                "episodeTitle": ep.title or f"第{ep.episodeIndex}话",
                "commentCount": count,
                "status": status
            })

        # 构建返回消息
        lines = [f"📺 {selected_anime['animeTitle']} - 分集列表:"]
        lines.append("=" * 40)
        for ep in episode_list[:20]:  # 限制显示前20集
            lines.append(f"[{ep['index']}] {ep['episodeTitle']} - {ep['status']} ({ep['commentCount']}条)")
        if len(episode_list) > 20:
            lines.append(f"... 还有 {len(episode_list) - 20} 集未显示")
        lines.append("=" * 40)
        lines.append("💡 输入 @SXDM {序号} 刷新弹幕")
        lines.append("例如: @SXDM 5")

        message = "\n".join(lines)

        # 更新会话状态
        session_state["stage"] = "select_episode"
        session_state["data"]["selectedAnime"] = selected_anime
        session_state["data"]["episodes"] = episode_list
        await crud.set_cache(session, session_key, json.dumps(session_state, ensure_ascii=False), 120)

        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=selected_anime["animeId"],
                bangumiId=str(selected_anime["animeId"]),
                animeTitle=f"📺 {selected_anime['animeTitle']}",
                type="other",
                typeDescription=message,
                imageUrl=image_url,
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=len(episode_list),
                rating=0.0,
                isFavorited=False
            )
        ])

    async def _trigger_refresh(
        self,
        token: str,
        session: AsyncSession,
        session_key: str,
        session_state: Dict,
        selected_index_str: str,
        task_manager,
        scraper_manager,
        rate_limiter,
        config_manager,
        custom_domain: str,
        image_url: str
    ):
        """触发刷新任务"""
        from .dandan_api import DandanSearchAnimeResponse, DandanSearchAnimeItem
        from . import tasks

        # 解析索引
        try:
            selected_index = int(selected_index_str)
        except ValueError:
            return self._error_response(
                f"❌ 无效的序号: {selected_index_str}\n💡 请输入数字序号",
                custom_domain, image_url
            )

        episodes = session_state.get("data", {}).get("episodes", [])

        # 验证索引
        if selected_index < 1 or selected_index > len(episodes):
            return self._error_response(
                f"❌ 无效的序号，请输入 1-{len(episodes)}",
                custom_domain, image_url
            )

        selected_episode = episodes[selected_index - 1]
        episode_id = selected_episode["episodeId"]
        episode_title = selected_episode["episodeTitle"]
        anime_title = session_state.get("data", {}).get("selectedAnime", {}).get("animeTitle", "")

        # 验证分集存在
        info = await crud.get_episode_for_refresh(session, episode_id)
        if not info:
            return self._error_response(
                f"❌ 分集不存在: {episode_title}",
                custom_domain, image_url
            )

        # 提交刷新任务
        try:
            # 使用 unique_key 防止重复提交，也便于弹幕获取时检测刷新状态
            unique_key = f"refresh-episode-{episode_id}"

            task_id, _ = await task_manager.submit_task(
                lambda s, cb: tasks.refresh_episode_task(
                    episode_id, s, scraper_manager, rate_limiter, cb, config_manager
                ),
                f"指令刷新分集: {anime_title} - {episode_title}",
                unique_key=unique_key
            )

            # 清除会话状态
            await crud.delete_cache(session, session_key)

            # 记录执行时间
            await self.record_execution(token, session)

            logger.info(f"指令 @SXDM 触发刷新任务成功: episodeId={episode_id}, taskId={task_id}, token={token}")

            message = f"✓ 刷新任务已提交\n\n番剧: {anime_title}\n分集: {episode_title}\n任务ID: {task_id}\n\n💡 刷新完成后重新加载弹幕即可"

            return DandanSearchAnimeResponse(animes=[
                DandanSearchAnimeItem(
                    animeId=999999996,
                    bangumiId="999999996",
                    animeTitle="✓ 弹幕刷新任务已提交",
                    type="other",
                    typeDescription=message,
                    imageUrl=image_url,
                    startDate="2025-01-01T00:00:00+08:00",
                    year=2025,
                    episodeCount=0,
                    rating=0.0,
                    isFavorited=False
                )
            ])
        except Exception as e:
            logger.error(f"指令 @SXDM 提交刷新任务失败: {e}", exc_info=True)
            return self._error_response(
                f"✗ 提交刷新任务失败: {str(e)}",
                custom_domain, image_url
            )

    def _error_response(self, message: str, custom_domain: str, image_url: str):
        """构建错误响应"""
        from .dandan_api import DandanSearchAnimeResponse, DandanSearchAnimeItem

        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999995,
                bangumiId="999999995",
                animeTitle="✗ 操作失败",
                type="other",
                typeDescription=message,
                imageUrl=image_url,
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=0,
                rating=0.0,
                isFavorited=False
            )
        ])


# 全局指令注册表
COMMAND_HANDLERS: Dict[str, CommandHandler] = {
    "QLHC": ClearCacheCommand(),
    "SXDM": RefreshDanmakuCommand(),
    # 未来可以添加更多指令：
    # "HELP": HelpCommand(),
    # "STATUS": StatusCommand(),
}


async def handle_command(search_term: str, token: str, session: AsyncSession,
                        config_manager, cache_manager, **kwargs):
    """
    处理指令

    Args:
        search_term: 搜索词
        token: 用户token
        session: 数据库会话
        config_manager: 配置管理器
        cache_manager: 缓存管理器
        **kwargs: 其他依赖

    Returns:
        指令响应 或 None（不是指令）
    """
    # 运行时导入，避免循环依赖
    from .dandan_api import DandanSearchAnimeResponse, DandanSearchAnimeItem

    parsed = parse_command(search_term)
    if not parsed:
        return None

    command_name, args = parsed
    handler = COMMAND_HANDLERS.get(command_name)

    # 获取自定义域名
    custom_domain = await config_manager.get("customApiDomain", "")
    image_url = f"{custom_domain}/static/logo.png" if custom_domain else "/static/logo.png"

    if not handler:
        # 未知指令
        available_commands = ', '.join(['@' + k for k in COMMAND_HANDLERS.keys()])
        logger.warning(f"未知指令: @{command_name}, token={token}")

        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999998,
                bangumiId="999999998",
                animeTitle=f"✗ 未知指令: @{command_name}",
                type="other",
                typeDescription=f"可用指令: {available_commands}",
                imageUrl=image_url,
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=0,
                rating=0.0,
                isFavorited=False
            )
        ])

    # 检查频率限制
    can_exec, remaining = await handler.can_execute(token, session)
    if not can_exec:
        logger.info(f"指令 @{command_name} 冷却中, token={token}, 剩余{remaining}秒")

        return DandanSearchAnimeResponse(animes=[
            DandanSearchAnimeItem(
                animeId=999999998,
                bangumiId="999999998",
                animeTitle=f"⏱ 指令冷却中",
                type="other",
                typeDescription=f"你已在30秒内触发过 @{command_name} 指令，还有 {remaining} 秒才能再次使用",
                imageUrl=image_url,
                startDate="2025-01-01T00:00:00+08:00",
                year=2025,
                episodeCount=0,
                rating=0.0,
                isFavorited=False
            )
        ])

    # 执行指令
    return await handler.execute(token, args, session, config_manager, cache_manager=cache_manager, **kwargs)

