"""
AI 调用统计 CRUD 操作
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_, Integer

from ..orm_models import AIMetricsLog
from src.core import get_now

logger = logging.getLogger(__name__)


async def create_ai_metrics_log(
    session: AsyncSession,
    timestamp: datetime,
    method: str,
    success: bool,
    duration_ms: int,
    tokens_used: int,
    model: str,
    error: Optional[str] = None,
    cache_hit: bool = False
) -> int:
    """创建 AI 调用日志记录"""
    log = AIMetricsLog(
        timestamp=timestamp,
        method=method,
        success=success,
        durationMs=duration_ms,
        tokensUsed=tokens_used,
        model=model,
        error=error,
        cacheHit=cache_hit
    )
    session.add(log)
    await session.commit()
    return log.id


async def get_ai_metrics_stats(session: AsyncSession, hours: int = 24) -> Dict[str, Any]:
    """
    获取 AI 调用统计数据
    
    Args:
        session: 数据库会话
        hours: 统计最近多少小时的数据
    
    Returns:
        统计数据字典
    """
    cutoff = get_now() - timedelta(hours=hours)
    
    # 查询基础统计
    stmt = select(
        func.count(AIMetricsLog.id).label('total_calls'),
        func.sum(func.cast(AIMetricsLog.success, Integer)).label('success_count'),
        func.sum(AIMetricsLog.tokensUsed).label('total_tokens'),
        func.sum(AIMetricsLog.durationMs).label('total_duration'),
        func.sum(func.cast(AIMetricsLog.cacheHit, Integer)).label('cache_hits')
    ).where(AIMetricsLog.timestamp > cutoff)
    
    result = await session.execute(stmt)
    row = result.first()
    
    if not row or not row.total_calls:
        return {
            "period_hours": hours,
            "total_calls": 0,
            "success_rate": 0.0,
            "total_tokens": 0,
            "avg_duration_ms": 0.0,
            "cache_hit_rate": 0.0,
            "by_method": {},
            "errors": []
        }
    
    total_calls = row.total_calls or 0
    success_count = row.success_count or 0
    total_tokens = row.total_tokens or 0
    total_duration = row.total_duration or 0
    cache_hits = row.cache_hits or 0
    
    # 按方法分组统计
    by_method = await _get_stats_by_method(session, cutoff)
    
    # 获取最近的错误
    errors = await _get_recent_errors(session, cutoff, limit=10)
    
    return {
        "period_hours": hours,
        "total_calls": total_calls,
        "success_rate": success_count / total_calls if total_calls > 0 else 0.0,
        "total_tokens": total_tokens,
        "avg_duration_ms": total_duration / total_calls if total_calls > 0 else 0.0,
        "cache_hit_rate": cache_hits / total_calls if total_calls > 0 else 0.0,
        "by_method": by_method,
        "errors": errors
    }


async def _get_stats_by_method(session: AsyncSession, cutoff: datetime) -> Dict[str, Any]:
    """按方法分组统计"""
    from sqlalchemy import Integer

    stmt = select(
        AIMetricsLog.method,
        func.count(AIMetricsLog.id).label('calls'),
        func.sum(func.cast(AIMetricsLog.success, Integer)).label('success'),
        func.sum(AIMetricsLog.tokensUsed).label('tokens'),
        func.sum(AIMetricsLog.durationMs).label('duration'),
        func.sum(func.cast(AIMetricsLog.cacheHit, Integer)).label('cache_hits')
    ).where(AIMetricsLog.timestamp > cutoff).group_by(AIMetricsLog.method)

    result = await session.execute(stmt)
    rows = result.all()

    by_method = {}
    for row in rows:
        calls = row.calls or 0
        if calls > 0:
            by_method[row.method] = {
                "calls": calls,
                "success_rate": (row.success or 0) / calls,
                "total_tokens": row.tokens or 0,
                "avg_duration_ms": (row.duration or 0) / calls,
                "cache_hit_rate": (row.cache_hits or 0) / calls
            }

    return by_method


async def _get_recent_errors(session: AsyncSession, cutoff: datetime, limit: int = 10) -> List[Dict[str, Any]]:
    """获取最近的错误记录"""
    stmt = select(
        AIMetricsLog.timestamp,
        AIMetricsLog.method,
        AIMetricsLog.error
    ).where(
        and_(AIMetricsLog.timestamp > cutoff, AIMetricsLog.success == False)
    ).order_by(AIMetricsLog.timestamp.desc()).limit(limit)

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "method": row.method,
            "error": row.error
        }
        for row in rows
    ]


async def cleanup_old_ai_metrics(session: AsyncSession, days: int = 30) -> int:
    """
    清理旧的 AI 调用日志

    Args:
        session: 数据库会话
        days: 保留最近多少天的数据

    Returns:
        删除的记录数
    """
    cutoff = get_now() - timedelta(days=days)

    stmt = delete(AIMetricsLog).where(AIMetricsLog.timestamp < cutoff)
    result = await session.execute(stmt)
    await session.commit()

    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info(f"清理了 {deleted_count} 条旧的 AI 调用日志（{days} 天前）")

    return deleted_count


async def get_ai_metrics_summary(session: AsyncSession) -> Dict[str, Any]:
    """
    获取 AI 调用的总体摘要（所有时间）

    Returns:
        总体统计摘要
    """
    stmt = select(
        func.count(AIMetricsLog.id).label('total_calls'),
        func.sum(AIMetricsLog.tokensUsed).label('total_tokens'),
        func.min(AIMetricsLog.timestamp).label('first_call'),
        func.max(AIMetricsLog.timestamp).label('last_call')
    )

    result = await session.execute(stmt)
    row = result.first()

    return {
        "total_calls_all_time": row.total_calls or 0,
        "total_tokens_all_time": row.total_tokens or 0,
        "first_call": row.first_call.isoformat() if row.first_call else None,
        "last_call": row.last_call.isoformat() if row.last_call else None
    }

