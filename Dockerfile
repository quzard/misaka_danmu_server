# --- Stage 1: Extract SO files ---
# 定义构建参数，用于确定.so文件来源镜像的标签
ARG SO_TAG=latest
FROM l429609201/so:${SO_TAG} AS so-extractor

# --- Stage 2: Build Frontend ---
FROM node:20-alpine AS builder

WORKDIR /app/web

# 仅复制 package.json 和 package-lock.json 以利用Docker缓存
COPY web/package.json web/package-lock.json ./
RUN npm ci

# 复制前端源代码
COPY web/ ./

# 执行构建
RUN npm run build

# --- Stage 3: Python Dependency Builder ---
FROM l429609201/su-exec:su-exec AS python-builder

# 安装编译Python包所需的构建时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libpq-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# 创建一个目录用于存放安装的包
WORKDIR /install
COPY requirements.txt .
# 将所有包安装到当前目录 (/install)
RUN pip install --no-cache-dir -r requirements.txt --target .

# --- Stage 4: Final Python Application ---
FROM l429609201/su-exec:su-exec

# 设置环境变量，防止生成 .pyc 文件并启用无缓冲输出
# 设置时区为亚洲/上海，以确保日志等时间正确显示
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 构建时参数：控制是否默认禁用限速，以及是否移除 .so 实现。
ARG DISABLE_RATE_LIMITER=true
ARG STRIP_RATE_LIMIT_SO=false

# 运行时环境变量：可在运行容器时覆盖（-e DISABLE_RATE_LIMITER=false）。
ENV DISABLE_RATE_LIMITER=${DISABLE_RATE_LIMITER}

# 设置工作目录
WORKDIR /app

# 仅安装运行时的系统依赖，不再需要 build-essential, python3-dev 等
RUN set -ex \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        tzdata \
        iputils-ping \
        libmariadb3 \
        libpq5 \
    && addgroup --gid 1000 appgroup \
    && adduser --shell /bin/sh --disabled-password --uid 1000 --gid 1000 appuser \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 从 python-builder 阶段将安装好的包复制到系统 site-packages 目录
# 注意：路径中的 python3.11 需要与基础镜像的Python版本匹配
COPY --from=python-builder /install /usr/local/lib/python3.11/site-packages

# 从 so-extractor 阶段复制.so文件到对应的src目录结构
COPY --from=so-extractor /app/src/ ./src/

# 可选：根据构建参数删除 so 实现，确保仅使用 Python 版本（配合 src/main.py 的开关）。
RUN if [ "$STRIP_RATE_LIMIT_SO" = "true" ]; then rm -f ./src/rate_limiter*.so; fi

# 复制应用代码
COPY src/ ./src/
COPY static/ ./static/
COPY config/ ./config/
COPY exec.sh /exec.sh
COPY run.sh /run.sh
RUN chmod +x /exec.sh /run.sh

# 从 'builder' 阶段复制构建好的前端静态文件
COPY --from=builder /app/web/dist ./web/dist/

# 更改工作目录所有权为新创建的用户
RUN chown -R appuser:appgroup /app

# 暴露应用运行的端口
EXPOSE 7768

# 运行应用的默认命令
CMD ["/exec.sh"]
