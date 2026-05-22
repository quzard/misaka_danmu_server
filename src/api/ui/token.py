"""
Token相关的API端点
"""
import logging
import secrets
import string
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import security
from src.db import crud, models, get_db_session

from .models import ApiTokenUpdate

import re

logger = logging.getLogger(__name__)

router = APIRouter()

# Token 字符合法性正则：仅允许字母、数字、下划线、短横线
_TOKEN_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_custom_token(token_str: str) -> str:
    """校验自定义 Token 字符串的合法性"""
    token_str = token_str.strip()
    if len(token_str) < 5 or len(token_str) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="自定义 Token 长度须在 5~100 字符之间"
        )
    if not _TOKEN_PATTERN.match(token_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="自定义 Token 仅允许字母、数字、下划线和短横线"
        )
    return token_str

@router.get("/tokens", response_model=List[models.ApiTokenInfo], summary="获取所有弹幕API Token")
async def get_all_api_tokens(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取所有为第三方播放器创建的 API Token。"""
    tokens = await crud.get_all_api_tokens(session)
    return [models.ApiTokenInfo.model_validate(t) for t in tokens]



@router.post("/tokens", response_model=models.ApiTokenInfo, status_code=status.HTTP_201_CREATED, summary="创建一个新的API Token")
async def create_new_api_token(
    token_data: models.ApiTokenCreate,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """创建一个新的 API Token，支持自定义 Token 字符串或自动生成。"""
    if token_data.customToken:
        new_token_str = _validate_custom_token(token_data.customToken)
        # 唯一性检查
        existing = await crud.get_api_token_by_token_str(session, new_token_str)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Token '{new_token_str}' 已被使用，请换一个。"
            )
    else:
        # 自动生成20位随机字符串
        alphabet = string.ascii_letters + string.digits
        new_token_str = ''.join(secrets.choice(alphabet) for _ in range(20))
    try:
        token_id = await crud.create_api_token(session, token_data.name, new_token_str, token_data.validityPeriod, token_data.dailyCallLimit)
        new_token = await crud.get_api_token_by_id(session, token_id)
        return models.ApiTokenInfo.model_validate(new_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))



@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除一个API Token")
async def delete_api_token(
    token_id: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """根据ID删除一个 API Token。"""
    deleted = await crud.delete_api_token(session, token_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return



@router.put("/tokens/{token_id}/toggle", status_code=status.HTTP_204_NO_CONTENT, summary="切换API Token的启用状态")
async def toggle_api_token_status(
    token_id: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """切换指定 API Token 的启用/禁用状态。"""
    toggled = await crud.toggle_api_token(session, token_id)
    if not toggled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return



@router.put("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="更新API Token信息")
async def update_api_token(
    token_id: int,
    payload: ApiTokenUpdate,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """更新指定API Token的名称、每日调用上限、有效期和Token字符串。"""
    # 如果提供了自定义 Token，先校验
    new_token_str = None
    if payload.customToken:
        new_token_str = _validate_custom_token(payload.customToken)
        # 唯一性检查（排除自身）
        existing = await crud.get_api_token_by_token_str(session, new_token_str)
        if existing and existing['id'] != token_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Token '{new_token_str}' 已被其他条目使用，请换一个。"
            )
    updated = await crud.update_api_token(
        session,
        token_id=token_id,
        name=payload.name,
        daily_call_limit=payload.dailyCallLimit,
        validity_period=payload.validityPeriod,
        new_token_str=new_token_str,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    logger.info(f"用户 '{current_user.username}' 更新了 Token (ID: {token_id}) 的信息。")




@router.post("/tokens/{token_id}/reset", status_code=status.HTTP_204_NO_CONTENT, summary="重置API Token的调用次数")
async def reset_api_token_counter(
    token_id: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """将指定API Token的今日调用次数重置为0。"""
    reset_ok = await crud.reset_token_counter(session, token_id)
    if not reset_ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    logger.info(f"用户 '{current_user.username}' 重置了 Token (ID: {token_id}) 的调用次数。")

# --- 自定义弹幕路径配置 ---



@router.get("/tokens/{tokenId}/logs", response_model=List[models.TokenAccessLog], summary="获取Token的访问日志")
async def get_token_logs(
    tokenId: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    logs = await crud.get_token_access_logs(session, tokenId)
    return [models.TokenAccessLog.model_validate(log) for log in logs]



