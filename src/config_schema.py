"""
参数配置 Schema 定义

配置项类型:
- string: 普通文本输入
- password: 密码输入（带遮罩）
- number: 数字输入
- boolean: 开关
- textarea: 多行文本
- select: 下拉选择

特殊字段:
- verifyEndpoint: 验证接口路径（如 Token 验证）
- suffix: 输入框后缀（如 "秒"）
- min/max: 数字输入的范围限制
- options: select 类型的选项列表
- placeholder: 输入框占位符
- description: 配置项描述
- rows: textarea 的行数
"""

CONFIG_SCHEMA = [
    {
        "key": "security",
        "label": "安全设置",
        "items": [
            {
                "key": "github_token",
                "label": "GitHub Token",
                "type": "password",
                "description": "用于请求 GitHub API，避免速率限制。无需任何权限，只需创建一个 Token 即可。",
                "placeholder": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "verifyEndpoint": "/api/ui/config/github-token/verify",
            },
            {
                "key": "trustedProxies",
                "label": "受信任的反向代理",
                "type": "textarea",
                "rows": 3,
                "description": "当请求来自这些IP时，将从 X-Forwarded-For 或 X-Real-IP 头中解析真实客户端IP。多个IP或CIDR网段请用英文逗号(,)分隔。",
                "placeholder": "例如: 127.0.0.1, 192.168.1.0/24, 10.0.0.1/32",
            },
            {
                "key": "jwtExpireMinutes",
                "label": "登录令牌有效期",
                "type": "number",
                "suffix": "分钟",
                "min": -1,
                "description": "JWT 令牌的有效期（分钟）。-1 表示永不过期。修改后需要重新登录生效。",
                "placeholder": "4320",
            },
        ],
    },
    {
        "key": "cache",
        "label": "缓存设置",
        "items": [
            {
                "key": "searchTtlSeconds",
                "label": "搜索缓存时间",
                "type": "number",
                "suffix": "秒",
                "min": 10800,
                "description": "搜索结果的缓存时间，最低3小时（10800秒）",
                "placeholder": "10800",
            },
            {
                "key": "episodesTtlSeconds",
                "label": "分集缓存时间",
                "type": "number",
                "suffix": "秒",
                "min": 10800,
                "description": "分集列表的缓存时间，最低3小时（10800秒）",
                "placeholder": "10800",
            },
            {
                "key": "baseInfoTtlSeconds",
                "label": "基础信息缓存时间",
                "type": "number",
                "suffix": "秒",
                "min": 10800,
                "description": "基础媒体信息的缓存时间，最低3小时（10800秒）",
                "placeholder": "10800",
            },
            {
                "key": "metadataSearchTtlSeconds",
                "label": "元数据搜索缓存时间",
                "type": "number",
                "suffix": "秒",
                "min": 10800,
                "description": "元数据（如TMDB, Bangumi）搜索结果的缓存时间，最低3小时（10800秒）",
                "placeholder": "10800",
            },
        ],
    },
    {
        "key": "performance",
        "label": "性能设置",
        "items": [
            {
                "key": "searchMaxResultsPerSource",
                "label": "每源最大搜索结果数",
                "type": "number",
                "min": 1,
                "max": 100,
                "description": "每个搜索源最多返回的结果数量。设置较小的值可以提高搜索速度。",
                "placeholder": "30",
            },
        ],
    },
    {
        "key": "database",
        "label": "数据库设置",
        "items": [
            {
                "key": "mysqlBinlogRetentionDays",
                "label": "MySQL Binlog 保留天数",
                "type": "number",
                "min": 0,
                "description": "（仅MySQL）自动清理多少天前的二进制日志（binlog）。0为不清理。需要SUPER或BINLOG_ADMIN权限。",
                "placeholder": "3",
            },
        ],
    },
]


def get_config_schema():
    """获取配置 Schema"""
    return CONFIG_SCHEMA

