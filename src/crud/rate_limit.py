"""
Rate Limit相关的CRUD操作
"""

from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, case, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from ..orm_models import RateLimitState
from .. import models
from ..log_manager import logger
from ..timezone import get_now


async def get_or_create_rate_limit_state(session: AsyncSession, provider_name: str) -> RateLimitState:
    """获取或创建特定提供商的速率限制状态。"""
    stmt = select(RateLimitState).where(RateLimitState.providerName == provider_name)
    result = await session.execute(stmt)
    state = result.scalar_one_or_none()
    if not state:
        state = RateLimitState(
            providerName=provider_name,
            requestCount=0,
            lastResetTime=get_now() # lastResetTime is explicitly set here
        )
        session.add(state)
        await session.flush()

    # 关键修复：无论数据来自数据库还是新创建，都确保返回的时间是 naive 的。
    # 这可以解决 PostgreSQL 驱动返回带时区时间对象的问题。
    if state.lastResetTime and state.lastResetTime.tzinfo:
        state.lastResetTime = state.lastResetTime.replace(tzinfo=None)

    return state


async def get_all_rate_limit_states(session: AsyncSession) -> List[RateLimitState]:
    """获取所有速率限制状态。"""
    result = await session.execute(select(RateLimitState))
    states = result.scalars().all()
    return states


async def reset_all_rate_limit_states(session: AsyncSession):
    """
    重置所有速率限制状态的请求计数和重置时间。
    """
    # 修正：从批量更新改为获取并更新对象。
    # 这确保了会话中已加载的ORM对象的状态能与数据库同步，
    # 解决了在 expire_on_commit=False 的情况下，对象状态陈旧的问题。
    states = (await session.execute(select(RateLimitState))).scalars().all()
    now_naive = get_now()
    for state in states:
        state.requestCount = 0
        state.lastResetTime = now_naive
    # The commit will be handled by the calling function (e.g., RateLimiter.check)


async def increment_rate_limit_count(session: AsyncSession, provider_name: str):
    """为指定的提供商增加请求计数。如果状态不存在，则会创建它。"""
    state = await get_or_create_rate_limit_state(session, provider_name)
    state.requestCount += 1

# --- Database Maintenance ---

