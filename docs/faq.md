# 常见问题

## 忘记密码怎么办？

如果您忘记了管理员密码，可以通过以下步骤在服务器上重置：

1.  通过 SSH 或其他方式登录到您的服务器。

2.  进入您存放 `docker-compose.yml` 的目录。

3.  执行以下命令来重置指定用户的密码。请将 `<username>` 替换为您要重置密码的用户名（例如 `admin`）。

    ```bash
     docker-compose exec danmu-api python -m src.reset_password <username>
    ```

    > **注意**: 如果您没有使用 `docker-compose`，或者您的容器名称不是 `danmu-api`，请使用 `docker exec` 命令：
    > `docker exec <您的容器名称> python -m src.reset_password <username>`

4.  命令执行后，终端会输出一个新的随机密码。请立即使用此密码登录，并在 "设置" -> "账户安全" 页面中修改为您自己的密码。

## 数据库文件越来越大怎么办？

随着时间的推移，数据库占用的磁盘空间可能会逐渐增大。这通常由两个原因造成：

1.  **应用日志**: 任务历史、API访问记录等会存储在数据库中。这些日志会由内置的 **"数据库维护"** 定时任务自动清理（默认保留最近3天）。
2.  **MySQL二进制日志 (Binlog)**: 这是MySQL用于数据恢复和主从复制的日志，如果不进行管理，它会持续增长。

本项目内置的"数据库维护"任务会**尝试自动清理**旧的Binlog文件。但由于权限问题，您可能会在日志中看到"Binlog 清理失败"的警告。这是一个正常且可安全忽略的现象。

如果您关心磁盘空间占用，并希望启用Binlog的自动清理功能，请参阅详细的解决方案：

- **[缓存日志清理任务说明](./缓存日志清理任务说明.md)**

> **对于PostgreSQL用户**: PostgreSQL没有Binlog机制，其WAL日志通常会自动管理，因此空间占用问题没有MySQL那么突出。您只需关注应用日志的自动清理即可。

## 国外VPS搭建弹幕库搜索不到内容怎么办？

如果您在国外VPS上部署本项目，可能会遇到搜索不到弹幕或搜索结果很少的问题。这主要是由于原因：**IP地区限制**

部分弹幕源（如B站、爱奇艺、腾讯视频等）的搜索接口存在IP地区限制，出于版权保护考虑，这些接口可能只对大陆IP开放完整的搜索结果。

### 解决方案：VPS回家

为了获得完整的搜索体验，建议使用"VPS回家"的方案，即让您的国外VPS通过国内网络进行弹幕搜索。

**推荐方案**：
- 使用国内中转服务器或代理
- 配置网络路由，让弹幕搜索请求通过国内IP发出
- 使用VPN或隧道技术将流量回传到国内

**详细教程**：
群友 [@wdnmlgbd](https://blog.tencentx.de/) 提供了完整的解决方案：
- **教程链接**: [国外VPS搭建的MisakaDump正常获取bilibili弹幕](https://blog.tencentx.de/p/build-%E5%9B%BD%E5%A4%96vps%E6%90%AD%E5%BB%BA%E7%9A%84misakadump%E6%AD%A3%E5%B8%B8%E8%8E%B7%E5%8F%96bilibili%E5%BC%B9%E5%B9%95/)

## 如何配置 TMDB/TVDB API Key?

TMDB 和 TVDB 是重要的元数据源,用于获取影视作品的详细信息。

### 快速配置

1. **获取 TMDB API Key**:
   - 访问 [TMDB 官网](https://www.themoviedb.org/) 注册账号
   - 进入 Settings → API → Request an API Key
   - 选择 "Developer" 类型并填写申请表单
   - 复制 "API Key (v3 auth)"

2. **获取 TVDB API Key**:
   - 访问 [TVDB 官网](https://thetvdb.com/) 注册账号
   - 进入 Dashboard → API Keys → Create API Key
   - 复制生成的 API Key

3. **在系统中配置**:
   - 登录 Web UI → "设置" → "搜索源"
   - 填写对应的 API Key
   - 保存配置

**详细教程**: 请参考 [元数据源配置指南](metadata-sources.md)

## AI 功能无法使用怎么办?

如果您遇到 AI 功能无法使用的问题,请按以下步骤排查:

### 1. 检查 AI 配置

- 登录 Web UI → "设置" → "AI 自动匹配"
- 确认已选择 AI 提供商
- 确认已填写正确的 API Key
- 点击 "测试 AI 连接" 验证配置

### 2. 检查网络连接

- **国外 AI 服务** (OpenAI, Gemini): 需要确保网络能访问对应服务
  - 如果在国内,可能需要配置代理
  - 在 "设置" → "网络" 中配置全局代理
- **国内 AI 服务** (DeepSeek, SiliconFlow): 通常无需代理

### 3. 检查 API Key 是否有效

- 访问对应 AI 提供商的官网
- 检查 API Key 是否过期
- 检查账户余额是否充足(DeepSeek, SiliconFlow 支持余额查询)

### 4. 查看系统日志

- 在 Web UI 中查看 "任务" 页面的日志
- 或使用 `docker logs misaka-danmu-server` 查看容器日志
- 查找 AI 相关的错误信息

### 5. 常见错误

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| `API key is invalid` | API Key 错误 | 检查 API Key 是否正确,没有多余空格 |
| `Connection timeout` | 网络无法访问 | 配置代理或更换 AI 提供商 |
| `Insufficient balance` | 余额不足 | 充值账户余额 |
| `Model not found` | 模型名称错误 | 检查模型名称是否正确 |

**详细教程**: 请参考 [AI 功能配置指南](ai-configuration.md)

## 如何自定义弹幕文件存储路径?

默认情况下,弹幕文件存储在 `/app/config/danmaku` 目录下。如果您想自定义存储路径:

### 方式 1: Web UI 配置 (推荐)

1. 登录 Web UI → "设置" → "弹幕文件路径"
2. 启用 "自定义弹幕文件保存路径"
3. 配置电影和电视节目的存储路径
4. 配置文件命名模板(支持变量: `${title}`, `${season}`, `${episode}` 等)
5. 保存配置

### 方式 2: Docker 挂载

如果您想将弹幕文件存储到宿主机的其他位置:

```yaml
volumes:
  - ./config:/app/config
  - /path/to/your/danmaku:/app/config/danmaku  # 挂载自定义路径
```

然后在 Web UI 中配置路径为 `/app/config/danmaku/...`

**注意**: 确保挂载的目录有正确的读写权限(PUID/PGID 配置)。
