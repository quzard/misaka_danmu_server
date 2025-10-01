import logging

from . import crud

logger = logging.getLogger(__name__)


class RateLimitExceededError(Exception):
    """保留原异常类型以兼容现有捕获逻辑。"""

    def __init__(self, message: str = "", retry_after_seconds: float = 0):
        super().__init__(message or "Rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class RateLimiter:
    """
    关闭限速的实现：
    - check(): 永远放行；仅确保状态存在。
    - increment(): 只做计数，便于状态页展示；不做限制。
    - 暴露 enabled/global_limit/global_period_seconds/_verification_failed 以兼容 UI。
    """

    def __init__(self, session_factory, scraper_manager):
        self._session_factory = session_factory
        self._scraper_manager = scraper_manager

        self.enabled = False
        self.global_limit = 0
        self.global_period_seconds = 3600
        self._verification_failed = False

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

