import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import crud
from .config_manager import ConfigManager
from .scraper_manager import ScraperManager

logger = logging.getLogger(__name__)

class RateLimitExceededError(Exception):
    """当达到速率限制时引发的自定义异常。"""
    def __init__(self, message, retry_after_seconds):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds

class RateLimiter:
    """管理全局和各源的下载速率限制，基于成功下载的分集数量。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], config_manager: ConfigManager, scraper_manager: ScraperManager):
        self._session_factory = session_factory
        self._config_manager = config_manager
        self._scraper_manager = scraper_manager
        self._period_map = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        self.logger = logging.getLogger(self.__class__.__name__)

    async def _get_rate_limit_config(self, provider_name: str) -> tuple[int, str, str]:
        """
        确定要使用的流控规则（硬编码的独立规则或UI设置的全局规则）。
        返回 (限制次数, 周期字符串, 用于数据库的键名)。
        """
        try:
            scraper = self._scraper_manager.get_scraper(provider_name)
            limit = scraper.rate_limit_count
            period_str = scraper.rate_limit_period
        except (ValueError, AttributeError):
            limit = 0
            period_str = "hour"

        if limit > 0:
            self.logger.debug(f"正在为 '{provider_name}' 应用独立流控: 每 {period_str} {limit} 次。")
            return limit, period_str, provider_name
        
        global_enabled_str = await self._config_manager.get("globalRateLimitEnabled", "false")
        if global_enabled_str.lower() == 'true':
            limit_str = await self._config_manager.get("globalRateLimitCount", "0")
            limit = int(limit_str) if limit_str.isdigit() else 0
            period_str = await self._config_manager.get("globalRateLimitPeriod", "hour")
            self.logger.debug(f"'{provider_name}' 遵循全局流控: 每 {period_str} {limit} 次。")
            return limit, period_str, "__global__"
        
        self.logger.debug(f"'{provider_name}' 未启用任何流控。")
        return 0, "hour", ""

    async def check(self, provider_name: str):
        """
        检查是否允许为指定源下载一个新分集。
        如果超出限制，则引发 RateLimitExceededError。
        此方法不增加计数器。
        """
        limit, period_str, rate_limit_key = await self._get_rate_limit_config(provider_name)

        if not rate_limit_key or limit <= 0:
            return

        period_seconds = self._period_map.get(period_str, 3600)

        async with self._session_factory() as session:
            state = await crud.get_rate_limit_state(session, rate_limit_key)
            now = datetime.now(timezone.utc)
            
            if not state:
                return

            if (now - state.lastResetTime).total_seconds() >= period_seconds:
                return

            if state.requestCount >= limit:
                retry_after = period_seconds - (now - state.lastResetTime).total_seconds()
                msg = f"'{rate_limit_key}' 的下载流控已达到上限 ({state.requestCount}/{limit})。"
                self.logger.warning(msg)
                raise RateLimitExceededError(msg, retry_after_seconds=retry_after)

    async def increment(self, provider_name: str):
        """
        为指定源增加下载计数。
        此方法应在成功下载一个分集的弹幕后调用。
        """
        limit, period_str, rate_limit_key = await self._get_rate_limit_config(provider_name)

        if not rate_limit_key or limit <= 0:
            return

        period_seconds = self._period_map.get(period_str, 3600)

        async with self._session_factory() as session:
            state = await crud.get_rate_limit_state(session, rate_limit_key)
            now = datetime.now(timezone.utc)

            if not state or (now - state.lastResetTime).total_seconds() >= period_seconds:
                await crud.reset_rate_limit_state(session, rate_limit_key)
            else:
                await crud.increment_rate_limit_count(session, rate_limit_key)
            
            await session.commit()
            self.logger.debug(f"已为 '{rate_limit_key}' 增加下载流控计数。")

    async def get_status(self) -> Dict[str, Any]:
        """获取所有速率限制器的当前状态。"""
        async with self._session_factory() as session:
            all_states = await crud.get_all_rate_limit_states(session)
            all_scrapers = await crud.get_all_scraper_settings(session)
        
        status_dict: Dict[str, Any] = {"globalStatus": {}, "providerStatus": []}
        now = datetime.now(timezone.utc)

        # 全局状态
        global_enabled_str = await self._config_manager.get("globalRateLimitEnabled", "false")
        global_enabled = global_enabled_str.lower() == 'true'
        global_limit_str = await self._config_manager.get("globalRateLimitCount", "0")
        global_limit = int(global_limit_str) if global_limit_str.isdigit() else 0
        global_period_str = await self._config_manager.get("globalRateLimitPeriod", "hour")
        global_period_seconds = self._period_map.get(global_period_str, 3600)

        global_state = next((s for s in all_states if s.providerName == "__global__"), None)
        
        global_count = 0
        resets_in_seconds = global_period_seconds
        if global_state and (now - global_state.lastResetTime).total_seconds() < global_period_seconds:
            global_count = global_state.requestCount
            resets_in_seconds = global_period_seconds - (now - global_state.lastResetTime).total_seconds()

        status_dict["globalStatus"] = {"enabled": global_enabled, "limit": global_limit, "periodSeconds": global_period_seconds, "count": global_count, "resetsInSeconds": round(resets_in_seconds)}
            
        # 各源状态
        for scraper in all_scrapers:
            provider_name = scraper['providerName']
            limit = scraper.get('rateLimitCount', 0) or 0
            period_str = scraper.get('rateLimitPeriod', 'hour') or 'hour'
            period_seconds = self._period_map.get(period_str, 3600)
            state = next((s for s in all_states if s.providerName == provider_name), None)
            
            count = 0
            resets_in = period_seconds
            if state and (now - state.lastResetTime).total_seconds() < period_seconds:
                count = state.requestCount
                resets_in = period_seconds - (now - state.lastResetTime).total_seconds()
            
            status_dict["providerStatus"].append({"providerName": provider_name, "limit": limit, "periodSeconds": period_seconds, "count": count, "resetsInSeconds": round(resets_in)})
        
        return status_dict