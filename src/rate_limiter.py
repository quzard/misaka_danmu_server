import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from . import crud
from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

class RateLimitExceededError(Exception):
    """当达到速率限制时引发的自定义异常。"""
    def __init__(self, message, provider, retry_after_seconds):
        super().__init__(message)
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds

class RateLimiter:
    """管理全局和各源的下载速率限制。"""

    def __init__(self, session_factory, config_manager: ConfigManager):
        self._session_factory = session_factory
        self._config_manager = config_manager
        self._lock = asyncio.Lock()

    async def _get_limit_and_period(self, provider_name: Optional[str]) -> tuple[int, int]:
        """获取指定源的限制和周期，如果未设置则回退到全局设置。"""
        # 全局默认值
        global_limit = int(await self._config_manager.get("rate_limit_global_limit", "50"))
        global_period = int(await self._config_manager.get("rate_limit_global_period_seconds", "3600"))

        if not provider_name:
            return global_limit, global_period

        # 各源的覆盖设置
        provider_limit_str = await self._config_manager.get(f"rate_limit_provider_{provider_name}_limit")
        provider_period_str = await self._config_manager.get(f"rate_limit_provider_{provider_name}_period_seconds")

        if provider_limit_str and provider_period_str:
            try:
                return int(provider_limit_str), int(provider_period_str)
            except (ValueError, TypeError):
                logger.warning(f"无效的速率限制配置 for '{provider_name}'，将使用全局设置。")
        
        return global_limit, global_period

    async def check_and_update(self, provider_name: str):
        """
        检查并更新给定源的速率限制。
        如果超出限制，则引发 RateLimitExceededError。
        """
        async with self._lock:
            async with self._session_factory() as session:
                # 检查全局限制
                await self._check_provider_limit(session, "__global__")
                # 检查各源限制
                await self._check_provider_limit(session, provider_name)

                # 如果两个检查都通过，则增加计数
                await crud.increment_rate_limit_count(session, "__global__")
                await crud.increment_rate_limit_count(session, provider_name)
                await session.commit()

    async def _check_provider_limit(self, session: AsyncSession, provider_key: str):
        """检查单个键（全局或特定源）的速率限制。"""
        is_global = provider_key == "__global__"
        limit, period_seconds = await self._get_limit_and_period(None if is_global else provider_key)

        if limit <= 0:  # 限制被禁用
            return

        state = await crud.get_rate_limit_state(session, provider_key)
        now = datetime.now(timezone.utc)
        period = timedelta(seconds=period_seconds)
        
        if not state or (now - state.last_reset_time) > period:
            await crud.reset_rate_limit_state(session, provider_key)
            return

        if state.request_count >= limit:
            retry_after = (state.last_reset_time + period) - now
            msg = f"速率限制已达到 '{provider_key}' ({state.request_count}/{limit})。请在 {retry_after.total_seconds():.0f} 秒后重试。"
            logger.warning(msg)
            raise RateLimitExceededError(msg, provider_key, retry_after.total_seconds())

    async def get_status(self) -> Dict[str, Any]:
        """获取所有速率限制器的当前状态。"""
        async with self._session_factory() as session:
            all_states = await crud.get_all_rate_limit_states(session)
            all_scrapers = await crud.get_all_scraper_settings(session)
        
        status_dict: Dict[str, Any] = {"globalStatus": {}, "providerStatus": {}}
        now = datetime.now(timezone.utc)

        # 全局状态
        global_limit, global_period = await self._get_limit_and_period(None)
        global_state = next((s for s in all_states if s.provider_name == "__global__"), None)
        
        if global_state and (now - global_state.last_reset_time) <= timedelta(seconds=global_period):
            resets_in = (global_state.last_reset_time + timedelta(seconds=global_period)) - now
            status_dict["globalStatus"] = {"limit": global_limit, "periodSeconds": global_period, "count": global_state.request_count, "resetsInSeconds": round(resets_in.total_seconds())}
        else:
            status_dict["globalStatus"] = {"limit": global_limit, "periodSeconds": global_period, "count": 0, "resetsInSeconds": global_period}
            
        # 各源状态
        for scraper in all_scrapers:
            provider_name = scraper['providerName']
            limit, period = await self._get_limit_and_period(provider_name)
            state = next((s for s in all_states if s.provider_name == provider_name), None)
            
            if state and (now - state.last_reset_time) <= timedelta(seconds=period):
                resets_in = (state.last_reset_time + timedelta(seconds=period)) - now
                status_dict["providerStatus"][provider_name] = {"limit": limit, "periodSeconds": period, "count": state.request_count, "resetsInSeconds": round(resets_in.total_seconds())}
            else:
                 status_dict["providerStatus"][provider_name] = {"limit": limit, "periodSeconds": period, "count": 0, "resetsInSeconds": period}
        
        return status_dict