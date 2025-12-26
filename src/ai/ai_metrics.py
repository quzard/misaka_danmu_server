"""
AI 调用监控和统计模块

提供 AI 调用的性能监控、成本统计和错误追踪功能
支持数据持久化到数据库
"""

import logging
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class AICallMetrics:
    """AI 调用指标"""
    timestamp: datetime
    method: str  # select_best_match, recognize_title, validate_aliases, etc.
    success: bool
    duration_ms: int
    tokens_used: int
    model: str
    error: Optional[str] = None
    cache_hit: bool = False


class AIMetricsCollector:
    """AI 指标收集器（支持数据库持久化）"""

    def __init__(self, max_history: int = 1000, db_session_factory: Optional[Callable] = None):
        """
        初始化指标收集器

        Args:
            max_history: 内存中最大保留的历史记录数（用于快速查询）
            db_session_factory: 数据库会话工厂函数（用于持久化）
        """
        self.metrics: List[AICallMetrics] = []
        self.max_history = max_history
        self.logger = logging.getLogger(self.__class__.__name__)
        self._db_session_factory = db_session_factory
        self._pending_writes: List[AICallMetrics] = []  # 待写入数据库的记录
        self._write_lock = asyncio.Lock()

    def set_db_session_factory(self, factory: Callable):
        """设置数据库会话工厂（延迟初始化）"""
        self._db_session_factory = factory

    def record(self, metric: AICallMetrics):
        """
        记录一次 AI 调用（同步方法，异步写入数据库）

        Args:
            metric: AI 调用指标
        """
        # 添加到内存列表
        self.metrics.append(metric)

        # 限制内存中的历史记录数量
        if len(self.metrics) > self.max_history:
            self.metrics = self.metrics[-self.max_history:]

        # 添加到待写入队列
        self._pending_writes.append(metric)

        # 异步写入数据库
        if self._db_session_factory:
            asyncio.create_task(self._write_to_db(metric))

        # 记录到日志
        if metric.success:
            self.logger.debug(
                f"AI调用成功: {metric.method} | "
                f"耗时: {metric.duration_ms}ms | "
                f"Tokens: {metric.tokens_used} | "
                f"缓存: {'命中' if metric.cache_hit else '未命中'}"
            )
        else:
            self.logger.warning(
                f"AI调用失败: {metric.method} | "
                f"耗时: {metric.duration_ms}ms | "
                f"错误: {metric.error}"
            )

    async def _write_to_db(self, metric: AICallMetrics):
        """异步写入数据库"""
        if not self._db_session_factory:
            return

        try:
            async with self._write_lock:
                async with self._db_session_factory() as session:
                    from ..crud.ai_metrics import create_ai_metrics_log
                    await create_ai_metrics_log(
                        session=session,
                        timestamp=metric.timestamp,
                        method=metric.method,
                        success=metric.success,
                        duration_ms=metric.duration_ms,
                        tokens_used=metric.tokens_used,
                        model=metric.model,
                        error=metric.error,
                        cache_hit=metric.cache_hit
                    )
                # 从待写入队列移除
                if metric in self._pending_writes:
                    self._pending_writes.remove(metric)
        except Exception as e:
            self.logger.error(f"写入 AI 调用日志到数据库失败: {e}")
    
    def get_stats(self, hours: int = 24) -> Dict:
        """
        获取统计数据
        
        Args:
            hours: 统计最近多少小时的数据
        
        Returns:
            统计数据字典
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [m for m in self.metrics if m.timestamp > cutoff]
        
        if not recent:
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
        
        # 基础统计
        total_calls = len(recent)
        success_count = sum(1 for m in recent if m.success)
        total_tokens = sum(m.tokens_used for m in recent)
        total_duration = sum(m.duration_ms for m in recent)
        cache_hits = sum(1 for m in recent if m.cache_hit)
        
        # 按方法分组统计
        by_method = self._group_by_method(recent)
        
        # 错误统计
        errors = [
            {
                "timestamp": m.timestamp.isoformat(),
                "method": m.method,
                "error": m.error
            }
            for m in recent if not m.success
        ]
        
        return {
            "period_hours": hours,
            "total_calls": total_calls,
            "success_rate": success_count / total_calls,
            "total_tokens": total_tokens,
            "avg_duration_ms": total_duration / total_calls,
            "cache_hit_rate": cache_hits / total_calls,
            "by_method": by_method,
            "errors": errors[-10:]  # 最近10个错误
        }
    
    def _group_by_method(self, metrics: List[AICallMetrics]) -> Dict:
        """按方法分组统计"""
        grouped = defaultdict(lambda: {
            "calls": 0,
            "success": 0,
            "tokens": 0,
            "duration_ms": 0,
            "cache_hits": 0
        })
        
        for m in metrics:
            g = grouped[m.method]
            g["calls"] += 1
            if m.success:
                g["success"] += 1
            g["tokens"] += m.tokens_used
            g["duration_ms"] += m.duration_ms
            if m.cache_hit:
                g["cache_hits"] += 1
        
        # 计算平均值和成功率
        result = {}
        for method, stats in grouped.items():
            result[method] = {
                "calls": stats["calls"],
                "success_rate": stats["success"] / stats["calls"],
                "total_tokens": stats["tokens"],
                "avg_duration_ms": stats["duration_ms"] / stats["calls"],
                "cache_hit_rate": stats["cache_hits"] / stats["calls"]
            }
        
        return result

