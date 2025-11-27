"""
弹幕存储管理API - 批量迁移、重命名、模板转换
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ... import models, security
from ...database import get_db_session
from ..dependencies import get_config_manager
from ...config_manager import ConfigManager
from ...crud import danmaku_storage as crud

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== 请求/响应模型 ====================

class BatchMigrateRequest(BaseModel):
    """批量迁移请求"""
    animeIds: List[int]
    targetPath: str
    keepStructure: bool = True
    conflictAction: str = "skip"  # skip, overwrite, rename


class BatchRenameRequest(BaseModel):
    """批量重命名请求"""
    animeIds: List[int]
    mode: str  # prefix, regex
    prefix: Optional[str] = ""
    suffix: Optional[str] = ""
    regexPattern: Optional[str] = ""
    regexReplace: Optional[str] = ""


class ApplyTemplateRequest(BaseModel):
    """应用模板请求"""
    animeIds: List[int]
    templateType: str  # tv, movie, id


class BatchOperationResult(BaseModel):
    """批量操作结果"""
    success: bool
    totalCount: int
    successCount: int
    failedCount: int
    skippedCount: int
    details: List[dict]


# ==================== API端点 ====================

@router.post("/batch-migrate", response_model=BatchOperationResult, summary="批量迁移弹幕文件")
async def batch_migrate(
    request: BatchMigrateRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """将选中条目的弹幕文件迁移到新目录"""
    result = await crud.batch_migrate_danmaku(
        session,
        anime_ids=request.animeIds,
        target_path=request.targetPath,
        keep_structure=request.keepStructure,
        conflict_action=request.conflictAction
    )
    return BatchOperationResult(**result)


@router.post("/batch-rename", response_model=BatchOperationResult, summary="批量重命名弹幕文件")
async def batch_rename(
    request: BatchRenameRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """批量重命名选中条目的弹幕文件"""
    result = await crud.batch_rename_danmaku(
        session,
        anime_ids=request.animeIds,
        mode=request.mode,
        prefix=request.prefix or "",
        suffix=request.suffix or "",
        regex_pattern=request.regexPattern or "",
        regex_replace=request.regexReplace or ""
    )
    return BatchOperationResult(**result)


@router.post("/apply-template", response_model=BatchOperationResult, summary="应用新模板")
async def apply_template(
    request: ApplyTemplateRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """按新的存储模板重新组织弹幕文件"""
    result = await crud.apply_danmaku_template(
        session,
        anime_ids=request.animeIds,
        template_type=request.templateType,
        config_manager=config_manager
    )
    return BatchOperationResult(**result)

