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

logger = logging.getLogger(__name__)

router = APIRouter()

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
    """创建一个新的、随机的 API Token。"""
    # 生成一个由大小写字母和数字组成的20位随机字符串
    alphabet = string.ascii_letters + string.digits
    new_token_str = ''.join(secrets.choice(alphabet) for _ in range(20))
    try:
        token_id = await crud.create_api_token(session, token_data.name, new_token_str, token_data.validityPeriod, token_data.dailyCallLimit)
        # 重新从数据库获取以包含所有字段
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
    """更新指定API Token的名称、每日调用上限和有效期。"""
    updated = await crud.update_api_token(
        session,
        token_id=token_id,
        name=payload.name,
        daily_call_limit=payload.dailyCallLimit,
        validity_period=payload.validityPeriod
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



