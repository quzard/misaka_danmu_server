from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Index,
    String, TypeDecorator, UniqueConstraint, DECIMAL, func
)
from sqlalchemy.dialects.postgresql import TEXT as PG_TEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from .timezone import get_now

class NaiveDateTime(TypeDecorator):
    """
    自定义数据库类型，确保无论数据库驱动返回何种datetime对象，
    在应用层面我们得到的都是不带时区信息的（naive）datetime。
    这解决了PostgreSQL驱动返回带时区时间，而MySQL驱动返回不带时区时间的不一致性问题。
    使用 DateTime 而非 TIMESTAMP，避免 MySQL 自动进行时区转换。

    注意：此类型已废弃，迁移后使用 TextTime。
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect: Any) -> Optional[datetime]:
        """在写入数据库时，移除时区信息。"""
        if value is not None and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: Optional[datetime], dialect: Any) -> Optional[datetime]:
        """从数据库读取时，移除时区信息。"""
        if value is not None and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value


class TextTime(TypeDecorator):
    """
    时间存储为文本类型 - MySQL: VARCHAR(50), PostgreSQL: TEXT
    格式: YYYY-MM-DD HH:MM:SS (不包含微秒)

    用途：数据库迁移后，所有时间字段使用此类型。

    注意：MySQL 使用 VARCHAR(50) 而非 LONGTEXT，原因：
    - 部分时间字段有索引（如 expires_at, created_at）
    - MySQL 不允许 LONGTEXT 字段有索引
    - VARCHAR(50) 足够存储时间字符串，同时支持索引
    """
    impl = String(50)  # 默认长度 50
    cache_ok = True

    def load_dialect_impl(self, dialect):
        """根据数据库类型返回对应的文本类型"""
        if dialect.name == 'mysql':
            return dialect.type_descriptor(String(50))  # VARCHAR(50)
        else:  # PostgreSQL
            return dialect.type_descriptor(PG_TEXT)

    def process_bind_param(self, value, dialect):
        """写入数据库：datetime/str → "YYYY-MM-DD HH:MM:SS" """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, str):
            # 如果已经是字符串，去掉微秒
            if '.' in value:
                return value.split('.')[0]
            return value
        return value

    def process_result_value(self, value, dialect):
        """从数据库读取：保持字符串格式"""
        if value is None:
            return None
        if isinstance(value, str) and '.' in value:
            return value.split('.')[0]
        return value


class LongText(TypeDecorator):
    """
    长文本类型 - MySQL: TEXT (64KB), PostgreSQL: TEXT

    用途：数据库迁移后，普通字符串字段使用此类型。

    TEXT 类型足够大（64KB），适用于标题、URL、路径等场景。
    """
    impl = PG_TEXT
    cache_ok = True

    def load_dialect_impl(self, dialect):
        """根据数据库类型返回对应的文本类型"""
        if dialect.name == 'mysql':
            from sqlalchemy.dialects.mysql import TEXT as MySQL_TEXT
            return dialect.type_descriptor(MySQL_TEXT)  # TEXT (64KB)
        else:  # PostgreSQL
            return dialect.type_descriptor(PG_TEXT)

class VeryLongText(TypeDecorator):
    """
    超长文本类型 - MySQL: LONGTEXT (4GB), PostgreSQL: TEXT

    用途：数据库迁移后，需要存储大量数据的字段使用此类型。

    适用场景：配置值、缓存数据、日志消息、任务参数等。
    """
    impl = PG_TEXT
    cache_ok = True

    def load_dialect_impl(self, dialect):
        """根据数据库类型返回对应的文本类型"""
        if dialect.name == 'mysql':
            from sqlalchemy.dialects.mysql import LONGTEXT as MySQL_LONGTEXT
            return dialect.type_descriptor(MySQL_LONGTEXT)  # LONGTEXT (4GB)
        else:  # PostgreSQL
            return dialect.type_descriptor(PG_TEXT)


class Base(DeclarativeBase):
    pass

class Anime(Base):
    __tablename__ = "anime"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(LongText, index=True)
    type: Mapped[str] = mapped_column(Enum('tv_series', 'movie', 'ova', 'other', name="anime_type"), default='tv_series')
    imageUrl: Mapped[Optional[str]] = mapped_column("image_url", LongText)
    localImagePath: Mapped[Optional[str]] = mapped_column("local_image_path", LongText)
    season: Mapped[int] = mapped_column(BigInteger, default=1)
    episodeCount: Mapped[Optional[int]] = mapped_column("episode_count", BigInteger)
    year: Mapped[Optional[int]] = mapped_column("year", BigInteger)
    createdAt: Mapped[str] = mapped_column("created_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"), nullable=False)

    sources: Mapped[List["AnimeSource"]] = relationship(back_populates="anime", cascade="all, delete-orphan")
    metadataRecord: Mapped["AnimeMetadata"] = relationship(back_populates="anime", cascade="all, delete-orphan", uselist=False)
    aliases: Mapped["AnimeAlias"] = relationship(back_populates="anime", cascade="all, delete-orphan", uselist=False)

    __table_args__ = (
        Index('idx_title_fulltext', 'title'),
    )

class AnimeSource(Base):
    __tablename__ = "anime_sources"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    animeId: Mapped[int] = mapped_column("anime_id", ForeignKey("anime.id", ondelete="CASCADE"))
    sourceOrder: Mapped[int] = mapped_column("source_order", BigInteger)
    providerName: Mapped[str] = mapped_column("provider_name", LongText)
    mediaId: Mapped[str] = mapped_column("media_id", LongText)
    isFavorited: Mapped[bool] = mapped_column("is_favorited", Boolean, default=False)
    incrementalRefreshEnabled: Mapped[bool] = mapped_column("incremental_refresh_enabled", Boolean, default=False)
    incrementalRefreshFailures: Mapped[int] = mapped_column("incremental_refresh_failures", BigInteger, default=0)
    lastRefreshLatestEpisodeAt: Mapped[Optional[str]] = mapped_column("last_refresh_latest_episode_at", TextTime, nullable=True)
    createdAt: Mapped[str] = mapped_column("created_at", TextTime)

    anime: Mapped["Anime"] = relationship(back_populates="sources")
    episodes: Mapped[List["Episode"]] = relationship(back_populates="source", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('anime_id', 'provider_name', 'media_id', name='idx_anime_provider_media_unique'),
        UniqueConstraint('anime_id', 'source_order', name='idx_anime_source_order_unique'),
    )

class Episode(Base):
    __tablename__ = "episode"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sourceId: Mapped[int] = mapped_column("source_id", ForeignKey("anime_sources.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(LongText)
    episodeIndex: Mapped[int] = mapped_column("episode_index", BigInteger)
    providerEpisodeId: Mapped[Optional[str]] = mapped_column("provider_episode_id", LongText)
    sourceUrl: Mapped[Optional[str]] = mapped_column("source_url", LongText)
    danmakuFilePath: Mapped[Optional[str]] = mapped_column("danmaku_file_path", LongText)
    fetchedAt: Mapped[Optional[str]] = mapped_column("fetched_at", TextTime)
    commentCount: Mapped[int] = mapped_column("comment_count", BigInteger, default=0)

    source: Mapped["AnimeSource"] = relationship(back_populates="episodes")

    __table_args__ = (UniqueConstraint('source_id', 'episode_index', name='idx_source_episode_unique'),)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(LongText, unique=True)
    hashedPassword: Mapped[str] = mapped_column("hashed_password", LongText)
    token: Mapped[Optional[str]] = mapped_column(LongText)
    tokenUpdate: Mapped[Optional[str]] = mapped_column("token_update", TextTime)
    createdAt: Mapped[str] = mapped_column("created_at", TextTime)

    # 关联会话
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    """用户会话表，用于多端登录管理"""
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    userId: Mapped[int] = mapped_column("user_id", BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    jti: Mapped[str] = mapped_column(LongText, unique=True, index=True)  # JWT ID
    ipAddress: Mapped[Optional[str]] = mapped_column("ip_address", LongText)
    userAgent: Mapped[Optional[str]] = mapped_column("user_agent", LongText)
    createdAt: Mapped[str] = mapped_column("created_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))
    lastUsedAt: Mapped[Optional[str]] = mapped_column("last_used_at", TextTime)
    expiresAt: Mapped[Optional[str]] = mapped_column("expires_at", TextTime)
    isRevoked: Mapped[bool] = mapped_column("is_revoked", Boolean, default=False)

    # 关联用户
    user: Mapped["User"] = relationship(back_populates="sessions")


class Scraper(Base):
    __tablename__ = "scrapers"
    providerName: Mapped[str] = mapped_column("provider_name", LongText, primary_key=True)
    isEnabled: Mapped[bool] = mapped_column("is_enabled", Boolean, default=True)
    displayOrder: Mapped[int] = mapped_column("display_order", BigInteger, default=0)
    useProxy: Mapped[bool] = mapped_column("use_proxy", Boolean, default=False)

class MetadataSource(Base):
    __tablename__ = "metadata_sources"
    providerName: Mapped[str] = mapped_column("provider_name", LongText, primary_key=True)
    isEnabled: Mapped[bool] = mapped_column("is_enabled", Boolean, default=True)
    isAuxSearchEnabled: Mapped[bool] = mapped_column("is_aux_search_enabled", Boolean, default=True)
    displayOrder: Mapped[int] = mapped_column("display_order", BigInteger, default=0)
    useProxy: Mapped[bool] = mapped_column("use_proxy", Boolean, default=True)
    isFailoverEnabled: Mapped[bool] = mapped_column("is_failover_enabled", Boolean, default=False)
    logRawResponses: Mapped[bool] = mapped_column("log_raw_responses", Boolean, default=False, nullable=False)

class AnimeMetadata(Base):
    __tablename__ = "anime_metadata"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    animeId: Mapped[int] = mapped_column("anime_id", ForeignKey("anime.id", ondelete="CASCADE"), unique=True)
    tmdbId: Mapped[Optional[str]] = mapped_column("tmdb_id", LongText)
    tmdbEpisodeGroupId: Mapped[Optional[str]] = mapped_column("tmdb_episode_group_id", LongText)
    imdbId: Mapped[Optional[str]] = mapped_column("imdb_id", LongText)
    tvdbId: Mapped[Optional[str]] = mapped_column("tvdb_id", LongText)
    doubanId: Mapped[Optional[str]] = mapped_column("douban_id", LongText)
    bangumiId: Mapped[Optional[str]] = mapped_column("bangumi_id", LongText)

    anime: Mapped["Anime"] = relationship(back_populates="metadataRecord")

class Config(Base):
    __tablename__ = "config"
    configKey: Mapped[str] = mapped_column("config_key", LongText, primary_key=True)
    configValue: Mapped[str] = mapped_column("config_value", VeryLongText)  # 超大字段：配置可能很长
    description: Mapped[Optional[str]] = mapped_column(LongText)

class CacheData(Base):
    __tablename__ = "cache_data"
    cacheProvider: Mapped[Optional[str]] = mapped_column("cache_provider", LongText)
    cacheKey: Mapped[str] = mapped_column("cache_key", LongText, primary_key=True)
    cacheValue: Mapped[str] = mapped_column("cache_value", VeryLongText)  # 超大字段：缓存数据可能很大
    expiresAt: Mapped[str] = mapped_column("expires_at", TextTime, index=True)

class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(LongText)
    token: Mapped[str] = mapped_column(LongText, unique=True)
    isEnabled: Mapped[bool] = mapped_column("is_enabled", Boolean, default=True)
    createdAt: Mapped[str] = mapped_column("created_at", TextTime)
    expiresAt: Mapped[Optional[str]] = mapped_column("expires_at", TextTime)
    dailyCallLimit: Mapped[int] = mapped_column("daily_call_limit", BigInteger, default=500, server_default="500", nullable=False)
    dailyCallCount: Mapped[int] = mapped_column("daily_call_count", BigInteger, default=0, server_default="0", nullable=False)
    lastCallAt: Mapped[Optional[str]] = mapped_column("last_call_at", TextTime)

class TokenAccessLog(Base):
    __tablename__ = "token_access_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tokenId: Mapped[int] = mapped_column("token_id", BigInteger)
    ipAddress: Mapped[str] = mapped_column("ip_address", LongText)
    userAgent: Mapped[Optional[str]] = mapped_column("user_agent", LongText)
    accessTime: Mapped[str] = mapped_column("access_time", TextTime)
    status: Mapped[str] = mapped_column(LongText)
    path: Mapped[Optional[str]] = mapped_column(LongText)

    __table_args__ = (Index('idx_token_id_time', 'token_id', 'access_time'),)

class UaRule(Base):
    __tablename__ = "ua_rules"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    uaString: Mapped[str] = mapped_column("ua_string", LongText, unique=True)
    createdAt: Mapped[str] = mapped_column("created_at", TextTime)

class BangumiAuth(Base):
    __tablename__ = "bangumi_auth"
    userId: Mapped[int] = mapped_column("user_id", BigInteger, primary_key=True)
    bangumiUserId: Mapped[Optional[int]] = mapped_column("bangumi_user_id", BigInteger)
    nickname: Mapped[Optional[str]] = mapped_column(LongText)
    avatarUrl: Mapped[Optional[str]] = mapped_column("avatar_url", LongText)
    accessToken: Mapped[str] = mapped_column("access_token", LongText)
    refreshToken: Mapped[Optional[str]] = mapped_column("refresh_token", LongText)
    expiresAt: Mapped[Optional[str]] = mapped_column("expires_at", TextTime)
    authorizedAt: Mapped[Optional[str]] = mapped_column("authorized_at", TextTime)

class OauthState(Base):
    __tablename__ = "oauth_states"
    stateKey: Mapped[str] = mapped_column("state_key", LongText, primary_key=True)
    userId: Mapped[int] = mapped_column("user_id", BigInteger)
    expiresAt: Mapped[str] = mapped_column("expires_at", TextTime, index=True)

class AnimeAlias(Base):
    __tablename__ = "anime_aliases"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    animeId: Mapped[int] = mapped_column("anime_id", ForeignKey("anime.id", ondelete="CASCADE"), unique=True)
    nameEn: Mapped[Optional[str]] = mapped_column("name_en", LongText)
    nameJp: Mapped[Optional[str]] = mapped_column("name_jp", LongText)
    nameRomaji: Mapped[Optional[str]] = mapped_column("name_romaji", LongText)
    aliasCn1: Mapped[Optional[str]] = mapped_column("alias_cn_1", LongText)
    aliasCn2: Mapped[Optional[str]] = mapped_column("alias_cn_2", LongText)
    aliasCn3: Mapped[Optional[str]] = mapped_column("alias_cn_3", LongText)
    aliasLocked: Mapped[bool] = mapped_column("alias_locked", Boolean, default=False, server_default="0")

    anime: Mapped["Anime"] = relationship(back_populates="aliases")

class TmdbEpisodeMapping(Base):
    __tablename__ = "tmdb_episode_mapping"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tmdbTvId: Mapped[int] = mapped_column("tmdb_tv_id", BigInteger)
    tmdbEpisodeGroupId: Mapped[str] = mapped_column("tmdb_episode_group_id", LongText)
    tmdbEpisodeId: Mapped[int] = mapped_column("tmdb_episode_id", BigInteger)
    tmdbSeasonNumber: Mapped[int] = mapped_column("tmdb_season_number", BigInteger)
    tmdbEpisodeNumber: Mapped[int] = mapped_column("tmdb_episode_number", BigInteger)
    customSeasonNumber: Mapped[int] = mapped_column("custom_season_number", BigInteger)
    customEpisodeNumber: Mapped[int] = mapped_column("custom_episode_number", BigInteger)
    absoluteEpisodeNumber: Mapped[int] = mapped_column("absolute_episode_number", BigInteger)

    __table_args__ = (
        UniqueConstraint('tmdb_episode_group_id', 'tmdb_episode_id', name='idx_group_episode_unique'),
        Index('idx_custom_season_episode', 'tmdb_tv_id', 'tmdb_episode_group_id', 'custom_season_number', 'custom_episode_number'),
        Index('idx_absolute_episode', 'tmdb_tv_id', 'tmdb_episode_group_id', 'absolute_episode_number'),
    )

class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    # 修正：将Python属性名从 'id' 改为 'taskId'，以匹配API响应模型，同时保持数据库列名为 'id'
    taskId: Mapped[str] = mapped_column("id", LongText, primary_key=True)
    name: Mapped[str] = mapped_column(LongText)
    jobType: Mapped[str] = mapped_column("job_type", LongText)
    cronExpression: Mapped[str] = mapped_column("cron_expression", LongText)
    isEnabled: Mapped[bool] = mapped_column("is_enabled", Boolean, default=True)
    lastRunAt: Mapped[Optional[str]] = mapped_column("last_run_at", TextTime)
    nextRunAt: Mapped[Optional[str]] = mapped_column("next_run_at", TextTime)

class WebhookTask(Base):
    __tablename__ = "webhook_tasks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    receptionTime: Mapped[str] = mapped_column("reception_time", TextTime, index=True)
    executeTime: Mapped[str] = mapped_column("execute_time", TextTime, index=True)
    webhookSource: Mapped[str] = mapped_column("webhook_source", LongText)
    status: Mapped[str] = mapped_column(LongText, default="pending", index=True) # pending, processing, failed, submitted
    payload: Mapped[str] = mapped_column(VeryLongText)  # 超大字段：webhook payload 可能很大
    uniqueKey: Mapped[str] = mapped_column("unique_key", LongText, unique=True)
    taskTitle: Mapped[str] = mapped_column("task_title", LongText)

    __table_args__ = (Index('idx_status_execute_time', 'status', 'execute_time'),)

class TaskHistory(Base):
    __tablename__ = "task_history"
    # 修正：将Python属性名从 'id' 改为 'taskId'，以匹配Pydantic模型，同时保持数据库列名为 'id'
    taskId: Mapped[str] = mapped_column("id", LongText, primary_key=True)
    scheduledTaskId: Mapped[Optional[str]] = mapped_column("scheduled_task_id", ForeignKey("scheduled_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(LongText)
    status: Mapped[str] = mapped_column(LongText)
    progress: Mapped[int] = mapped_column(BigInteger, default=0)
    description: Mapped[Optional[str]] = mapped_column(VeryLongText)  # 超大字段：任务描述可能很长
    createdAt: Mapped[str] = mapped_column("created_at", TextTime)
    updatedAt: Mapped[str] = mapped_column("updated_at", TextTime)
    finishedAt: Mapped[Optional[str]] = mapped_column("finished_at", TextTime)
    uniqueKey: Mapped[Optional[str]] = mapped_column("unique_key", LongText, index=True)
    queueType: Mapped[str] = mapped_column("queue_type", LongText, default="download", server_default="download")
    # 任务恢复相关字段：在提交时保存，用于重启后恢复排队中的任务
    taskType: Mapped[Optional[str]] = mapped_column("task_type", LongText, nullable=True)
    taskParameters: Mapped[Optional[str]] = mapped_column("task_parameters", VeryLongText, nullable=True)  # 超大字段：任务参数 JSON 可能很大

    __table_args__ = (Index('idx_created_at', 'created_at'),)

class TaskStateCache(Base):
    """任务状态缓存表，用于存储正在执行任务的参数，支持服务重启后的任务恢复"""
    __tablename__ = "task_state_cache"
    taskId: Mapped[str] = mapped_column("task_id", LongText, primary_key=True)
    taskType: Mapped[str] = mapped_column("task_type", LongText)  # 任务类型，如 'generic_import', 'match_fallback'
    taskParameters: Mapped[str] = mapped_column("task_parameters", VeryLongText)  # 超大字段：任务参数 JSON 可能很大
    createdAt: Mapped[str] = mapped_column("created_at", TextTime)
    updatedAt: Mapped[str] = mapped_column("updated_at", TextTime)

    __table_args__ = (Index('idx_task_type', 'task_type'),)

class ExternalApiLog(Base):
    __tablename__ = "external_api_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accessTime: Mapped[str] = mapped_column("access_time", TextTime)
    ipAddress: Mapped[str] = mapped_column("ip_address", LongText)
    endpoint: Mapped[str] = mapped_column(LongText)
    statusCode: Mapped[int] = mapped_column("status_code", BigInteger)
    message: Mapped[Optional[str]] = mapped_column(VeryLongText)  # 超大字段：日志消息可能很长

class RateLimitState(Base):
    __tablename__ = "rate_limit_state"
    providerName: Mapped[str] = mapped_column("provider_name", LongText, primary_key=True)
    requestCount: Mapped[int] = mapped_column("request_count", BigInteger, default=0)
    lastResetTime: Mapped[str] = mapped_column("last_reset_time", TextTime)
    checksum: Mapped[Optional[str]] = mapped_column(LongText, nullable=True, default=None)

class TitleRecognition(Base):
    """识别词配置表 - 单记录全量存储"""
    __tablename__ = "title_recognition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(VeryLongText)  # 超大字段：识别词列表可能很长
    created_at: Mapped[str] = mapped_column("created_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: Mapped[str] = mapped_column("updated_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"), onupdate=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))


class MediaServer(Base):
    """媒体服务器配置表"""
    __tablename__ = "media_servers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(LongText)
    providerName: Mapped[str] = mapped_column("provider_name", LongText)  # emby, jellyfin, plex
    url: Mapped[str] = mapped_column(LongText)
    apiToken: Mapped[str] = mapped_column("api_token", LongText)
    isEnabled: Mapped[bool] = mapped_column("is_enabled", Boolean, default=True)
    selectedLibraries: Mapped[Optional[str]] = mapped_column("selected_libraries", LongText)  # JSON array
    filterRules: Mapped[Optional[str]] = mapped_column("filter_rules", LongText)  # JSON object
    createdAt: Mapped[str] = mapped_column("created_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))
    updatedAt: Mapped[str] = mapped_column("updated_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"), onupdate=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))

    mediaItems: Mapped[List["MediaItem"]] = relationship(back_populates="server", cascade="all, delete-orphan")


class MediaItem(Base):
    """扫描到的媒体项"""
    __tablename__ = "media_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    serverId: Mapped[int] = mapped_column("server_id", ForeignKey("media_servers.id", ondelete="CASCADE"))
    mediaId: Mapped[str] = mapped_column("media_id", LongText)  # 媒体服务器中的ID
    libraryId: Mapped[Optional[str]] = mapped_column("library_id", LongText)  # 所属媒体库ID
    title: Mapped[str] = mapped_column(LongText)
    mediaType: Mapped[str] = mapped_column("media_type", Enum('movie', 'tv_series', name="media_item_type"))
    season: Mapped[Optional[int]] = mapped_column(BigInteger)
    episode: Mapped[Optional[int]] = mapped_column(BigInteger)
    year: Mapped[Optional[int]] = mapped_column(BigInteger)
    tmdbId: Mapped[Optional[str]] = mapped_column("tmdb_id", LongText)
    tvdbId: Mapped[Optional[str]] = mapped_column("tvdb_id", LongText)
    imdbId: Mapped[Optional[str]] = mapped_column("imdb_id", LongText)
    posterUrl: Mapped[Optional[str]] = mapped_column("poster_url", LongText)
    isImported: Mapped[bool] = mapped_column("is_imported", Boolean, default=False)
    createdAt: Mapped[str] = mapped_column("created_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))
    updatedAt: Mapped[str] = mapped_column("updated_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"), onupdate=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))

    server: Mapped["MediaServer"] = relationship(back_populates="mediaItems")

    __table_args__ = (
        UniqueConstraint('server_id', 'media_id', name='idx_server_media_unique'),
        Index('idx_media_type', 'media_type'),
        Index('idx_is_imported', 'is_imported'),
    )


class LocalDanmakuItem(Base):
    """本地扫描的弹幕文件"""
    __tablename__ = "local_danmaku_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filePath: Mapped[str] = mapped_column("file_path", LongText)  # .xml文件路径
    title: Mapped[str] = mapped_column(LongText)  # 标题
    mediaType: Mapped[str] = mapped_column("media_type", Enum('movie', 'tv_series', name="local_media_type"))
    season: Mapped[Optional[int]] = mapped_column(BigInteger)  # 季度
    episode: Mapped[Optional[int]] = mapped_column(BigInteger)  # 集数
    year: Mapped[Optional[int]] = mapped_column(BigInteger)  # 年份
    tmdbId: Mapped[Optional[str]] = mapped_column("tmdb_id", LongText)
    tvdbId: Mapped[Optional[str]] = mapped_column("tvdb_id", LongText)
    imdbId: Mapped[Optional[str]] = mapped_column("imdb_id", LongText)
    posterUrl: Mapped[Optional[str]] = mapped_column("poster_url", LongText)
    nfoPath: Mapped[Optional[str]] = mapped_column("nfo_path", LongText)  # nfo文件路径
    isImported: Mapped[bool] = mapped_column("is_imported", Boolean, default=False)
    createdAt: Mapped[str] = mapped_column("created_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))
    updatedAt: Mapped[str] = mapped_column("updated_at", TextTime, default=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"), onupdate=lambda: get_now().strftime("%Y-%m-%d %H:%M:%S"))

    __table_args__ = (
        Index('idx_local_file_path', 'file_path', mysql_length=255),
        Index('idx_local_media_type', 'media_type'),
        Index('idx_local_is_imported', 'is_imported'),
    )
