"""
Token Log相关的CRUD操作
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, case, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from ..orm_models import TokenAccessLog, UaRule
from .. import models
from ..timezone import get_now

logger = logging.getLogger(__name__)


async def create_token_access_log(session: AsyncSession, token_id: int, ip_address: str, user_agent: Optional[str], log_status: str, path: Optional[str] = None):
    new_log = TokenAccessLog(
        tokenId=token_id, 
        ipAddress=ip_address, 
        userAgent=user_agent, 
        status=log_status, 
        path=path, 
        accessTime=get_now())
    session.add(new_log)
    await session.commit()


async def get_token_access_logs(session: AsyncSession, token_id: int) -> List[Dict[str, Any]]:
    stmt = select(TokenAccessLog).where(TokenAccessLog.tokenId == token_id).order_by(TokenAccessLog.accessTime.desc()).limit(200)
    result = await session.execute(stmt)
    return [
        {"ipAddress": log.ipAddress, "userAgent": log.userAgent, "accessTime": log.accessTime, "status": log.status, "path": log.path}
        for log in result.scalars()
    ]


async def get_ua_rules(session: AsyncSession) -> List[Dict[str, Any]]:
    stmt = select(UaRule).order_by(UaRule.createdAt.desc())
    result = await session.execute(stmt)
    return [{"id": r.id, "uaString": r.uaString, "createdAt": r.createdAt} for r in result.scalars()]


async def add_ua_rule(session: AsyncSession, ua_string: str) -> int:
    new_rule = UaRule(uaString=ua_string, createdAt=get_now())
    session.add(new_rule)
    await session.commit()
    return new_rule.id


async def delete_ua_rule(session: AsyncSession, rule_id: int) -> bool:
    rule = await session.get(UaRule, rule_id)
    if rule:
        await session.delete(rule)
        await session.commit()
        return True
    return False

