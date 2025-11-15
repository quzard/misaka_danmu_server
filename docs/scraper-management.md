# 🔧 弹幕源管理

本服务支持灵活的弹幕源管理方式,您可以通过资源仓库加载或上传离线包来安装弹幕源。

## 1. 从资源仓库加载

### 配置资源仓库

1. 在 Web UI 的 "搜索源" 页面,找到 "资源仓库" 卡片
2. 在输入框中填入 GitHub 仓库链接或 CDN 加速链接

   **官方仓库:**
   ```
   https://github.com/l429609201/Misaka-Scraper-Resources
   ```

   **CDN 加速链接 (推荐,国内访问更快):**
   ```
   https://cdn.jsdelivr.net/gh/l429609201/Misaka-Scraper-Resources
   ```
   ```
   https://hk.gh-proxy.org/https://github.com/l429609201/Misaka-Scraper-Resources
   ```
   ```
   https://gh-proxy.org/https://github.com/l429609201/Misaka-Scraper-Resources
   ```
   ```
   https://proxy.pipers.cn/https://github.com/l429609201/Misaka-Scraper-Resources
   ```
   ```
   https://cdn.gh-proxy.org/https://github.com/l429609201/Misaka-Scraper-Resources
   ```
   ```
   https://edgeone.gh-proxy.org/https://github.com/l429609201/Misaka-Scraper-Resources
   ```
   ```
   https://ghproxy.com/https://github.com/l429609201/Misaka-Scraper-Resources
   ```
   ```
   https://dl.122896.xyz/https://github.com/l429609201/Misaka-Scraper-Resources
   ```

3. 点击 "保存" 按钮保存配置

### 加载弹幕源

1. 配置好资源仓库后,点击 "加载资源" 按钮
2. 系统会自动:
   - 备份当前弹幕源
   - 从仓库下载最新的弹幕源文件
   - 安装到系统中
   - 重载弹幕源

### 版本信息

- **本地版本**: 显示当前安装的弹幕源版本
- **远程版本**: 显示资源仓库中的最新版本
- 如果远程版本更新,会显示 "有更新" 提示

## 2. 上传离线包

### 准备离线包

离线包应该是一个 `.zip` 或 `.tar.gz` 压缩文件,包含以下内容:

- **弹幕源文件**: `.so` (Linux/macOS) 或 `.pyd` (Windows) 文件
- **versions.json**: 必需,包含版本信息和平台架构
- **package.json**: 可选,包含资源包版本号

### versions.json 格式示例

```json
{
  "version": "1.0.0",
  "platform": "linux",
  "type": "x86",
  "scrapers": {
    "bilibili": "1.0.0",
    "iqiyi": "1.0.0"
  }
}
```

### 上传步骤

1. 在 "搜索源" 页面的 "资源仓库" 卡片中
2. 点击 "离线包上传" 按钮
3. 选择准备好的压缩包文件
4. 系统会自动:
   - 验证文件格式和平台架构
   - 备份当前弹幕源
   - 解压并安装新的弹幕源
   - 在后台重载弹幕源

### 平台和架构验证

系统会自动验证离线包的平台和架构是否匹配当前系统:

- **平台**: `linux`, `macos`, `windows`
- **架构**: `x86` (x86_64/amd64), `arm` (aarch64/arm64)

如果不匹配,上传会失败并提示错误信息。

## 3. 备份和恢复

### 自动备份

- 在加载资源或上传离线包时,系统会自动备份当前弹幕源
- 备份包含所有 `.so`/`.pyd` 文件、`package.json` 和 `versions.json`

### 手动备份

1. 在 "搜索源" 页面,找到 "备份管理" 区域
2. 点击 "备份当前弹幕源" 按钮
3. 系统会将当前弹幕源备份到持久化目录

### 查看备份信息

备份信息包括:
- 备份时间
- 备份用户
- 文件数量
- 平台信息
- 各弹幕源的版本号

### 恢复备份

1. 点击 "从备份还原" 按钮
2. 系统会:
   - 从备份目录恢复所有文件
   - 恢复 `package.json` 和 `versions.json`
   - 重载弹幕源

## 4. 重载弹幕源

在以下情况下,您可能需要手动重载弹幕源:

- 修改了弹幕源文件
- 更新了配置
- 系统提示需要重载

点击 "重载弹幕源" 按钮即可。

## 5. 注意事项

- **平台兼容性**: 确保离线包的平台和架构与您的系统匹配
- **备份重要性**: 在更新弹幕源前,系统会自动备份,但建议定期手动备份
- **版本管理**: 建议使用资源仓库方式,可以方便地查看和更新版本
- **网络要求**: 从资源仓库加载需要能够访问 GitHub,国内用户建议使用 CDN 加速链接
- **CDN 选择**: 如果某个 CDN 访问较慢,可以尝试切换到其他 CDN 链接

## 6. 故障排除

### 上传失败

- 检查文件格式是否为 `.zip` 或 `.tar.gz`
- 确认压缩包中包含 `versions.json`
- 验证平台和架构是否匹配

### 加载资源失败

- 检查资源仓库链接是否正确
- 确认网络可以访问 GitHub,国内用户建议使用 CDN 加速链接
- 如果使用 CDN 链接仍然失败,尝试切换到其他 CDN 节点
- 查看系统日志获取详细错误信息

### 重载失败

- 检查弹幕源文件是否完整
- 确认文件权限正确
- 尝试从备份恢复后再重载

