"""
PassKey (WebAuthn) 凭证的 CRUD 操作
"""

import logging
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from ..orm_models import UserPassKey
from src.core.timezone import get_now

logger = logging.getLogger(__name__)


async def get_passkeys_by_user_id(session: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    """获取用户的所有 PassKey 凭证"""
    stmt = select(UserPassKey).where(UserPassKey.userId == user_id).order_by(UserPassKey.createdAt.desc())
    result = await session.execute(stmt)
    passkeys = result.scalars().all()
    return [
        {
            "id": pk.id,
            "userId": pk.userId,
            "credentialId": pk.credentialId,
            "publicKey": pk.publicKey,
            "signCount": pk.signCount,
            "deviceName": pk.deviceName,
            "transports": pk.transports,
            "createdAt": pk.createdAt,
            "lastUsedAt": pk.lastUsedAt,
        }
        for pk in passkeys
    ]


async def get_passkey_by_credential_id(session: AsyncSession, credential_id: str) -> Optional[Dict[str, Any]]:
    """通过凭证ID查找 PassKey"""
    stmt = select(UserPassKey).where(UserPassKey.credentialId == credential_id)
    result = await session.execute(stmt)
    pk = result.scalar_one_or_none()
    if pk:
        return {
            "id": pk.id,
            "userId": pk.userId,
            "credentialId": pk.credentialId,
            "publicKey": pk.publicKey,
            "signCount": pk.signCount,
            "deviceName": pk.deviceName,
            "transports": pk.transports,
            "createdAt": pk.createdAt,
            "lastUsedAt": pk.lastUsedAt,
        }
    return None


async def create_passkey(
    session: AsyncSession,
    user_id: int,
    credential_id: str,
    public_key: str,
    sign_count: int,
    device_name: Optional[str] = None,
    transports: Optional[str] = None,
) -> int:
    """创建新的 PassKey 凭证"""
    new_passkey = UserPassKey(
        userId=user_id,
        credentialId=credential_id,
        publicKey=public_key,
        signCount=sign_count,
        deviceName=device_name,
        transports=transports,
        createdAt=get_now(),
    )
    session.add(new_passkey)
    await session.commit()
    await session.refresh(new_passkey)
    return new_passkey.id


async def update_passkey_sign_count(session: AsyncSession, credential_id: str, new_sign_count: int):
    """更新 PassKey 的签名计数器和最后使用时间"""
    stmt = (
        update(UserPassKey)
        .where(UserPassKey.credentialId == credential_id)
        .values(signCount=new_sign_count, lastUsedAt=get_now())
    )
    await session.execute(stmt)
    await session.commit()


async def rename_passkey(session: AsyncSession, passkey_id: int, user_id: int, device_name: str) -> bool:
    """重命名 PassKey"""
    stmt = (
        update(UserPassKey)
        .where(UserPassKey.id == passkey_id, UserPassKey.userId == user_id)
        .values(deviceName=device_name)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0


async def delete_passkey(session: AsyncSession, passkey_id: int, user_id: int) -> bool:
    """删除 PassKey"""
    stmt = delete(UserPassKey).where(UserPassKey.id == passkey_id, UserPassKey.userId == user_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0


async def count_passkeys_by_user_id(session: AsyncSession, user_id: int) -> int:
    """获取用户的 PassKey 数量"""
    stmt = select(UserPassKey).where(UserPassKey.userId == user_id)
    result = await session.execute(stmt)
    return len(result.scalars().all())
