"""
流控查询命令模块
提供 @CXLK 指令,查询流控使用情况和剩余时间
"""
import logging
from typing import List, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession

from .base import CommandHandler
from .. import crud

if TYPE_CHECKING:
    from ..dandan_api import DandanSearchAnimeResponse

logger = logging.getLogger(__name__)


class RateLimitStatusCommand(CommandHandler):
    """流控状态查询命令"""
    
    def __init__(self):
        super().__init__(
            name="CXLK",
            description="查询流控使用情况和剩余重置时间",
            cooldown_seconds=5,
            usage="@CXLK (支持大小写)",
            examples=["@CXLK", "@cxlk"]
        )
    
    async def execute(self, token: str, args: List[str], session: AsyncSession,
                     config_manager, **kwargs) -> "DandanSearchAnimeResponse":
        """执行流控查询"""
        from ..rate_limiter import RateLimiter
        from ..timezone import get_now
        
        # 获取图片URL
        image_url = await self.get_image_url(config_manager)
        
        # 获取 rate_limiter
        rate_limiter: RateLimiter = kwargs.get('rate_limiter')
        if not rate_limiter:
            return self.error_response(
                title="流控查询失败",
                description="系统未配置流控管理器",
                image_url=image_url
            )
        
        # 获取流控配置
        global_limit = rate_limiter.global_limit
        period_seconds = rate_limiter.global_period_seconds
        fallback_limit = rate_limiter.fallback_limit
        enabled = rate_limiter.enabled
        verification_failed = rate_limiter._verification_failed
        
        # 获取所有流控状态
        all_states = await crud.get_all_rate_limit_states(session)
        states_map = {s.providerName: s for s in all_states}
        
        # 计算剩余重置时间
        global_state = states_map.get("__global__")
        seconds_until_reset = 0
        if global_state:
            now = get_now().replace(tzinfo=None)
            time_since_reset = now - global_state.lastResetTime
            seconds_until_reset = max(0, int(period_seconds - time_since_reset.total_seconds()))
        
        # 格式化时间周期
        if period_seconds < 60:
            period_str = f"{period_seconds}秒"
        elif period_seconds < 3600:
            period_str = f"{period_seconds // 60}分钟"
        else:
            period_str = f"{period_seconds // 3600}小时"
        
        # 构建响应列表
        items = []
        
        # 第一项：剩余重置时间
        minutes = seconds_until_reset // 60
        seconds = seconds_until_reset % 60
        time_display = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
        
        status_text = "🔴 禁用" if not enabled else ("⚠️ 验证失败" if verification_failed else "🟢 启用")
        
        reset_desc = (
            f"流控状态: {status_text}\n"
            f"周期长度: {period_str}\n"
            f"距离重置: {time_display}\n\n"
            f"💡 重置后所有计数器将清零"
        )
        
        items.append(
            self.build_response_item(
                anime_id=999999990,
                title="⏱️ 重置时间",
                description=reset_desc,
                image_url=image_url,
                type="other"
            )
        )
        
        # 第二项：下载流控（全局）
        global_count = global_state.requestCount if global_state else 0
        global_usage_percent = int((global_count / global_limit) * 100) if global_limit > 0 else 0
        
        # 进度条
        progress_bar = self._make_progress_bar(global_count, global_limit)
        
        download_desc = (
            f"全局配额: {global_count} / {global_limit} 次\n"
            f"使用率: {global_usage_percent}%\n\n"
            f"{progress_bar}\n\n"
            f"💡 所有下载操作共享此配额"
        )
        
        items.append(
            self.build_response_item(
                anime_id=999999991,
                title="📥 下载流控",
                description=download_desc,
                image_url=image_url,
                type="other",
                episodeCount=global_count
            )
        )
        
        # 第三项：后备流控
        fallback_match_state = states_map.get("__fallback_match__")
        fallback_search_state = states_map.get("__fallback_search__")
        
        match_count = fallback_match_state.requestCount if fallback_match_state else 0
        search_count = fallback_search_state.requestCount if fallback_search_state else 0
        total_fallback = match_count + search_count
        
        fallback_usage_percent = int((total_fallback / fallback_limit) * 100) if fallback_limit > 0 else 0
        
        fallback_progress = self._make_progress_bar(total_fallback, fallback_limit)
        
        fallback_desc = (
            f"总计: {total_fallback} / {fallback_limit} 次\n"
            f"使用率: {fallback_usage_percent}%\n\n"
            f"{fallback_progress}\n\n"
            f"📊 详细分类:\n"
            f"  • 匹配后备: {match_count} 次\n"
            f"  • 搜索后备: {search_count} 次\n\n"
            f"💡 后备不消耗全局配额"
        )
        
        items.append(
            self.build_response_item(
                anime_id=999999992,
                title="🔄 后备流控",
                description=fallback_desc,
                image_url=image_url,
                type="other",
                episodeCount=total_fallback
            )
        )
        
        logger.info(f"@CXLK 查询流控: 全局={global_count}/{global_limit}, 后备={total_fallback}/{fallback_limit}, 剩余={time_display}")
        
        return self.build_response(items)
    
    def _make_progress_bar(self, current: int, total: int, width: int = 10) -> str:
        """生成文本进度条"""
        if total <= 0:
            return "▱" * width
        
        filled = int((current / total) * width)
        filled = min(filled, width)  # 确保不超过宽度
        
        bar = "▰" * filled + "▱" * (width - filled)
        return bar

