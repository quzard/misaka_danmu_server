#!/bin/sh
set -e

# 激活虚拟环境，确保使用 /opt/venv/bin/python
source /opt/venv/bin/activate

# This script is executed as the 'appuser'
echo "正在执行主程序: python -m src.main"

# 'exec' 命令会用 python 进程替换当前的 shell 进程，这对于正确的信号处理至关重要。
exec python -m src.main