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
from ..timezone import get_now

logger = logging.getLogger(__name__)


async def create_external_api_log(session: AsyncSession, ip_address: str, endpoint: str, status_code: int, message: Optional[str] = None):
    """创建一个外部API访问日志。"""
    new_log = ExternalApiLog(
        accessTime=get_now(),
        ipAddress=ip_address,
        endpoint=endpoint,
        statusCode=status_code,
        message=message
    )
    session.add(new_log)
    await session.commit()


async def get_external_api_logs(session: AsyncSession, limit: int = 100) -> List[ExternalApiLog]:
    stmt = select(ExternalApiLog).order_by(ExternalApiLog.accessTime.desc()).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()

# initialize_configs - 已迁移到 crud/config.py

# --- Rate Limiter CRUD ---

