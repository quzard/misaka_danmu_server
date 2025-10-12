# 🚀 MySQL 内存优化配置

如果您的服务器内存有限（如 1GB 以下的 VPS），或者希望减少 MySQL 的内存占用，可以使用以下优化配置。

## 📊 优化效果

- **默认配置**：MySQL 8.x 通常占用 200-400MB 内存
- **优化后**：内存占用降低到约 100-150MB
- **适用场景**：个人服务器、小型 VPS、开发测试环境

## 🔧 使用方法

### 步骤 1: 创建优化配置文件

在您的项目目录中创建 MySQL 配置文件：

```bash
# 确保 config 目录存在
mkdir -p config

# 创建优化的 MySQL 配置文件
cat > config/mysql.cnf << 'EOF'
[mysqld]
# === 基础配置 ===
user = mysql
port = 3306
bind-address = 0.0.0.0
skip-name-resolve = 1
default-authentication-plugin = mysql_native_password

# === 字符集配置 ===
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
init_connect = 'SET NAMES utf8mb4'

# === 内存优化配置 ===
# InnoDB 缓冲池大小 - 设置为较小值以节省内存
innodb_buffer_pool_size = 64M
# 减少 InnoDB 日志缓冲区大小
innodb_log_buffer_size = 8M
# 减少表缓存大小
table_open_cache = 64
# 减少线程缓存大小
thread_cache_size = 8
# 减少临时表大小
tmp_table_size = 16M
max_heap_table_size = 16M
# 减少排序缓冲区大小
sort_buffer_size = 256K
# 减少连接缓冲区大小
read_buffer_size = 128K
read_rnd_buffer_size = 256K
# 减少批量插入缓冲区大小
bulk_insert_buffer_size = 8M

# === 连接配置 ===
max_connections = 50
max_connect_errors = 10
connect_timeout = 10
wait_timeout = 600
interactive_timeout = 600

# === InnoDB 优化 ===
# 减少 InnoDB 日志文件大小
innodb_log_file_size = 32M
# 减少 InnoDB 日志文件数量
innodb_log_files_in_group = 2
# 优化 InnoDB 刷新方法
innodb_flush_method = O_DIRECT
# 减少 InnoDB 线程并发数
innodb_thread_concurrency = 2
# 减少 InnoDB 读写 IO 线程
innodb_read_io_threads = 2
innodb_write_io_threads = 2

# === 日志配置 ===
# 禁用一般查询日志以节省空间和性能
general_log = 0
# 启用慢查询日志但设置较高阈值
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 5
# 二进制日志配置
log-bin = mysql-bin
binlog_expire_logs_seconds = 259200
max_binlog_size = 100M

# === 安全配置 ===
# 禁用符号链接
symbolic-links = 0
# 设置 SQL 模式
sql_mode = STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO

# === 性能优化 ===
# 禁用性能模式以节省内存
performance_schema = OFF
# 减少信息模式统计信息缓存
information_schema_stats_expiry = 86400

[mysql]
default-character-set = utf8mb4

[client]
default-character-set = utf8mb4
port = 3306
EOF
```

### 步骤 2: 修改 docker-compose.yaml

将您的 MySQL 服务配置修改为使用配置文件：

```yaml
  mysql:
    image: mysql:8.1.0-oracle
    container_name: danmu-mysql
    restart: unless-stopped
    environment:
      # !!! 重要：请务必替换为您的强密码 !!!
      MYSQL_ROOT_PASSWORD: "your_strong_root_password"
      MYSQL_DATABASE: "danmuapi"
      MYSQL_USER: "danmuapi"
      MYSQL_PASSWORD: "your_strong_user_password"
      TZ: "Asia/Shanghai"
    volumes:
      - ./db-data:/var/lib/mysql
      - ./config/mysql.cnf:/etc/mysql/conf.d/custom.cnf:ro  # 挂载优化配置文件
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -u$${MYSQL_USER} -p$${MYSQL_PASSWORD}"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 30s
    networks:
      - misaka-net
```

### 步骤 3: 重启服务

```bash
# 停止现有服务
docker-compose down

# 重新启动服务
docker-compose up -d
```

## 📝 配置说明

### 主要优化项

| 配置项 | 默认值 | 优化值 | 说明 |
|--------|--------|--------|------|
| `innodb_buffer_pool_size` | 128M+ | 64M | InnoDB 缓冲池大小 |
| `innodb_log_buffer_size` | 16M | 8M | 日志缓冲区大小 |
| `max_connections` | 151 | 50 | 最大连接数 |
| `tmp_table_size` | 16M | 16M | 临时表大小 |
| `performance_schema` | ON | OFF | 性能监控（关闭节省内存） |

### 注意事项

⚠️ **使用前请注意：**

1. **适用场景**：此配置适合小型应用，如果您的应用有高并发需求，请谨慎使用
2. **连接数限制**：最大连接数设置为 50，如果应用需要更多连接，请适当调整
3. **缓冲池大小**：如果服务器内存充足，可以适当增加 `innodb_buffer_pool_size`
4. **备份重要**：修改配置前请备份数据

### 性能监控

启动后可以通过以下命令监控内存使用：

```bash
# 查看容器内存使用
docker stats danmu-mysql

# 查看 MySQL 进程状态
docker exec danmu-mysql mysql -u root -p -e "SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages_%';"
```

## 🔄 恢复默认配置

如果需要恢复默认配置，只需：

1. 删除配置文件挂载：
   ```bash
   # 编辑 docker-compose.yaml，移除这一行：
   # - ./config/mysql.cnf:/etc/mysql/conf.d/custom.cnf:ro
   ```

2. 重启服务：
   ```bash
   docker-compose down
   docker-compose up -d
   ```


有问题请参考 [MySQL 官方文档](https://dev.mysql.com/doc/refman/8.0/en/server-system-variables.html) 或在项目中提 Issue。
