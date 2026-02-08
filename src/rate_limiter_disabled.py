import logging
from typing import Tuple

from src.db import crud

logger = logging.getLogger(__name__)


class RateLimitExceededError(Exception):
    """保留原异常类型以兼容现有捕获逻辑。"""

    def __init__(self, message: str = "", retry_after_seconds: float = 0):
        super().__init__(message or "Rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class RateLimiter:
    """
    关闭限速的实现：
    - check()/check_fallback(): 永远放行；仅确保状态存在。
    - increment()/increment_fallback(): 只做计数，便于状态页展示；不做限制。
    - get_global_limit_status(): 始终返回未触发限速。
    - 暴露 enabled/global_limit/global_period_seconds/fallback_limit/_verification_failed 以兼容 UI。
    """

    def __init__(self, session_factory, scraper_manager):
        self._session_factory = session_factory
        self._scraper_manager = scraper_manager

        self.enabled = False
        self.global_limit = 10000
        self.global_period_seconds = 3600
        self.fallback_limit = 50
        self._verification_failed = False

    @staticmethod
    def _get_fallback_key(fallback_type: str) -> str:
        if fallback_type == "match":
            return "__fallback_match__"
        if fallback_type == "search":
            return "__fallback_search__"
        return f"__fallback_{fallback_type}__"

    async def check(self, provider_name: str) -> None:
        try:
            async with self._session_factory() as session:
                target = "__global__" if provider_name in ("__control_api_status_check__", "__ui_status_check__") else provider_name
                await crud.get_or_create_rate_limit_state(session, target)
                await session.commit()
        except Exception as e:
            logger.debug(f"RateLimiterDisabled.check() 忽略异常: {e}")

    async def increment(self, provider_name: str) -> None:
        try:
            async with self._session_factory() as session:
                await crud.increment_rate_limit_count(session, provider_name)
                await crud.increment_rate_limit_count(session, "__global__")
                await session.commit()
        except Exception as e:
            logger.debug(f"RateLimiterDisabled.increment() 忽略异常: {e}")

    async def check_fallback(self, fallback_type: str, provider_name: str) -> None:
        try:
            async with self._session_factory() as session:
                await crud.get_or_create_rate_limit_state(session, self._get_fallback_key(fallback_type))
                await crud.get_or_create_rate_limit_state(session, provider_name)
                await session.commit()
        except Exception as e:
            logger.debug(f"RateLimiterDisabled.check_fallback() 忽略异常: {e}")

    async def increment_fallback(self, fallback_type: str, provider_name: str) -> None:
        try:
            async with self._session_factory() as session:
                await crud.increment_rate_limit_count(session, self._get_fallback_key(fallback_type))
                await crud.increment_rate_limit_count(session, provider_name)
                await session.commit()
        except Exception as e:
            logger.debug(f"RateLimiterDisabled.increment_fallback() 忽略异常: {e}")

    async def get_global_limit_status(self) -> Tuple[bool, float]:
        return False, 0.0

