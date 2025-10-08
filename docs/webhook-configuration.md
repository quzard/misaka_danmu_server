# Webhook 配置

本服务支持通过 Webhook 接收来自 Emby、Jellyfin、Plex 等媒体服务器的通知，实现新媒体入库后的弹幕自动搜索和导入。

## 1. 获取 Webhook URL

1. 在 Web UI 的 "设置" -> "Webhook" 页面，您会看到一个为您生成的唯一的 **API Key**。
2. 根据您要集成的服务，复制对应的 Webhook URL。URL 的通用格式为：
   `http://<服务器IP>:<端口>/api/webhook/{服务名}?api_key=<你的API_Key>`

   - `<服务器IP>`: 部署本服务的主机 IP 地址。
   - `<端口>`: 部署本服务时设置的端口（默认为 `7768`）。
   - `{服务名}`: webhook界面中下方已加载的服务名称，例如 `emby`、`jellyfin`、`plex`。
   - `<你的API_Key>`: 您在 Webhook 设置页面获取的密钥。
3. 现在已经增加拼接URL后的复制按钮

## 2. 配置媒体服务器

### 对于 Emby

1. 登录您的 Emby 服务器管理后台。
2. 导航到 **通知** (Notifications)。
3. 点击 **添加通知** (Add Notification)，选择 **Webhook** 类型。
4. 在 **Webhook URL** 字段中，填入您的 Emby Webhook URL，例如：
   ```
   http://192.168.1.100:7768/api/webhook/emby?api_key=your_webhook_api_key_here
   ```
5. **关键步骤**: 在 **事件** (Events) 部分，请务必**只勾选**以下事件：
   - **项目已添加 (Item Added)**: 这是新媒体入库的事件，其对应的事件名为 `新媒体添加`。
6. 确保 **发送内容类型** (Content type) 设置为 `application/json`。
7. 保存设置。

### 对于 Jellyfin

1. 登录您的 Jellyfin 服务器管理后台。
2. 导航到 **我的插件**，找到 **Webhook** 插件，如果没有找到，请先安装插件，并重启服务器。
3. 点击 **Webhook** 插件，进入配置页面。
4. 在 **Server Url** 中输入jellyfin 访问地址（可选）。
5. 点击 **Add Generic Destination**。
6. 输入 **Webhook Name**
7. 在 **Webhook URL** 字段中，填入您的 Jellyfin Webhook URL，例如：
   ```
   http://192.168.1.100:7768/api/webhook/jellyfin?api_key=your_webhook_api_key_here
   ```
8. **关键步骤**: 在 **Notification Type** 部分，请务必**只勾选**以下事件：
   - **Item Added**: 这是新媒体入库的事件，其对应的事件名为 `新媒体添加`。
9. **关键步骤**: 一定要勾选 **Send All Properties (ignores template)** 选项。
10. 保存设置。

### 对于 Plex

1. 登录您的 Plex 服务器管理后台。
2. 导航到 **设置** -> **Webhooks**。
3. 点击 **添加 Webhook**。
4. 在 **URL** 字段中，填入您的 Plex Webhook URL，例如：
   ```
   http://192.168.1.100:7768/api/webhook/plex?api_key=your_webhook_api_key_here
   ```
5. 保存设置。

> **注意**: Plex 会在所有事件（播放、暂停、新媒体入库等）时发送 webhook，但本服务只会处理 `library.new` 事件（新媒体入库）。

现在，当有新的电影或剧集添加到您的媒体库时，本服务将自动收到通知，并创建一个后台任务来为其搜索和导入弹幕。
