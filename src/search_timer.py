"""搜索计时器模块 - 用于统计各搜索流程耗时"""
import time
import logging
from typing import Dict, Optional, List
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TimingResult:
    """单个计时结果"""
    name: str
    duration_ms: float
    success: bool = True
    details: Optional[str] = None


@dataclass
class SearchTimingReport:
    """搜索计时报告"""
    search_type: str  # 搜索类型：主页搜索、webhook导入、后备匹配等
    keyword: str  # 搜索关键词
    total_duration_ms: float = 0.0
    steps: List[TimingResult] = field(default_factory=list)
    
    def add_step(self, name: str, duration_ms: float, success: bool = True, details: str = None):
        """添加一个步骤的计时结果"""
        self.steps.append(TimingResult(name, duration_ms, success, details))
    
    def print_report(self, logger_instance=None):
        """打印计时报告"""
        log = logger_instance or logger
        
        log.info(f"⏱️ ═══════════════════════════════════════════════════════")
        log.info(f"⏱️ 【{self.search_type}】计时报告 - '{self.keyword}'")
        log.info(f"⏱️ ───────────────────────────────────────────────────────")
        
        for step in self.steps:
            status = "✓" if step.success else "✗"
            detail_str = f" ({step.details})" if step.details else ""
            log.info(f"⏱️   {status} {step.name}: {step.duration_ms:.0f}ms{detail_str}")
        
        log.info(f"⏱️ ───────────────────────────────────────────────────────")
        log.info(f"⏱️ 总耗时: {self.total_duration_ms:.0f}ms ({self.total_duration_ms/1000:.2f}s)")
        log.info(f"⏱️ ═══════════════════════════════════════════════════════")


class SearchTimer:
    """搜索计时器 - 用于跟踪搜索流程各阶段耗时"""
    
    def __init__(self, search_type: str, keyword: str, logger_instance=None):
        """
        初始化计时器
        
        Args:
            search_type: 搜索类型 (如: "主页搜索", "Webhook导入", "后备匹配" 等)
            keyword: 搜索关键词
            logger_instance: 日志实例
        """
        self.search_type = search_type
        self.keyword = keyword
        self.log = logger_instance or logger
        self.report = SearchTimingReport(search_type=search_type, keyword=keyword)
        self._start_time: Optional[float] = None
        self._step_start: Optional[float] = None
        self._current_step: Optional[str] = None
    
    def start(self):
        """开始总计时"""
        self._start_time = time.perf_counter()
        return self
    
    def step_start(self, step_name: str):
        """开始一个步骤的计时"""
        self._step_start = time.perf_counter()
        self._current_step = step_name
    
    def step_end(self, success: bool = True, details: str = None):
        """结束当前步骤的计时"""
        if self._step_start and self._current_step:
            duration = (time.perf_counter() - self._step_start) * 1000
            self.report.add_step(self._current_step, duration, success, details)
            self._step_start = None
            self._current_step = None
    
    @asynccontextmanager
    async def time_step(self, step_name: str):
        """异步上下文管理器，用于计时单个步骤"""
        self.step_start(step_name)
        success = True
        details = None
        try:
            yield
        except Exception as e:
            success = False
            details = str(e)
            raise
        finally:
            self.step_end(success, details)
    
    def finish(self, print_report: bool = True):
        """结束计时并可选打印报告"""
        if self._start_time:
            self.report.total_duration_ms = (time.perf_counter() - self._start_time) * 1000
        
        if print_report:
            self.report.print_report(self.log)
        
        return self.report


# 搜索类型常量
SEARCH_TYPE_HOME = "主页搜索"
SEARCH_TYPE_WEBHOOK = "Webhook导入"
SEARCH_TYPE_FALLBACK_MATCH = "后备匹配"
SEARCH_TYPE_FALLBACK_SEARCH = "后备搜索"
SEARCH_TYPE_CONTROL_AUTO_IMPORT = "外部控制-全自动导入"
SEARCH_TYPE_CONTROL_SEARCH = "外部控制-搜索媒体"

