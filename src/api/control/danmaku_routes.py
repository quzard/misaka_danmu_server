"""
外部控制API - 弹幕管理路由
包含: /danmaku/{episodeId} GET/POST
"""

import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import crud, models, get_db_session, ConfigManager
from src.services import TaskManager, TaskSuccess

from .models import ControlTaskResponse
from .dependencies import get_task_manager, get_config_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/danmaku/{episodeId}", response_model=models.CommentResponse, summary="获取弹幕")
async def get_danmaku(episodeId: int, session: AsyncSession = Depends(get_db_session)):
    """获取指定分集的所有弹幕，返回dandanplay兼容格式。用于弹幕调整，不受输出限制控制。"""
    if not await crud.check_episode_exists(session, episodeId):
        raise HTTPException(404, "分集未找到")
    comments = await crud.fetch_comments(session, episodeId)
    return models.CommentResponse(count=len(comments), comments=[models.Comment.model_validate(c) for c in comments])


@router.post("/danmaku/{episodeId}", status_code=202, summary="覆盖弹幕", response_model=ControlTaskResponse)
async def overwrite_danmaku(
    episodeId: int,
    payload: models.DanmakuUpdateRequest,
    task_manager: TaskManager = Depends(get_task_manager),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """提交一个后台任务，用请求体中提供的弹幕列表完全覆盖指定分集的现有弹幕。"""
    async def overwrite_task(session: AsyncSession, cb: Callable):
        await cb(10, "清空中...")
        await crud.clear_episode_comments(session, episodeId)
        await cb(50, f"插入 {len(payload.comments)} 条新弹幕...")

        comments_to_insert = []
        for c in payload.comments:
            comment_dict = c.model_dump()
            try:
                # 从 'p' 字段解析时间戳，并添加到字典中
                timestamp_str = comment_dict['p'].split(',')[0]
                comment_dict['t'] = float(timestamp_str)
            except (IndexError, ValueError):
                comment_dict['t'] = 0.0  # 如果解析失败，则默认为0
            comments_to_insert.append(comment_dict)

        added = await crud.save_danmaku_for_episode(session, episodeId, comments_to_insert, config_manager)
        raise TaskSuccess(f"弹幕覆盖完成，新增 {added} 条。")

    try:
        task_id, _ = await task_manager.submit_task(overwrite_task, f"外部API覆盖弹幕 (分集ID: {episodeId})")
        return {"message": "弹幕覆盖任务已提交", "taskId": task_id}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

