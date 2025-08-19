# --- 阶段 1: 构建前端 ---
# 使用 Node.js 20 Alpine 镜像作为前端构建环境
FROM node:20-alpine AS frontend-builder

# 设置前端工作目录
WORKDIR /app/web

# 复制前端依赖定义文件并安装依赖
COPY web/package.json web/yarn.lock ./
RUN yarn install --frozen-lockfile

# 复制所有前端代码并执行构建
COPY web/ ./
RUN yarn build

# --- 阶段 2: 构建最终的 Python 应用镜像 ---
FROM l429609201/su-exec:su-exec

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV TZ=Asia/Shanghai
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8

# 设置工作目录
WORKDIR /app

# 安装系统依赖并创建用户
RUN set -ex \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        default-libmysqlclient-dev \
        libpq-dev \
        tzdata \
        iputils-ping \
    && addgroup --gid 1000 appgroup \
    && adduser --shell /bin/sh --disabled-password --uid 1000 --gid 1000 appuser \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 复制 Python 依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端应用代码
COPY src/ ./src/
COPY static/ ./static/
COPY config/ ./config/
COPY exec.sh /exec.sh
COPY run.sh /run.sh
RUN chmod +x /exec.sh /run.sh

# 从前端构建阶段复制构建好的静态文件到最终镜像
COPY --from=frontend-builder /app/web/dist ./web/dist

# 更改工作目录所有权为新创建的用户
RUN chown -R appuser:appgroup /app

# 暴露应用运行的端口
EXPOSE 7768

# 运行应用的默认命令
CMD ["/exec.sh"]
