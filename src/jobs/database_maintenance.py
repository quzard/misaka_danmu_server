import logging
from typing import Callable
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from .. import crud, orm_models
from ..config import settings
from ..timezone import get_now
from .base import BaseJob
from ..task_manager import TaskSuccess


class DatabaseMaintenanceJob(BaseJob):
    """
    一个用于执行数据库维护的定时任务，包括清理旧日志和优化表。
    """
    job_type = "databaseMaintenance"
    job_name = "数据库维护"

    async def run(self, session: AsyncSession, progress_callback: Callable):
        """
        执行数据库维护的核心任务：清理旧日志和优化表。
        """
        self.logger.info(f"开始执行 [{self.job_name}] 定时任务...")
        
        # --- 1. 应用日志清理 ---
        await progress_callback(10, "正在清理旧日志...")
        
        try:
            # 日志保留天数，默认为30天。
            retention_days_str = await crud.get_config_value(session, "logRetentionDays", "30")
            retention_days = int(retention_days_str)
        except (ValueError, TypeError):
            retention_days = 30
        
        if retention_days > 0:
            self.logger.info(f"将清理 {retention_days} 天前的日志记录。")
            cutoff_date = get_now().replace(tzinfo=None) - timedelta(days=retention_days)
            
            tables_to_prune = {
                "任务历史": (orm_models.TaskHistory, orm_models.TaskHistory.createdAt),
                "Token访问日志": (orm_models.TokenAccessLog, orm_models.TokenAccessLog.accessTime),
                "外部API访问日志": (orm_models.ExternalApiLog, orm_models.ExternalApiLog.accessTime),
            }
            
            total_deleted = 0
            for name, (model, date_column) in tables_to_prune.items():
                deleted_count = await crud.prune_logs(session, model, date_column, cutoff_date)
                if deleted_count > 0:
                    self.logger.info(f"从 {name} 表中删除了 {deleted_count} 条旧记录。")
                total_deleted += deleted_count
            await progress_callback(40, f"应用日志清理完成，共删除 {total_deleted} 条记录。")
        else:
            self.logger.info("日志保留天数设为0或无效，跳过清理。")
            await progress_callback(40, "日志保留天数设为0，跳过清理。")

        # --- 2. Binlog 清理 (仅MySQL) ---
        db_type = settings.database.type.lower()
        if db_type == "mysql":
            await progress_callback(50, "正在清理 MySQL Binlog...")
            try:
                # 新增：从配置中读取binlog保留天数
                binlog_retention_days_str = await crud.get_config_value(session, "mysqlBinlogRetentionDays", "3")
                binlog_retention_days = int(binlog_retention_days_str)

                if binlog_retention_days > 0:
                    # 用户指定清理N天前的日志
                    binlog_cleanup_message = await crud.purge_binary_logs(session, days=binlog_retention_days)
                    self.logger.info(binlog_cleanup_message)
                    await progress_callback(60, binlog_cleanup_message)
                else:
                    binlog_cleanup_message = "Binlog自动清理已禁用。"
                    self.logger.info(binlog_cleanup_message)
                    await progress_callback(60, binlog_cleanup_message)
            except OperationalError as e:
                # 检查是否是权限不足的错误 (MySQL error code 1227)
                if e.orig and hasattr(e.orig, 'args') and len(e.orig.args) > 0 and e.orig.args[0] == 1227:
                    binlog_cleanup_message = "Binlog 清理失败: 数据库用户缺少 SUPER 或 BINLOG_ADMIN 权限。此为正常现象，可安全忽略。"
                    self.logger.warning(binlog_cleanup_message)
                    await progress_callback(60, binlog_cleanup_message)
                else:
                    # 其他操作错误，仍然记录详细信息
                    binlog_cleanup_message = f"Binlog 清理失败: {e}"
                    self.logger.error(binlog_cleanup_message, exc_info=True)
                    await progress_callback(60, binlog_cleanup_message)
            except Exception as e:
                # 记录错误，但不中断任务
                binlog_cleanup_message = f"Binlog 清理失败: {e}"
                self.logger.error(binlog_cleanup_message, exc_info=True)
                await progress_callback(60, binlog_cleanup_message)

        # --- 3. 数据库表优化 ---
        await progress_callback(70, "正在执行数据库表优化...")
        
        try:
            optimization_message = await crud.optimize_database(session, db_type)
            self.logger.info(f"数据库优化结果: {optimization_message}")
        except Exception as e:
            optimization_message = f"数据库优化失败: {e}"
            self.logger.error(optimization_message, exc_info=True)
            # 即使优化失败，也不应导致整个任务失败，仅记录错误

        await progress_callback(90, optimization_message)

        final_message = f"数据库维护完成。{optimization_message}"
        raise TaskSuccess(final_message)
