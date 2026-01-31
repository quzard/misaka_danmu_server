"""
配置相关的API端点
"""

import logging
import json
import secrets
import string
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import models, crud, get_db_session
from src import security
from src.core import ConfigManager, get_config_schema
from src.api.dependencies import get_config_manager

# 从 crud 导入需要的子模块
config_crud = crud.config

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Pydantic Models ---

class ConfigValueResponse(BaseModel):
    value: str


class ConfigValueRequest(BaseModel):
    value: str


# --- API Endpoints ---

@router.get("/schema/parameters", summary="获取参数配置的 Schema")
async def get_parameters_schema(
    current_user: models.User = Depends(security.get_current_user)
):
    """
    获取参数配置页面的 Schema 定义。
    前端根据此 Schema 动态渲染配置界面。
    """
    return get_config_schema()


@router.get("/{config_key}", response_model=Dict[str, str], summary="获取指定配置项的值")
async def get_config_item(
    config_key: str,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取数据库中单个配置项的值。"""
    value = await config_crud.get_config_value(session, config_key, "")  # 默认为空字符串
    return {"key": config_key, "value": value}


@router.put("/{config_key}", status_code=status.HTTP_204_NO_CONTENT, summary="更新指定配置项的值")
async def update_config_item(
    config_key: str,
    payload: Dict[str, Any],  # 修正：允许任意类型的值,避免前端传递undefined时报错
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """更新数据库中单个配置项的值。"""
    value = payload.get("value")
    if value is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing 'value' in request body")

    # 确保value是字符串类型
    value_str = str(value) if value is not None else ""

    await config_crud.update_config_value(session, config_key, value_str)
    config_manager.invalidate(config_key)
    logger.info(f"用户 '{current_user.username}' 更新了配置项 '{config_key}'。")


@router.post("/webhookApiKey/regenerate", response_model=Dict[str, str], summary="重新生成Webhook API Key")
async def regenerate_webhook_api_key(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """生成一个新的、随机的Webhook API Key并保存到数据库。"""
    alphabet = string.ascii_letters + string.digits
    new_key = ''.join(secrets.choice(alphabet) for _ in range(20))
    await config_crud.update_config_value(session, "webhookApiKey", new_key)
    config_manager.invalidate("webhookApiKey")
    logger.info(f"用户 '{current_user.username}' 重新生成了 Webhook API Key。")
    return {"key": "webhookApiKey", "value": new_key}


@router.post("/externalApiKey/regenerate", response_model=Dict[str, str], summary="重新生成外部API Key")
async def regenerate_external_api_key(
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """生成一个新的、随机的外部API Key并保存到数据库。"""
    alphabet = string.ascii_letters + string.digits
    new_key = ''.join(secrets.choice(alphabet) for _ in range(32))  # 增加长度以提高安全性
    await config_crud.update_config_value(session, "externalApiKey", new_key)
    config_manager.invalidate("externalApiKey")
    logger.info(f"用户 '{current_user.username}' 重新生成了外部 API Key。")
    return {"key": "externalApiKey", "value": new_key}



