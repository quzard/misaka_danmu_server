"""
数据库备份管理 API
"""
import logging
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ... import crud, models, security
from ...database import get_db_session
from ...jobs.database_backup import (
    create_backup, list_backups, delete_backup, restore_backup,
    get_backup_path, get_retention_count
)
from ..dependencies import get_scheduler_manager
from ...scheduler import SchedulerManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup", tags=["备份管理"])


class BackupInfo(BaseModel):
    filename: str
    size: int
    created_at: str
    db_type: Optional[str] = None


class BackupCreateResponse(BaseModel):
    success: bool
    message: str
    filename: Optional[str] = None
    size: Optional[int] = None
    records: Optional[int] = None


class BackupJobStatus(BaseModel):
    exists: bool
    enabled: bool = False
    cron_expression: Optional[str] = None
    next_run_time: Optional[str] = None
    task_id: Optional[str] = None


class RestoreRequest(BaseModel):
    filename: str
    confirm: str  # 必须输入 "RESTORE" 确认


@router.get("/list", response_model=List[BackupInfo], summary="获取备份列表")
async def get_backup_list(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """获取所有备份文件列表"""
    try:
        backups = await list_backups(session)
        return [BackupInfo(**b) for b in backups]
    except Exception as e:
        logger.error(f"获取备份列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取备份列表失败: {str(e)}")


@router.post("/create", response_model=BackupCreateResponse, summary="立即创建备份")
async def create_backup_now(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """立即创建数据库备份"""
    try:
        result = await create_backup(session)
        await session.commit()
        
        size_mb = result['size'] / (1024 * 1024)
        return BackupCreateResponse(
            success=True,
            message=f"备份成功，文件大小: {size_mb:.2f} MB，共 {result['records']} 条记录",
            filename=result['filename'],
            size=result['size'],
            records=result['records'],
        )
    except Exception as e:
        logger.error(f"创建备份失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建备份失败: {str(e)}")


@router.get("/download/{filename}", summary="下载备份文件")
async def download_backup(
    filename: str,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """下载指定的备份文件"""
    # 安全检查
    if not filename.startswith("danmuapi_backup_") or not filename.endswith(".json.gz"):
        raise HTTPException(status_code=400, detail="无效的备份文件名")
    
    backup_path = await get_backup_path(session)
    filepath = backup_path / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    
    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/gzip"
    )


@router.delete("/delete/{filename}", summary="删除备份文件")
async def delete_backup_file(
    filename: str,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """删除指定的备份文件"""
    try:
        await delete_backup(session, filename)
        return {"success": True, "message": f"已删除备份: {filename}"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"删除备份失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除备份失败: {str(e)}")


@router.delete("/delete-batch", summary="批量删除备份文件")
async def delete_backup_files_batch(
    filenames: List[str] = Query(..., description="要删除的文件名列表"),
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """批量删除备份文件"""
    deleted = []
    errors = []

    for filename in filenames:
        try:
            await delete_backup(session, filename)
            deleted.append(filename)
        except Exception as e:
            errors.append({"filename": filename, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "deleted": deleted,
        "errors": errors,
        "message": f"成功删除 {len(deleted)} 个文件" + (f"，{len(errors)} 个失败" if errors else "")
    }


@router.post("/restore", summary="从备份还原数据库")
async def restore_from_backup(
    request: RestoreRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    从备份还原数据库
    警告：此操作会清空现有数据！
    """
    # 确认检查
    if request.confirm != "RESTORE":
        raise HTTPException(status_code=400, detail="请输入 'RESTORE' 确认还原操作")

    try:
        result = await restore_backup(session, request.filename)
        await session.commit()

        return {
            "success": True,
            "message": f"还原成功，共还原 {result['records']} 条记录",
            "filename": result['filename'],
            "records": result['records'],
            "source_db_type": result['source_db_type'],
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"还原备份失败: {e}", exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"还原备份失败: {str(e)}")


@router.get("/job-status", response_model=BackupJobStatus, summary="获取备份定时任务状态")
async def get_backup_job_status(
    current_user: models.User = Depends(security.get_current_user),
    scheduler: SchedulerManager = Depends(get_scheduler_manager),
):
    """获取数据库备份定时任务的状态"""
    tasks_list = await scheduler.get_all_tasks()

    # 查找 job_type 为 "databaseBackup" 的任务
    for task in tasks_list:
        if task.get("jobType") == "databaseBackup":
            return BackupJobStatus(
                exists=True,
                enabled=task.get("isEnabled", False),
                cron_expression=task.get("cronExpression"),
                next_run_time=task.get("nextRunTime"),
                task_id=task.get("taskId")
            )

    return BackupJobStatus(exists=False)


@router.get("/config", summary="获取备份配置")
async def get_backup_config(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """获取备份相关配置"""
    backup_path = await get_backup_path(session)
    retention_count = await get_retention_count(session)

    return {
        "backup_path": str(backup_path),
        "retention_count": retention_count,
    }

