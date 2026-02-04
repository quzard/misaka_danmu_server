"""
弹幕编辑API - 弹幕详情、时间偏移、分集拆分、分集合并
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import models, get_db_session, ConfigManager
from src import security
from src.db.crud import danmaku_edit as crud
from src.api.dependencies import get_config_manager

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== 请求/响应模型 ====================

class TimeOffsetRequest(BaseModel):
    """时间偏移请求"""
    episodeIds: List[int] = Field(..., description="要调整的分集ID列表")
    offsetSeconds: float = Field(..., description="偏移秒数（正数延后，负数提前）")


class TimeOffsetResponse(BaseModel):
    """时间偏移响应"""
    success: bool
    modifiedCount: int = Field(0, description="修改的分集数")
    totalComments: int = Field(0, description="总共修改的弹幕数")


class SplitConfig(BaseModel):
    """拆分配置"""
    episodeIndex: int = Field(..., description="新分集的集数")
    startTime: float = Field(..., description="开始时间（秒）")
    endTime: float = Field(..., description="结束时间（秒）")
    title: Optional[str] = Field(None, description="新分集标题")


class SplitRequest(BaseModel):
    """分集拆分请求"""
    sourceEpisodeId: int = Field(..., description="源分集ID")
    splits: List[SplitConfig] = Field(..., description="拆分配置列表")
    deleteSource: bool = Field(True, description="是否删除原分集")
    resetTime: bool = Field(True, description="新分集时间是否从0开始")


class NewEpisodeInfo(BaseModel):
    """新分集信息"""
    episodeId: int
    episodeIndex: int
    commentCount: int


class SplitResponse(BaseModel):
    """分集拆分响应"""
    success: bool
    error: Optional[str] = None
    newEpisodes: List[NewEpisodeInfo] = []


class MergeSourceConfig(BaseModel):
    """合并源配置"""
    episodeId: int = Field(..., description="源分集ID")
    offsetSeconds: float = Field(0, description="时间偏移（秒）")


class MergeRequest(BaseModel):
    """分集合并请求"""
    sourceEpisodes: List[MergeSourceConfig] = Field(..., description="源分集配置列表")
    targetEpisodeIndex: int = Field(..., description="目标集数")
    targetTitle: str = Field(..., description="目标标题")
    deleteSources: bool = Field(True, description="是否删除原分集")
    deduplicate: bool = Field(False, description="是否去重")


class MergeResponse(BaseModel):
    """分集合并响应"""
    success: bool
    error: Optional[str] = None
    newEpisodeId: Optional[int] = None
    commentCount: int = 0


class SourceInfo(BaseModel):
    """来源信息"""
    name: str
    count: int


class TimeRange(BaseModel):
    """时间范围"""
    start: float
    end: float


class DistributionItem(BaseModel):
    """分布项"""
    minute: int
    count: int


class CommentPreview(BaseModel):
    """弹幕预览"""
    time: float
    content: str
    source: str


class DanmakuDetailResponse(BaseModel):
    """弹幕详情响应"""
    episodeId: int
    totalCount: int
    timeRange: TimeRange
    sources: List[SourceInfo]
    distribution: List[DistributionItem]
    comments: List[CommentPreview]


class CommentsPageResponse(BaseModel):
    """弹幕分页响应"""
    total: int
    comments: List[CommentPreview]
    page: int
    pageSize: int


# ==================== API端点 ====================

@router.get(
    "/danmaku/detail/{episodeId}",
    response_model=DanmakuDetailResponse,
    summary="获取弹幕详情"
)
async def get_danmaku_detail(
    episodeId: int,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """获取指定分集的弹幕详情，包括统计信息、时间分布和弹幕预览"""
    result = await crud.get_danmaku_detail(session, episodeId)
    if not result:
        raise HTTPException(status_code=404, detail="分集不存在或没有弹幕")
    return DanmakuDetailResponse(**result)


@router.get(
    "/danmaku/comments/{episodeId}",
    response_model=CommentsPageResponse,
    summary="分页获取弹幕列表"
)
async def get_danmaku_comments(
    episodeId: int,
    page: int = 1,
    pageSize: int = 100,
    startTime: Optional[float] = None,
    endTime: Optional[float] = None,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """分页获取弹幕列表，支持时间范围筛选"""
    result = await crud.get_danmaku_comments_page(
        session, episodeId, page, pageSize, startTime, endTime
    )
    return CommentsPageResponse(**result)


@router.post(
    "/danmaku/offset",
    response_model=TimeOffsetResponse,
    summary="时间偏移调整"
)
async def apply_time_offset(
    request: TimeOffsetRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """对指定分集的弹幕应用时间偏移"""
    result = await crud.apply_time_offset(session, request.episodeIds, request.offsetSeconds)
    return TimeOffsetResponse(**result)


@router.post(
    "/danmaku/split",
    response_model=SplitResponse,
    summary="分集拆分"
)
async def split_episode_danmaku(
    request: SplitRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """将一个分集的弹幕按时间范围拆分到多个新分集"""
    splits = [s.model_dump() for s in request.splits]
    result = await crud.split_episode_danmaku(
        session,
        request.sourceEpisodeId,
        splits,
        request.deleteSource,
        request.resetTime,
        config_manager
    )
    if not result.get("success"):
        return SplitResponse(success=False, error=result.get("error"))
    return SplitResponse(
        success=True,
        newEpisodes=[NewEpisodeInfo(**ep) for ep in result.get("newEpisodes", [])]
    )


@router.post(
    "/danmaku/merge",
    response_model=MergeResponse,
    summary="分集合并"
)
async def merge_episodes_danmaku(
    request: MergeRequest,
    current_user: models.User = Depends(security.get_current_user),
    session: AsyncSession = Depends(get_db_session),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """将多个分集的弹幕合并到一个新分集"""
    source_episodes = [s.model_dump() for s in request.sourceEpisodes]
    result = await crud.merge_episodes_danmaku(
        session,
        source_episodes,
        request.targetEpisodeIndex,
        request.targetTitle,
        request.deleteSources,
        request.deduplicate,
        config_manager
    )
    return MergeResponse(**result)

