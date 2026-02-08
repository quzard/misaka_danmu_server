"""
External Log相关的CRUD操作
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, case, or_, and_, update, delete
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from ..orm_models import ExternalApiLog
from .. import models
from src.core.timezone import get_now

logger = logging.getLogger(__name__)


async def create_external_api_log(
    session: AsyncSession,
    ip_address: str,
    endpoint: str,
    status_code: int,
    message: Optional[str] = None,
    request_headers: Optional[str] = None,
    request_body: Optional[str] = None,
) -> ExternalApiLog:
    """创建一个外部API访问日志，返回日志对象（含id）。"""
    new_log = ExternalApiLog(
        accessTime=get_now(),
        ipAddress=ip_address,
        endpoint=endpoint,
        statusCode=status_code,
        message=message,
        requestHeaders=request_headers,
        requestBody=request_body,
    )
    session.add(new_log)
    await session.commit()
    await session.refresh(new_log)
    return new_log


async def update_external_api_log_response(
    session: AsyncSession,
    log_id: int,
    status_code: Optional[int] = None,
    response_headers: Optional[str] = None,
    response_body: Optional[str] = None,
):
    """更新外部API访问日志的响应信息。"""
    stmt = select(ExternalApiLog).where(ExternalApiLog.id == log_id)
    result = await session.execute(stmt)
    log_entry = result.scalar_one_or_none()
    if log_entry:
        if status_code is not None:
            log_entry.statusCode = status_code
        if response_headers is not None:
            log_entry.responseHeaders = response_headers
        if response_body is not None:
            log_entry.responseBody = response_body
        await session.commit()


async def get_external_api_logs(session: AsyncSession, limit: int = 100) -> List[ExternalApiLog]:
    stmt = select(ExternalApiLog).order_by(ExternalApiLog.accessTime.desc()).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()

# initialize_configs - 已迁移到 crud/config.py

# --- Rate Limiter CRUD ---

