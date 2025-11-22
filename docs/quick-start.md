# 🚀 快速开始 (使用 Docker Compose)

推荐使用 Docker 和 Docker Compose 进行一键部署。

## 步骤 1: 准备 `docker-compose.yaml`

1.  在一个合适的目录（例如 `~/danmuku`）下，创建 `docker-compose.yaml` 文件和所需的文件夹 `config，db-data`。

    ```bash
    mkdir -p ~/danmuku
    cd ~/danmuku
    mkdir -p db-data config
    touch docker-compose.yaml
    ```

2.  根据您选择的数据库，将以下内容之一复制到 `docker-compose.yaml` 文件中。

### 方案 A: 使用 MySQL (推荐)

> 💡 **内存优化提示**：如果您的服务器内存有限（如 1GB 以下的 VPS），建议使用 [MySQL 内存优化配置](mysql-optimization.md) 来减少内存占用。

```yaml
version: "3.8"
services:
  mysql:
    image: mysql:8.1.0-oracle
    container_name: danmu-mysql
    restart: unless-stopped
    environment:
      # !!! 重要：请务必替换为您的强密码 !!!
      MYSQL_ROOT_PASSWORD: "your_strong_root_password"                  #数据库root密码
      MYSQL_DATABASE: "danmuapi"                                        #数据库名称
      MYSQL_USER: "danmuapi"                                            #数据库用户名
      MYSQL_PASSWORD: "your_strong_user_password"                       #数据库密码
      TZ: "Asia/Shanghai"
    volumes:
      - ./db-data:/var/lib/mysql
    command:
      - '--character-set-server=utf8mb4'
      - '--collation-server=utf8mb4_unicode_ci'
      - '--binlog_expire_logs_seconds=259200' # 自动清理超过3天的binlog日志
      - '--default-authentication-plugin=mysql_native_password' # 使用传统密码认证方式
    healthcheck:
      # 使用mysqladmin ping命令进行健康检查，通过环境变量引用密码
      test: ["CMD-SHELL", "mysqladmin ping -u$${MYSQL_USER} -p$${MYSQL_PASSWORD}"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 30s

    networks:
      - misaka-net

  danmu-app:
    image: l429609201/misaka_danmu_server:latest
    container_name: misaka-danmu-server
    restart: unless-stopped
    depends_on:
      mysql:
        condition: service_healthy
    environment:
      # 设置运行容器的用户和组ID，以匹配您宿主机的用户，避免挂载卷的权限问题。
      - PUID=1000
      - PGID=1000
      - UMASK=0022
      - TZ=Asia/Shanghai
      # --- 数据库连接配置 ---
      - DANMUAPI_DATABASE__TYPE=mysql                         # 数据库类型
      - DANMUAPI_DATABASE__HOST=mysql                         # 使用服务名
      - DANMUAPI_DATABASE__PORT=3306                          # 端口号
      - DANMUAPI_DATABASE__NAME=danmuapi                      # 数据库名称
      # !!! 重要：请使用上面mysql容器相同的用户名和密码 !!!
      - DANMUAPI_DATABASE__USER=danmuapi                      #数据库用户名
      - DANMUAPI_DATABASE__PASSWORD=your_strong_user_password #数据库密码
      # --- 初始管理员配置 ---
      - DANMUAPI_ADMIN__INITIAL_USER=admin
    volumes:
      - ./config:/app/config
    ports:
      - "7768:7768"
    networks:
      - misaka-net

networks:
  misaka-net:
    driver: bridge
```

### 方案 B: 使用 PostgreSQL (可选)

```yaml
version: "3.8"
services:
  postgres:
    image: postgres:16
    container_name: danmu-postgres
    restart: unless-stopped
    environment:
      # !!! 重要：请务必替换为您的强密码 !!!
      POSTGRES_PASSWORD: "your_strong_postgres_password"               #数据库密码
      POSTGRES_USER: "danmuapi"                                        #数据库用户名
      POSTGRES_DB: "danmuapi"                                          #数据库名称
      TZ: "Asia/Shanghai"
    volumes:
      - ./db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U danmuapi -d danmuapi"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 30s
    networks:
      - misaka-net

  danmu-app:
    image: l429609201/misaka_danmu_server:latest
    container_name: misaka-danmu-server
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      # 设置运行容器的用户和组ID，以匹配您宿主机的用户，避免挂载卷的权限问题。
      - PUID=1000
      - PGID=1000
      - UMASK=0022
      - TZ=Asia/Shanghai
      # --- 数据库连接配置 ---
      - DANMUAPI_DATABASE__TYPE=postgresql                              # 数据库类型
      - DANMUAPI_DATABASE__HOST=postgres                                # 使用服务名
      - DANMUAPI_DATABASE__PORT=5432                                    # 数据库端口
      - DANMUAPI_DATABASE__NAME=danmuapi                                # 数据库名称
      # !!! 重要：请使用上面postgres容器相同的用户名和密码 !!!
      - DANMUAPI_DATABASE__USER=danmuapi                                # 数据库用户名    
      - DANMUAPI_DATABASE__PASSWORD=your_strong_postgres_password       # 数据库密码
      # --- 初始管理员配置 ---
      - DANMUAPI_ADMIN__INITIAL_USER=admin
    volumes:
      - ./config:/app/config
    ports:
      - "7768:7768"

    networks:
      - misaka-net

networks:
  misaka-net:
    driver: bridge
```

## 步骤 2: 修改配置并启动

1.  **重要**: 打开您刚刚创建的 `docker-compose.yaml` 文件，将所有 `your_strong_..._password` 替换为您自己的安全密码。
    -   对于MySQL，您需要修改 `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` (两处) 和 `healthcheck` 中的密码。
    -   对于PostgreSQL，您需要修改 `POSTGRES_PASSWORD` 和 `DANMUAPI_DATABASE__PASSWORD`。
2.  在 `docker-compose.yaml` 所在目录运行命令启动应用：
    ```bash
    docker-compose up -d
    ```

## 步骤 3: 访问和配置

- **访问Web UI**: 打开浏览器，访问 `http://<您的服务器IP>:7768`。
- **初始登录**:
  - 用户名: `admin` (或您在环境变量中设置的值)。
  - 密码: 首次启动时会在容器的日志中生成一个随机密码。请使用 `docker logs misaka-danmu-server` 查看。
- **开始使用**: 登录后，请先在 "设置" -> "账户安全" 中修改您的密码，然后配置以下内容:
  - **元数据源**: 在 "设置" -> "搜索源" 中配置 TMDB, TVDB 等 API 密钥 (参考 [元数据源配置指南](metadata-sources.md))
  - **AI 功能** (可选): 在 "设置" -> "AI 自动匹配" 中配置 AI 提供商和 API Key (参考 [AI 功能配置指南](ai-configuration.md))
  - **弹幕源**: 在 "弹幕源" 页面加载或上传弹幕源离线包

## 步骤 4: 环境变量说明

### 数据库配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `DANMUAPI_DATABASE__TYPE` | 数据库类型 (`mysql` 或 `postgresql`) | - |
| `DANMUAPI_DATABASE__HOST` | 数据库主机地址 | - |
| `DANMUAPI_DATABASE__PORT` | 数据库端口 | `3306` (MySQL) / `5432` (PostgreSQL) |
| `DANMUAPI_DATABASE__NAME` | 数据库名称 | - |
| `DANMUAPI_DATABASE__USER` | 数据库用户名 | - |
| `DANMUAPI_DATABASE__PASSWORD` | 数据库密码 | - |

### 管理员配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `DANMUAPI_ADMIN__INITIAL_USER` | 初始管理员用户名 | `admin` |

### 弹幕存储路径配置

> **注意**: 弹幕存储路径配置只能通过 Web UI 进行设置,不支持环境变量配置。

**配置方式**:
1. 登录 Web UI
2. 进入 "设置" → "弹幕文件路径"
3. 启用 "自定义弹幕文件保存路径"
4. 配置电影和电视节目的存储路径和文件命名模板

**文件命名模板支持的变量**:
- `${title}` - 作品标题
- `${season}` - 季度编号
- `${episode}` - 集数编号
- `${year}` - 年份
- `${provider}` - 弹幕源提供商
- `${animeId}` - 作品 ID
- `${episodeId}` - 分集 ID
- `${sourceId}` - 源 ID

**默认配置**:
- 电影弹幕路径: `/app/config/danmaku/movies`
- 电影文件命名: `${title}/${episodeId}.xml`
- 电视节目弹幕路径: `/app/config/danmaku/tv`
- 电视节目文件命名: `${animeId}/${episodeId}.xml`

### 其他配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `PUID` | 运行容器的用户 ID | `1000` |
| `PGID` | 运行容器的组 ID | `1000` |
| `UMASK` | 文件权限掩码 | `0022` |
| `TZ` | 时区 | `Asia/Shanghai` |


---

## 📚 下一步

- **[📱 客户端配置](client-configuration.md)** - 配置播放器弹幕接口
- **[🎬 元数据源配置](metadata-sources.md)** - 配置 TMDB, TVDB 等 API 密钥
- **[🤖 AI 功能配置](ai-configuration.md)** - 配置 AI 智能匹配功能
- **[🔗 Webhook 配置](webhook-configuration.md)** - 配置 Emby/Jellyfin/Plex 自动化
- **[🔧 弹幕源管理](scraper-management.md)** - 加载和管理弹幕源
