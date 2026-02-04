"""
Api Token相关的CRUD操作
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, case, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from ..orm_models import ApiToken, TokenAccessLog, UaRule
from .. import models, orm_models
from src.core.timezone import get_now

logger = logging.getLogger(__name__)


async def get_all_api_tokens(session: AsyncSession) -> List[Dict[str, Any]]:
    stmt = select(ApiToken).order_by(ApiToken.createdAt.desc())
    result = await session.execute(stmt)
    return [
        {"id": t.id, "name": t.name, "token": t.token, "isEnabled": t.isEnabled, "expiresAt": t.expiresAt, "createdAt": t.createdAt, "dailyCallLimit": t.dailyCallLimit, "dailyCallCount": t.dailyCallCount}
        for t in result.scalars()
    ]


async def get_api_token_by_id(session: AsyncSession, token_id: int) -> Optional[Dict[str, Any]]:
    token = await session.get(ApiToken, token_id)
    if token:
        return {"id": token.id, "name": token.name, "token": token.token, "isEnabled": token.isEnabled, "expiresAt": token.expiresAt, "createdAt": token.createdAt, "dailyCallLimit": token.dailyCallLimit, "dailyCallCount": token.dailyCallCount}
    return None


async def get_api_token_by_token_str(session: AsyncSession, token_str: str) -> Optional[Dict[str, Any]]:
    stmt = select(ApiToken).where(ApiToken.token == token_str)
    result = await session.execute(stmt)
    token = result.scalar_one_or_none()
    if token:
        return {"id": token.id, "name": token.name, "token": token.token, "isEnabled": token.isEnabled, "expiresAt": token.expiresAt, "createdAt": token.createdAt, "dailyCallLimit": token.dailyCallLimit, "dailyCallCount": token.dailyCallCount}
    return None


async def create_api_token(session: AsyncSession, name: str, token: str, validityPeriod: str, daily_call_limit: int) -> int:
    """创建新的API Token，如果名称已存在则会失败。"""
    # 检查名称是否已存在
    existing_token = await session.execute(select(ApiToken).where(ApiToken.name == name))
    if existing_token.scalar_one_or_none():
        raise ValueError(f"名称为 '{name}' 的Token已存在。")
    
    expires_at = None
    if validityPeriod != "permanent":
        days = int(validityPeriod.replace('d', '')) # type: ignore
        # 修正：确保写入数据库的时间是 naive 的
        expires_at = get_now() + timedelta(days=days)
    new_token = ApiToken(
        name=name, token=token, 
        expiresAt=expires_at, 
        createdAt=get_now(),
        dailyCallLimit=daily_call_limit
    )
    session.add(new_token)
    await session.commit()
    return new_token.id


async def update_api_token(
    session: AsyncSession,
    token_id: int,
    name: str,
    daily_call_limit: int,
    validity_period: str
) -> bool:
    """更新API Token的名称、调用上限和有效期。"""
    token = await session.get(orm_models.ApiToken, token_id)
    if not token:
        return False

    token.name = name
    token.dailyCallLimit = daily_call_limit

    if validity_period != 'custom':
        if validity_period == 'permanent':
            token.expiresAt = None
        else:
            try:
                days = int(validity_period.replace('d', ''))
                token.expiresAt = get_now() + timedelta(days=days)
            except (ValueError, TypeError):
                logger.warning(f"更新Token时收到无效的有效期格式: '{validity_period}'")

    await session.commit()
    return True


async def delete_api_token(session: AsyncSession, token_id: int) -> bool:
    token = await session.get(ApiToken, token_id)
    if token:
        await session.delete(token)
        await session.commit()
        return True
    return False


async def toggle_api_token(session: AsyncSession, token_id: int) -> bool:
    token = await session.get(ApiToken, token_id)
    if token:
        token.isEnabled = not token.isEnabled
        await session.commit()
        return True
    return False


async def reset_token_counter(session: AsyncSession, token_id: int) -> bool:
    """将指定Token的每日调用次数重置为0。"""
    token = await session.get(orm_models.ApiToken, token_id)
    if not token:
        return False
    
    token.dailyCallCount = 0
    await session.commit()
    return True


async def validate_api_token(session: AsyncSession, token: str) -> Optional[Dict[str, Any]]:
    stmt = select(ApiToken).where(ApiToken.token == token, ApiToken.isEnabled == True)
    result = await session.execute(stmt)
    token_info = result.scalar_one_or_none()
    if not token_info:
        return None
    # 随着 orm_models.py 和 database.py 的修复，SQLAlchemy 现在应返回时区感知的 UTC 日期时间。
    if token_info.expiresAt:
        if token_info.expiresAt < get_now(): # Compare naive datetimes
            return None # Token 已过期
    
    # --- 新增：每日调用限制检查 ---
    now = get_now()
    current_count = token_info.dailyCallCount
    
    # 如果有上次调用记录，且不是今天，则视为计数为0
    if token_info.lastCallAt and token_info.lastCallAt.date() < now.date():
        current_count = 0
        
    if token_info.dailyCallLimit != -1 and current_count >= token_info.dailyCallLimit:
        return None # Token 已达到每日调用上限

    return {"id": token_info.id, "expiresAt": token_info.expiresAt, "dailyCallLimit": token_info.dailyCallLimit, "dailyCallCount": token_info.dailyCallCount} # type: ignore


async def increment_token_call_count(session: AsyncSession, token_id: int):
    """为指定的Token增加调用计数。"""
    token = await session.get(ApiToken, token_id)
    if not token:
        return

    # 修正：简化函数职责，现在只负责增加计数。
    # 重置逻辑已移至 validate_api_token 中，以避免竞争条件。
    token.dailyCallCount += 1
    # 总是更新最后调用时间
    token.lastCallAt = get_now()
    # 注意：这里不 commit，由调用方（API端点）来决定何时提交事务


async def reset_all_token_daily_counts(session: AsyncSession) -> int:
    """重置所有API Token的每日调用次数为0。"""
    from sqlalchemy import update
    stmt = update(ApiToken).values(dailyCallCount=0)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount

# --- UA Filter and Log Services ---

