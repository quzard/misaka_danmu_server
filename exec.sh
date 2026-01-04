#!/bin/sh
set -e

# 如果环境变量未设置，则使用默认值
PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-0022}

# 设置 umask
echo "正在设置 umask 为 ${UMASK}..."
umask ${UMASK}

# 更新挂载目录的所有权，以确保容器内运行用户有权写入
# - /app/config: 配置与数据卷
# - /app/src/scrapers: 弹幕源 .so/.pyd 文件目录
#   （需要在运行时支持上传离线包、从 GitHub 更新资源等写操作）
echo "正在更新 /app/config 和 /app/src/scrapers 目录的所有权为 ${PUID}:${PGID}..."
chown -R ${PUID}:${PGID} /app/config /app/src/scrapers

# 如果 docker.sock 存在，自动将运行用户加入 docker 组以获得访问权限
# 这样用户无需在 docker-compose.yml 中手动配置 group_add
if [ -S /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
    echo "检测到 Docker 套接字，GID: ${DOCKER_GID}"

    # 检查是否已存在该 GID 的组，如果不存在则创建
    if ! getent group ${DOCKER_GID} > /dev/null 2>&1; then
        echo "创建 docker_host 组 (GID: ${DOCKER_GID})..."
        groupadd -g ${DOCKER_GID} docker_host 2>/dev/null || true
    fi

    # 获取组名（可能是 docker 或 docker_host 或其他）
    DOCKER_GROUP=$(getent group ${DOCKER_GID} | cut -d: -f1)
    if [ -n "${DOCKER_GROUP}" ]; then
        # 使用 usermod 将 appuser 加入 docker 组（Debian 系统）
        if usermod -aG ${DOCKER_GROUP} appuser 2>/dev/null; then
            echo "已将 appuser 加入 ${DOCKER_GROUP} 组"
        fi
    fi
fi

# 使用 su-exec 工具切换到指定的 UID/GID，并执行 /run.sh 脚本
echo "正在以 appuser 用户身份执行 /run.sh..."
exec su-exec ${PUID}:${PGID} /run.sh