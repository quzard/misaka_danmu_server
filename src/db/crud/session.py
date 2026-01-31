"""
用户会话相关的CRUD操作
"""

import logging
from datetime import timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from ..orm_models import UserSession
from src.core import get_now

logger = logging.getLogger(__name__)


async def create_user_session(
    session: AsyncSession,
    user_id: int,
    jti: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    expires_minutes: Optional[int] = None
) -> int:
    """创建新的用户会话"""
    now = get_now()
    expires_at = None
    if expires_minutes and expires_minutes != -1:
        expires_at = now + timedelta(minutes=expires_minutes)
    
    new_session = UserSession(
        userId=user_id,
        jti=jti,
        ipAddress=ip_address,
        userAgent=user_agent[:500] if user_agent and len(user_agent) > 500 else user_agent,
        createdAt=now,
        lastUsedAt=now,
        expiresAt=expires_at,
        isRevoked=False
    )
    session.add(new_session)
    await session.commit()
    return new_session.id


async def get_session_by_jti(session: AsyncSession, jti: str) -> Optional[Dict[str, Any]]:
    """通过 JWT ID 获取会话"""
    stmt = select(UserSession).where(UserSession.jti == jti)
    result = await session.execute(stmt)
    user_session = result.scalar_one_or_none()
    if user_session:
        return {
            "id": user_session.id,
            "userId": user_session.userId,
            "jti": user_session.jti,
            "ipAddress": user_session.ipAddress,
            "userAgent": user_session.userAgent,
            "createdAt": user_session.createdAt,
            "lastUsedAt": user_session.lastUsedAt,
            "expiresAt": user_session.expiresAt,
            "isRevoked": user_session.isRevoked
        }
    return None


async def validate_session(session: AsyncSession, jti: str) -> bool:
    """验证会话是否有效（未撤销且未过期）"""
    stmt = select(UserSession).where(
        UserSession.jti == jti,
        UserSession.isRevoked == False
    )
    result = await session.execute(stmt)
    user_session = result.scalar_one_or_none()
    
    if not user_session:
        return False
    
    # 检查是否过期
    if user_session.expiresAt and user_session.expiresAt < get_now():
        return False
    
    return True


async def update_session_last_used(session: AsyncSession, jti: str):
    """更新会话的最后使用时间"""
    stmt = update(UserSession).where(UserSession.jti == jti).values(lastUsedAt=get_now())
    await session.execute(stmt)
    await session.commit()


async def get_user_sessions(session: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    """获取用户的所有会话"""
    stmt = select(UserSession).where(
        UserSession.userId == user_id
    ).order_by(UserSession.createdAt.desc())
    
    result = await session.execute(stmt)
    sessions = result.scalars().all()
    
    return [
        {
            "id": s.id,
            "userId": s.userId,
            "jti": s.jti,
            "ipAddress": s.ipAddress,
            "userAgent": s.userAgent,
            "createdAt": s.createdAt,
            "lastUsedAt": s.lastUsedAt,
            "expiresAt": s.expiresAt,
            "isRevoked": s.isRevoked
        }
        for s in sessions
    ]


async def revoke_session(session: AsyncSession, session_id: int, user_id: int) -> bool:
    """撤销指定会话"""
    stmt = update(UserSession).where(
        UserSession.id == session_id,
        UserSession.userId == user_id
    ).values(isRevoked=True)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0


async def revoke_session_by_jti(session: AsyncSession, jti: str) -> bool:
    """通过 jti 撤销会话"""
    stmt = update(UserSession).where(UserSession.jti == jti).values(isRevoked=True)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0


async def delete_session_by_jti(session: AsyncSession, jti: str) -> bool:
    """通过 jti 删除会话（用于白名单会话的重建）"""
    stmt = delete(UserSession).where(UserSession.jti == jti)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0


async def revoke_other_sessions(session: AsyncSession, user_id: int, current_jti: str) -> int:
    """撤销用户的所有其他会话"""
    stmt = update(UserSession).where(
        UserSession.userId == user_id,
        UserSession.jti != current_jti,
        UserSession.isRevoked == False
    ).values(isRevoked=True)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount


async def cleanup_expired_sessions(session: AsyncSession) -> int:
    """清理过期和已撤销的会话"""
    now = get_now()
    stmt = delete(UserSession).where(
        (UserSession.isRevoked == True) |
        ((UserSession.expiresAt != None) & (UserSession.expiresAt < now))
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount

