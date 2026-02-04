"""
任务状态查询命令模块
提供 @CXRW 指令，查询进行中的任务状态
"""
import logging
from typing import List, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime

from .base import CommandHandler
from src.db.orm_models import TaskHistory
from src.core.timezone import get_now

if TYPE_CHECKING:
    from src.api.dandan import DandanSearchAnimeResponse

logger = logging.getLogger(__name__)


class TaskStatusCommand(CommandHandler):
    """任务状态查询命令"""
    
    def __init__(self):
        super().__init__(
            name="CXRW",
            description="查询任务状态（支持按状态和队列筛选）",
            cooldown_seconds=3,
            usage="@CXRW [状态#] [#队列] [状态#队列] (支持大小写)",
            examples=[
                "@CXRW - 查询所有任务",
                "@cxrw r# - 进行中",
                "@CXRW c# - 已完成",
                "@cxrw f# - 失败",
                "@CXRW #d - 下载队列",
                "@cxrw #m - 管理队列",
                "@CXRW #b - 后备队列",
                "@cxrw r#d - 下载队列运行中"
            ]
        )
    
    async def execute(self, token: str, args: List[str], session: AsyncSession,
                     config_manager, **kwargs) -> "DandanSearchAnimeResponse":
        """执行任务状态查询"""
        # 获取图片URL
        image_url = await self.get_image_url(config_manager)

        # 解析参数 - 使用简短标识符
        # 格式规则：
        #   a#  - 只指定状态（状态在#前）
        #   #a  - 只指定队列（队列在#后）
        #   a#b - 同时指定状态和队列
        #
        # 状态标识: A(all), R(running), C(completed), F(failed), P(pending), S(paused)
        # 队列标识: D(download), M(management), B(fallback/backup)

        status_filter = 'ALL'  # 默认为所有任务
        queue_filter = None

        if args:
            arg = args[0].upper()

            # 状态映射
            status_map = {
                'A': 'ALL',
                'R': 'RUNNING',
                'C': 'COMPLETED',
                'F': 'FAILED',
                'P': 'PENDING',
                'S': 'PAUSED'
            }

            # 队列映射
            queue_map = {
                'D': 'download',
                'M': 'management',
                'B': 'fallback'
            }

            # 检查是否包含 #
            if '#' in arg:
                # 按 # 分割
                parts = arg.split('#')

                # 情况1: a# - 只指定状态（# 在末尾）
                if parts[0] and not parts[1]:
                    if parts[0] in status_map:
                        status_filter = status_map[parts[0]]

                # 情况2: #a - 只指定队列（# 在开头）
                elif not parts[0] and parts[1]:
                    if parts[1] in queue_map:
                        queue_filter = queue_map[parts[1]]

                # 情况3: a#b - 同时指定状态和队列
                elif parts[0] and parts[1]:
                    if parts[0] in status_map:
                        status_filter = status_map[parts[0]]
                    if parts[1] in queue_map:
                        queue_filter = queue_map[parts[1]]

        # 构建查询
        stmt = select(
            TaskHistory.taskId,
            TaskHistory.title,
            TaskHistory.status,
            TaskHistory.progress,
            TaskHistory.description,
            TaskHistory.createdAt,
            TaskHistory.updatedAt,
            TaskHistory.queueType
        )

        # 应用状态过滤
        if status_filter == 'RUNNING':
            stmt = stmt.where(TaskHistory.status.in_(['排队中', '运行中', '已暂停']))
        elif status_filter == 'COMPLETED':
            stmt = stmt.where(TaskHistory.status == '已完成')
        elif status_filter == 'FAILED':
            stmt = stmt.where(TaskHistory.status == '失败')
        elif status_filter == 'PENDING':
            stmt = stmt.where(TaskHistory.status == '排队中')
        elif status_filter == 'PAUSED':
            stmt = stmt.where(TaskHistory.status == '已暂停')
        # ALL 不添加状态过滤

        # 应用队列过滤
        if queue_filter:
            stmt = stmt.where(TaskHistory.queueType == queue_filter)

        stmt = stmt.order_by(TaskHistory.updatedAt.desc()).limit(5)
        
        result = await session.execute(stmt)
        tasks = result.mappings().all()

        # 状态和队列的中文标签
        status_labels = {
            'ALL': '全部',
            'RUNNING': '进行中',
            'COMPLETED': '已完成',
            'FAILED': '失败',
            'PENDING': '排队中',
            'PAUSED': '已暂停'
        }

        queue_labels = {
            'download': '下载队列',
            'management': '管理队列',
            'fallback': '后备队列'
        }

        status_label = status_labels.get(status_filter, status_filter)
        queue_label = queue_labels.get(queue_filter, '所有队列') if queue_filter else '所有队列'

        # 如果没有找到任务
        if not tasks:
            filter_desc = f"状态: {status_label} | 队列: {queue_label}"
            return self.success_response(
                title=f"📋 未找到匹配的任务",
                description=f"筛选条件: {filter_desc}\n\n💡 尝试其他筛选条件\n\n"
                           f"示例:\n"
                           f"  @CXRW - 所有任务\n"
                           f"  @CXRW c# - 已完成\n"
                           f"  @CXRW #d - 下载队列\n"
                           f"  @CXRW r#d - 下载队列运行中",
                image_url=image_url
            )

        # 构建响应列表
        items = []

        # 第一项：帮助说明
        help_desc = (
            "📖 参数说明:\n\n"
            "状态标识:\n"
            "  a# - 全部  r# - 进行中\n"
            "  c# - 已完成  f# - 失败\n"
            "  p# - 排队中  s# - 已暂停\n\n"
            "队列标识:\n"
            "  #d - 下载队列\n"
            "  #m - 管理队列\n"
            "  #b - 后备队列\n\n"
            "组合使用:\n"
            "  r#d - 下载队列运行中\n"
            "  c#m - 管理队列已完成"
        )

        items.append(
            self.build_response_item(
                anime_id=999999979,
                title="💡 @CXRW 使用说明",
                description=help_desc,
                image_url=image_url,
                type="other",
                episodeCount=0
            )
        )

        # 第二项：任务总览
        # 构建统计查询（与主查询条件一致）
        total_stmt = select(func.count()).select_from(TaskHistory)

        if status_filter == 'RUNNING':
            total_stmt = total_stmt.where(TaskHistory.status.in_(['排队中', '运行中', '已暂停']))
        elif status_filter == 'COMPLETED':
            total_stmt = total_stmt.where(TaskHistory.status == '已完成')
        elif status_filter == 'FAILED':
            total_stmt = total_stmt.where(TaskHistory.status == '失败')
        elif status_filter == 'PENDING':
            total_stmt = total_stmt.where(TaskHistory.status == '排队中')
        elif status_filter == 'PAUSED':
            total_stmt = total_stmt.where(TaskHistory.status == '已暂停')

        if queue_filter:
            total_stmt = total_stmt.where(TaskHistory.queueType == queue_filter)

        total_count = (await session.execute(total_stmt)).scalar_one()

        overview_desc = (
            f"筛选条件:\n"
            f"  状态: {status_label}\n"
            f"  队列: {queue_label}\n\n"
            f"共找到 {total_count} 个任务\n"
            f"显示最新的 {len(tasks)} 条\n\n"
            f"💡 任务按更新时间排序"
        )

        items.append(
            self.build_response_item(
                anime_id=999999980,
                title="📊 任务总览",
                description=overview_desc,
                image_url=image_url,
                type="other",
                episodeCount=total_count
            )
        )
        
        # 后续项：每个任务
        for idx, task in enumerate(tasks, start=1):
            title = task['title']
            status = task['status']
            progress = task['progress']
            description = task['description']
            created_at = task['createdAt']
            updated_at = task['updatedAt']
            queue_type = task['queueType']
            
            # 状态图标
            status_icon = {
                '排队中': '⏳',
                '运行中': '▶️',
                '已暂停': '⏸️'
            }.get(status, '❓')
            
            # 队列类型标签
            queue_label = {
                'download': '下载队列',
                'management': '管理队列',
                'fallback': '后备队列'
            }.get(queue_type, queue_type)
            
            # 进度条
            progress_bar = self._make_progress_bar(progress, width=15)
            
            # 计算运行时长
            now = get_now().replace(tzinfo=None)
            duration = now - created_at if created_at else None
            if duration:
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                seconds = int(duration.total_seconds() % 60)
                if hours > 0:
                    duration_str = f"{hours}小时{minutes}分"
                elif minutes > 0:
                    duration_str = f"{minutes}分{seconds}秒"
                else:
                    duration_str = f"{seconds}秒"
            else:
                duration_str = "未知"
            
            # 格式化更新时间
            if updated_at:
                update_time_str = updated_at.strftime("%H:%M:%S")
            else:
                update_time_str = "未知"
            
            task_desc = (
                f"{status_icon} {status} | {progress}%\n\n"
                f"{progress_bar}\n\n"
                f"📝 {description}\n\n"
                f"🏷️ 队列: {queue_label}\n"
                f"⏱️ 运行时长: {duration_str}\n"
                f"🔄 最后更新: {update_time_str}"
            )
            
            items.append(
                self.build_response_item(
                    anime_id=999999980 + idx,
                    title=f"[{idx}] {title[:30]}{'...' if len(title) > 30 else ''}",
                    description=task_desc,
                    image_url=image_url,
                    type="other",
                    episodeCount=progress
                )
            )
        
        logger.info(f"@CXRW 查询任务: 状态={status_label}, 队列={queue_label}, 找到 {len(tasks)} 个任务")

        return self.build_response(items)
    
    def _make_progress_bar(self, progress: int, width: int = 15) -> str:
        """生成文本进度条"""
        if progress < 0:
            progress = 0
        elif progress > 100:
            progress = 100
        
        filled = int((progress / 100) * width)
        filled = min(filled, width)
        
        bar = "▰" * filled + "▱" * (width - filled)
        return bar

