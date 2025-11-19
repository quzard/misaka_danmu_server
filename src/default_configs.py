"""
默认配置定义
每个配置项格式: (默认值, 描述)

注意: 某些配置需要在运行时动态生成(如jwtSecretKey),这些配置在main.py中单独处理
"""

def get_default_configs(settings=None, ai_prompts=None):
    """
    获取默认配置字典

    Args:
        settings: FastAPI settings对象,用于获取JWT过期时间等配置
        ai_prompts: AI提示词字典,包含DEFAULT_AI_MATCH_PROMPT等

    Returns:
        dict: 默认配置字典
    """
    configs = {
        # 缓存 TTL
        'searchTtlSeconds': (10800, '搜索结果的缓存时间（秒），最低3小时。'),
        'episodesTtlSeconds': (10800, '分集列表的缓存时间（秒），最低3小时。'),
        'baseInfoTtlSeconds': (10800, '基础媒体信息（如爱奇艺）的缓存时间（秒），最低3小时。'),
        'metadataSearchTtlSeconds': (10800, '元数据（如TMDB, Bangumi）搜索结果的缓存时间（秒），最低3小时。'),

        # API 和 Webhook
        'customApiDomain': ('', '用于拼接弹幕API地址的自定义域名。'),
        'webhookApiKey': ('', '用于Webhook调用的安全密钥。'),
        'trustedProxies': ('', '受信任的反向代理IP列表，用逗号分隔。当请求来自这些IP时，将从 X-Forwarded-For 或 X-Real-IP 头中解析真实客户端IP。'),
        'webhookEnabled': ('true', '是否全局启用 Webhook 功能。'),
        'webhookDelayedImportEnabled': ('false', '是否为 Webhook 触发的导入启用延时。'),
        'webhookDelayedImportHours': ('24', 'Webhook 延时导入的小时数。'),
        'webhookFilterMode': ('blacklist', 'Webhook 标题过滤模式 (blacklist/whitelist)。'),
        'webhookFilterRegex': ('', '用于过滤 Webhook 标题的正则表达式。'),
        'webhookLogRawRequest': ('false', '是否记录 Webhook 的原始请求体。'),
        'externalApiKey': ('', '用于外部API调用的安全密钥。'),
        'externalApiDuplicateTaskThresholdHours': (3, '（外部API）重复任务提交阈值（小时）。在此时长内，不允许为同一媒体提交重复的自动导入任务。0为禁用。'),
        'webhookCustomDomain': ('', '用于拼接Webhook URL的自定义域名。'),

        # 代理
        'proxyUrl': ('', '全局HTTP/HTTPS/SOCKS5代理地址。'),
        'proxyEnabled': ('false', '是否全局启用代理。'),
        'proxySslVerify': ('true', '使用HTTPS代理时是否验证SSL证书。设为false可解决自签名证书问题。'),

        # 元数据源
        'tmdbApiKey': ('', '用于访问 The Movie Database API 的密钥。'),
        'tmdbApiBaseUrl': ('https://api.themoviedb.org', 'TMDB API 的基础域名。'),
        'tmdbImageBaseUrl': ('https://image.tmdb.org', 'TMDB 图片服务的基础 URL。'),
        'tvdbApiKey': ('', '用于访问 TheTVDB API 的密钥。'),
        'bangumiClientId': ('', '用于Bangumi OAuth的App ID。'),
        'bangumiClientSecret': ('', '用于Bangumi OAuth的App Secret。'),
        'doubanCookie': ('', '用于访问豆瓣API的Cookie。'),
        'imdbUseApi': ('true', 'IMDb是否使用第三方API (api.imdbapi.dev) 而不是官方网站HTML解析。'),
        'imdbEnableFallback': ('true', 'IMDb是否启用兜底机制。当主方式失败时,自动尝试另一种方式。'),

        # 弹幕源
        'danmakuOutputLimitPerSource': ('-1', '弹幕输出上限。-1为无限制。超出限制时按时间段均匀采样。'),
        'danmakuAggregationEnabled': ('true', '是否启用跨源弹幕聚合功能。'),
        'scraperVerificationEnabled': ('false', '是否启用搜索源签名验证。'),
        'bilibiliCookie': ('', '用于访问B站API的Cookie，特别是buvid3。'),
        'gamerCookie': ('', '用于访问巴哈姆特动画疯的Cookie。'),
        'matchFallbackEnabled': ('false', '是否为匹配接口启用后备机制（自动搜索导入）。'),
        'matchFallbackBlacklist': ('', '匹配后备黑名单，使用正则表达式过滤文件名，匹配的文件不会触发后备机制。'),
        'searchFallbackEnabled': ('false', '是否为搜索接口启用后备搜索功能（全网搜索）。'),

        # 弹幕文件路径配置
        'customDanmakuPathEnabled': ('false', '是否启用自定义弹幕文件保存路径。'),
        'movieDanmakuDirectoryPath': ('/app/config/danmaku/movies', '电影/剧场版弹幕文件存储的根目录。'),
        'movieDanmakuFilenameTemplate': ('${title}/${episodeId}', '电影/剧场版弹幕文件命名模板。支持变量：${title}, ${season}, ${episode}, ${year}, ${provider}, ${animeId}, ${episodeId}, ${sourceId}。支持子目录。.xml后缀会自动添加。'),
        'tvDanmakuDirectoryPath': ('/app/config/danmaku/tv', '电视节目弹幕文件存储的根目录。'),
        'tvDanmakuFilenameTemplate': ('${animeId}/${episodeId}', '电视节目弹幕文件命名模板。支持变量：${title}, ${season}, ${episode}, ${year}, ${provider}, ${animeId}, ${episodeId}, ${sourceId}。支持子目录。.xml后缀会自动添加。'),

        'iqiyiUseProtobuf': ('false', '（爱奇艺）是否使用新的Protobuf弹幕接口（实验性）。'),
        'gamerUserAgent': ('', '用于访问巴哈姆特动画疯的User-Agent。'),

        # 搜索性能优化
        'searchMaxResultsPerSource': ('30', '每个搜索源最多返回的结果数量。设置较小的值可以提高搜索速度。'),

        # 全局过滤
        'search_result_global_blacklist_cn': (r'特典|预告|广告|菜单|花絮|特辑|速看|资讯|彩蛋|直拍|直播回顾|片头|片尾|幕后|映像|番外篇|纪录片|访谈|番外|短片|加更|走心|解忧|纯享|解读|揭秘|赏析', '用于过滤搜索结果标题的全局中文黑名单(正则表达式)。'),
        'search_result_global_blacklist_eng': (r'NC|OP|ED|SP|OVA|OAD|CM|PV|MV|BDMenu|Menu|Bonus|Recap|Teaser|Trailer|Preview|CD|Disc|Scan|Sample|Logo|Info|EDPV|SongSpot|BDSpot', '用于过滤搜索结果标题的全局英文黑名单(正则表达式)。'),

        'mysqlBinlogRetentionDays': (3, '（仅MySQL）自动清理多少天前的二进制日志（binlog）。0为不清理。需要SUPER或BINLOG_ADMIN权限。'),

        # 顺延机制配置
        'webhookFallbackEnabled': ('false', '是否启用Webhook顺延机制。当选中的源没有有效分集时，自动尝试下一个源。'),
        'externalApiFallbackEnabled': ('false', '是否启用外部控制API/匹配后备/后备搜索顺延机制。当选中的源没有有效分集时，自动尝试下一个源。'),

        # 预下载配置
        'preDownloadNextEpisodeEnabled': ('false', '是否启用预下载下一集弹幕。当播放当前集时，自动下载下一集的弹幕。需要启用匹配后备或后备搜索。'),

        # 媒体服务器配置
        'mediaServerAutoImport': ('false', '是否自动导入新扫描到的媒体项'),
        'mediaServerSyncInterval': ('3600', '媒体服务器同步间隔(秒)'),
    }

    # 添加需要settings的配置
    if settings:
        configs['jwtExpireMinutes'] = (settings.jwt.access_token_expire_minutes, 'JWT令牌的有效期（分钟）。-1 表示永不过期。')

    # 添加AI相关配置
    if ai_prompts:
        configs.update({
            'aiMatchEnabled': ('false', '是否启用AI智能匹配。启用后，在自动匹配场景(外部API、Webhook、匹配后备)中使用AI选择最佳搜索结果。'),
            'aiFallbackEnabled': ('true', '是否启用传统匹配兜底。当AI匹配失败时，自动降级到传统匹配算法。'),
            'aiProvider': ('deepseek', 'AI提供商: deepseek, openai, gemini'),
            'aiApiKey': ('', 'AI服务的API密钥'),
            'aiBaseUrl': ('', 'AI服务的Base URL (可选,用于自定义接口)'),
            'aiModel': ('deepseek-chat', 'AI模型名称,如: deepseek-chat, gpt-4, gemini-pro'),
            'aiPrompt': (ai_prompts.get('DEFAULT_AI_MATCH_PROMPT', ''), 'AI智能匹配提示词'),
            'aiRecognitionEnabled': ('false', '是否启用AI辅助识别。启用后，在TMDB自动刮削任务中使用AI识别标题和季度信息。'),
            'aiRecognitionPrompt': (ai_prompts.get('DEFAULT_AI_RECOGNITION_PROMPT', ''), 'AI辅助识别提示词'),
            'aiAliasCorrectionEnabled': ('false', '是否启用AI别名修正。启用后，在TMDB自动刮削任务中使用AI验证和修正别名。'),
            'aiAliasValidationPrompt': (ai_prompts.get('DEFAULT_AI_ALIAS_VALIDATION_PROMPT', ''), 'AI别名验证提示词'),
            'aiAliasExpansionEnabled': ('false', '是否启用AI别名扩展。启用后，当元数据源返回非中文标题时，使用AI生成可能的别名用于搜索。'),
            'aiAliasExpansionPrompt': (ai_prompts.get('DEFAULT_AI_ALIAS_EXPANSION_PROMPT', ''), 'AI别名扩展提示词'),
            'aiLogRawResponse': ('false', '是否记录AI原始响应到日志文件'),
        })

    return configs

