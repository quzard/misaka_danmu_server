# 客户端配置

## 1. 获取弹幕 Token

- 在 Web UI 的 "弹幕Token" 页面，点击 "添加Token" 来创建一个新的访问令牌。
- 创建后，您会得到一串随机字符，这就是您的弹幕 Token。
- 可通过配置自定义域名之后直接点击复制，会帮你拼接好相关的链接

## 2. 配置弹幕接口

在您的播放器（如 Yamby, Hills, 小幻影视, SenPlayer 等）的自定义弹幕接口设置中，填入以下格式的地址：

`http://<服务器IP>:<端口>/api/v1/<你的Token>`

- `<服务器IP>`: 部署本服务的主机 IP 地址。
- `<端口>`: 部署本服务时设置的端口（默认为 `7768`）。
- `<你的Token>`: 您在上一步中创建的 Token 字符串。

**示例:**

假设您的服务部署在 `192.168.1.100`，端口为 `7768`，创建的 Token 是 `Q2KHYcveM0SaRKvxomQm`。

- **对于 Yamby （版本要大于1.5.9.11） / Hills （版本要大于1.4.2）:**

  在自定义弹幕接口中填写：
  `http://192.168.1.100:7768/api/v1/Q2KHYcveM0SaRKvxomQm`
  
- **对于 小幻影视:**
  小幻影视您可以添加含有 `/api/v2` 的路径，可以直接填写复制得到的url：
  `http://192.168.1.100:7768/api/v1/Q2KHYcveM0SaRKvxomQm/api/v2   #可加可不加/api/v2 `

- **对于 SenPlayer（版本要大于5.7）:**
  SenPlayer 是一款支持 ISO 播放的智能视频播放器，在弹幕设置中填写：
  `http://192.168.1.100:7768/api/v1/Q2KHYcveM0SaRKvxomQm`

> **兼容性说明**: 本服务已对路由进行特殊处理，无论您使用 `.../api/v1/<Token>` 还是 `.../api/v1/<Token>/api/v2` 格式，服务都能正确响应，以最大程度兼容不同客户端。

## 3. 项目参考

本项目参考了 [dandanplayapi](https://api.dandanplay.net/swagger/index.html)，同时增加了使用访问令牌管理弹幕API，支持上述多种播放器客户端。
