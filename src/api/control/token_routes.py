"""
外部控制API - Token管理路由
包含: /tokens/*
"""

import logging
import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import crud, models, get_db_session

from .models import ControlActionResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class ControlApiTokenUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="Token的描述性名称")
    dailyCallLimit: int = Field(..., description="每日调用次数限制, -1 表示无限")
    validityPeriod: str = Field("custom", description="新的有效期: 'permanent', 'custom', '30d' 等。'custom' 表示不改变当前有效期。")


@router.get("/tokens", response_model=List[models.ApiTokenInfo], summary="获取所有Token")
async def get_tokens(session: AsyncSession = Depends(get_db_session)):
    """获取所有为dandanplay客户端创建的API Token。"""
    tokens = await crud.get_all_api_tokens(session)
    return [models.ApiTokenInfo.model_validate(t) for t in tokens]


@router.post("/tokens", response_model=models.ApiTokenInfo, status_code=201, summary="创建Token")
async def create_token(payload: models.ApiTokenCreate, session: AsyncSession = Depends(get_db_session)):
    """
    创建一个新的API Token。

    ### 请求体说明
    - `name`: (string, 必需) Token的名称，用于在UI中识别。
    - `validityPeriod`: (string, 必需) Token的有效期。
        - 填入数字（如 "30", "90"）表示有效期为多少天。
        - 填入 "permanent" 表示永久有效。
    """
    token_str = secrets.token_urlsafe(16)
    try:
        token_id = await crud.create_api_token(session, payload.name, token_str, payload.validityPeriod, payload.dailyCallLimit)
        new_token = await crud.get_api_token_by_id(session, token_id)
        return models.ApiTokenInfo.model_validate(new_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/tokens/{tokenId}", response_model=models.ApiTokenInfo, summary="获取单个Token详情")
async def get_token(tokenId: int, session: AsyncSession = Depends(get_db_session)):
    """获取单个API Token的详细信息。"""
    token = await crud.get_api_token_by_id(session, tokenId)
    if not token:
        raise HTTPException(404, "Token未找到")
    return models.ApiTokenInfo.model_validate(token)


@router.get("/tokens/{tokenId}/logs", response_model=List[models.TokenAccessLog], summary="获取Token访问日志")
async def get_token_logs(tokenId: int, session: AsyncSession = Depends(get_db_session)):
    """获取单个API Token最近的访问日志。"""
    logs = await crud.get_token_access_logs(session, tokenId)
    return [models.TokenAccessLog.model_validate(log) for log in logs]


@router.put("/tokens/{tokenId}/toggle", response_model=ControlActionResponse, summary="启用/禁用Token")
async def toggle_token(tokenId: int, session: AsyncSession = Depends(get_db_session)):
    """切换API Token的启用/禁用状态。"""
    new_status = await crud.toggle_api_token(session, tokenId)
    if new_status is None:
        raise HTTPException(404, "Token未找到")
    message = "Token 已启用。" if new_status else "Token 已禁用。"
    return {"message": message}


@router.put("/tokens/{tokenId}", response_model=ControlActionResponse, summary="更新Token信息")
async def update_token(
    tokenId: int,
    payload: ControlApiTokenUpdate,
    session: AsyncSession = Depends(get_db_session)
):
    """更新指定API Token的名称、每日调用上限和有效期。"""
    updated = await crud.update_api_token(
        session,
        token_id=tokenId,
        name=payload.name,
        daily_call_limit=payload.dailyCallLimit,
        validity_period=payload.validityPeriod
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return {"message": "Token信息更新成功。"}


@router.post("/tokens/{tokenId}/reset", response_model=ControlActionResponse, summary="重置Token调用次数")
async def reset_token_counter(
    tokenId: int,
    session: AsyncSession = Depends(get_db_session)
):
    """将指定API Token的今日调用次数重置为0。"""
    reset_ok = await crud.reset_token_counter(session, tokenId)
    if not reset_ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return {"message": "Token调用次数已重置为0。"}


@router.delete("/tokens/{tokenId}", response_model=ControlActionResponse, summary="删除Token")
async def delete_token(tokenId: int, session: AsyncSession = Depends(get_db_session)):
    """删除一个API Token。"""
    if not await crud.delete_api_token(session, tokenId):
        raise HTTPException(404, "Token未找到")
    return {"message": "Token 删除成功。"}

