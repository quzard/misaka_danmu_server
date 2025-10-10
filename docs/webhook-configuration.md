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

#### 方式一：Plex 原生 Webhooks（需要 Plex Pass，有局限性）

1. 登录您的 Plex 服务器管理后台。
2. 导航到 **设置** -> **Webhooks**。
3. 点击 **添加 Webhook**。
4. 在 **URL** 字段中，填入您的 Plex Webhook URL，例如：
   ```
   http://192.168.1.100:7768/api/webhook/plex?api_key=your_webhook_api_key_here
   ```
5. 保存设置。

![Plex 原生 Webhooks 配置](https://camo.githubusercontent.com/7e859e2957bebc2048916d29746aca752a9c35519f819c86a34957c7b7884018/68747470733a2f2f702e736461312e6465762f31362f65363837323965316434353462646432336137633966653736636137313235312f312e6a7067)

> **⚠️ 重要限制**:
> - **需要 Plex Pass 订阅**
> - **无法处理批量入库**：当您一次性添加多集剧集时（如第1-7集），Plex 原生 webhook 只会发送一个剧集级别的通知，无法获取具体的集数信息
> - **事件过多**：Plex 会在所有事件（播放、暂停、新媒体入库等）时发送 webhook，增加服务器负担
> - 本服务只会处理 `library.new` 事件（新媒体入库），其他事件会被忽略

#### 方式二：通过 Tautulli（强烈推荐）

**为什么推荐 Tautulli？**
- ✅ **解决批量入库问题**：完美处理连续剧集入库（如一次性添加第1-7集）
- ✅ **无需 Plex Pass**：免费使用，无订阅要求
- ✅ **精确事件控制**：只在真正需要时触发，减少无用请求
- ✅ **丰富的过滤条件**：可按用户、媒体库、媒体类型等过滤
- ✅ **完整的元数据**：提供更详细的媒体信息

**详细配置步骤：**

1. **安装 Tautulli**
   - 访问 [Tautulli 官网](https://tautulli.com/) 下载并安装
   - 配置 Tautulli 连接到您的 Plex 服务器

2. **创建 Webhook 通知**
   - 登录 Tautulli 管理后台
   - 导航到 **Settings** -> **Notification Agents**
   - 点击 **Add a new notification agent**，选择 **Webhook**

   ![Tautulli 通知代理设置](https://camo.githubusercontent.com/c91d11ad195d1bc300de1dffd80ab57fa274599ec9ebaa789c5a21c0cb2f785c/68747470733a2f2f702e736461312e6465762f31362f63303165396465353638393234393863303136336130666662376431313266652f312e6a7067)

   > 💡 **提示**: 如果您是第一次使用 Tautulli，建议先熟悉其基本功能，确保它能正常监控您的 Plex 服务器活动。

3. **Configuration 标签页配置**
   - **Webhook URL**: 填入您的 Plex Webhook URL：
     ```
     http://192.168.1.100:7768/api/webhook/plex?api_key=your_webhook_api_key_here
     ```
   - **Webhook Method**: 选择 `POST`
   - **Description**: 填入描述，如 "弹幕服务器通知"


   ![Tautulli Configuration 配置](https://github.com/user-attachments/assets/05f64783-6ad5-474f-9c06-14ddc96a56ca)

4. **Triggers 标签页配置**
   - 勾选 **Recently Added**（新媒体入库事件）
   - 其他事件保持不勾选

   ![Tautulli Triggers 标签页配置](https://github.com/user-attachments/assets/0a081782-451a-4b4f-bc63-2aeb136e5e1b)
   
6. **Conditions 标签页配置（可选但推荐）**
   - 添加条件以减少不必要的通知：
     - **Condition 1**: `Library Name` `is` `您的动漫库名称`（限制特定媒体库）
     - **Condition 2**: `Media Type` `is` `episode`（限制剧集类型）
     - **Condition Logic**: `{1} and {2}`（两个条件同时满足）

   ![Tautulli Conditions 标签页配置（可选但推荐）](https://github.com/user-attachments/assets/10d22dec-0554-41fb-bb45-41d04987915e)
   
7. **Data 标签页配置**
   - 展开 **Recently Added** 部分
   - 在 **JSON Data** 字段中填入以下模板：
     ```json
     {
       "media_type": "{media_type}",
       "title": "{title}",
       "show_name": "{show_name}",
       "season": "{season_num}",
       "episode": "{episode_num}",
       "release_date": "{air_date}",
       "user_name": "{username}",
       "action": "created"
     }
     ```

   ![Tautulli Data 配置](https://github.com/user-attachments/assets/2dd093d2-a718-4eac-b328-0ce25b226724)

   > ⚠️ **重要**: 请确保 JSON 格式正确，任何语法错误都会导致 webhook 失败。建议复制粘贴上述模板以避免输入错误。

8. **保存并测试**
   - 点击 **Save** 保存配置
   - 可以使用 **Test** 功能验证配置是否正确

   > 💡 **测试建议**:
   > - 先使用 Tautulli 的测试功能确保 webhook 能正常发送
   > - 然后在 Plex 中添加一个测试媒体文件，观察是否触发弹幕搜索任务
   > - 检查弹幕服务器的日志以确认 webhook 被正确接收和处理

**字段说明：**
- `{media_type}`: 媒体类型（movie, episode, season 等）
- `{title}`: 通用标题（电影完整名称，剧集包含集数信息）
- `{show_name}`: 电视剧名称（仅剧集有效，提供纯净剧名）
- `{season_num}`: 季数（支持范围格式如 "1-3"）
- `{episode_num}`: 集数（支持范围格式如 "1-7" 或混合格式如 "1-3,6,8,10-13"）
- `{air_date}`: 首播日期
- `{username}`: 触发用户名

**批量入库处理示例：**
当您一次性添加《某动漫》第1-7集时：
- Plex 原生 webhook：只发送1个剧集级别通知，无法获取具体集数
- Tautulli webhook：发送包含 `"episode": "1-7"` 的通知，本服务会自动解析为7个独立任务


