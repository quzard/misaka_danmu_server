"""
UI API共享的Pydantic模型
这些模型被多个API端点模块使用
"""

from typing import Optional, List, Dict, Union
from datetime import datetime
from pydantic import BaseModel, Field


class UITaskResponse(BaseModel):
    """后台任务响应"""
    message: str
    taskId: str


class UIProviderSearchResponse(BaseModel):
    """扩展了 ProviderSearchResponse 以包含原始搜索的上下文"""
    results: List[Dict] = Field([], description="主搜索结果列表")
    search_season: Optional[int] = None
    search_episode: Optional[int] = None
    supplemental_results: List[Dict] = Field([], description="来自补充源（如360, Douban）的搜索结果")


class RefreshPosterRequest(BaseModel):
    """刷新海报请求"""
    imageUrl: str


class ReassociationRequest(BaseModel):
    """重新关联请求"""
    targetAnimeId: int


class BulkDeleteEpisodesRequest(BaseModel):
    """批量删除分集请求"""
    episodeIds: List[int] = Field(..., alias="episode_ids")

    class Config:
        populate_by_name = True


class BulkDeleteRequest(BaseModel):
    """批量删除数据源请求"""
    sourceIds: List[int] = Field(..., alias="source_ids")

    class Config:
        populate_by_name = True


class ProxyTestResult(BaseModel):
    """代理测试结果"""
    status: str  # 'success' or 'failure'
    latency: Optional[float] = None  # in ms
    error: Optional[str] = None


class ProxyTestRequest(BaseModel):
    """代理测试请求"""
    proxy_url: Optional[str] = None


class FullProxyTestResponse(BaseModel):
    """完整代理测试响应"""
    proxy_connectivity: ProxyTestResult
    target_sites: Dict[str, ProxyTestResult]


class TitleRecognitionContent(BaseModel):
    """识别词内容模型"""
    content: str = Field(..., description="识别词配置内容")


class TitleRecognitionUpdateResponse(BaseModel):
    """识别词更新响应模型"""
    success: bool = Field(..., description="是否更新成功")
    warnings: List[str] = Field(default_factory=list, description="解析过程中的警告信息")


class ApiTokenUpdate(BaseModel):
    """API Token更新请求"""
    name: str = Field(..., min_length=1, max_length=50, description="Token的描述性名称")
    dailyCallLimit: int = Field(..., description="每日调用次数限制, -1 表示无限")
    validityPeriod: str = Field(..., description="新的有效期: 'permanent', 'custom', '30d' 等")


class CustomDanmakuPathRequest(BaseModel):
    """自定义弹幕路径请求"""
    enabled: str
    template: str


class CustomDanmakuPathResponse(BaseModel):
    """自定义弹幕路径响应"""
    enabled: str
    template: str


class MatchFallbackTokensResponse(BaseModel):
    """匹配后备Token响应"""
    value: str


class ConfigValueResponse(BaseModel):
    """配置值响应"""
    value: str


class ConfigValueRequest(BaseModel):
    """配置值请求"""
    value: str


class TmdbReverseLookupConfig(BaseModel):
    """TMDB反查配置"""
    enabled: bool
    sources: List[str]  # 启用反查的源列表，如 ['imdb', 'tvdb', 'douban', 'bangumi']


class TmdbReverseLookupConfigRequest(BaseModel):
    """TMDB反查配置请求"""
    enabled: bool
    sources: List[str]


class ImportFromUrlRequest(BaseModel):
    """从URL导入请求"""
    provider: str
    url: str
    title: str
    media_type: str
    season: int


class GlobalFilterSettings(BaseModel):
    """全局过滤设置"""
    cn: str
    eng: str


class RateLimitProviderStatus(BaseModel):
    """流控提供商状态"""
    providerName: str
    requestCount: int
    quota: Union[int, str]  # Can be a number or "∞"


class FallbackRateLimitStatus(BaseModel):
    """后备流控状态"""
    totalCount: int
    totalLimit: int
    matchCount: int
    searchCount: int


class RateLimitStatusResponse(BaseModel):
    """流控状态响应"""
    enabled: bool  # 改为enabled以匹配前端
    verificationFailed: bool = Field(False, description="配置文件验证是否失败")
    globalRequestCount: int
    globalLimit: int
    globalPeriod: str
    secondsUntilReset: int
    providers: List[RateLimitProviderStatus]
    fallback: Optional[FallbackRateLimitStatus] = None


class WebhookSettings(BaseModel):
    """Webhook设置"""
    webhookEnabled: bool
    webhookDelayedImportEnabled: bool
    webhookDelayedImportHours: int
    webhookCustomDomain: str
    webhookFilterMode: str
    webhookFilterRegex: str
    webhookLogRawRequest: bool
    webhookFallbackEnabled: bool


class WebhookTaskItem(BaseModel):
    """Webhook任务项"""
    id: int
    receptionTime: datetime
    executeTime: datetime
    webhookSource: str
    status: str
    taskTitle: str

    class Config:
        from_attributes = True


class PaginatedWebhookTasksResponse(BaseModel):
    """分页Webhook任务响应"""
    total: int
    list: List[WebhookTaskItem]


class AITestRequest(BaseModel):
    """AI测试请求"""
    provider: str
    apiKey: str
    baseUrl: Optional[str] = None
    model: str


class AITestResponse(BaseModel):
    """AI测试响应"""
    success: bool
    message: str
    latency: Optional[float] = None  # 响应时间(毫秒)
    error: Optional[str] = None

