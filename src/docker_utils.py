"""
Docker 工具模块

提供 Docker 容器管理功能，包括：
- 检测 Docker socket 是否可用
- 重启容器（通过 Docker API 或进程退出）
- 拉取镜像
- 使用 watchtower 更新容器
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Generator

logger = logging.getLogger(__name__)

# Docker socket 路径
DOCKER_SOCKET_PATH = "/var/run/docker.sock"

# 尝试导入 docker 库
try:
    import docker
    from docker.errors import DockerException, NotFound, APIError
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None
    DockerException = Exception
    NotFound = Exception
    APIError = Exception


def is_docker_socket_available() -> bool:
    """
    检测 Docker socket 是否可用
    
    Returns:
        bool: Docker socket 是否可用
    """
    if not DOCKER_AVAILABLE:
        logger.debug("Docker SDK 未安装")
        return False
    
    # 检查 socket 文件是否存在
    if not Path(DOCKER_SOCKET_PATH).exists():
        logger.debug(f"Docker socket 不存在: {DOCKER_SOCKET_PATH}")
        return False
    
    # 尝试连接 Docker daemon
    try:
        client = docker.from_env()
        client.ping()
        logger.debug("Docker socket 可用")
        return True
    except Exception as e:
        logger.debug(f"无法连接 Docker daemon: {e}")
        return False


def get_docker_client() -> Optional[Any]:
    """
    获取 Docker 客户端
    
    Returns:
        docker.DockerClient 或 None
    """
    if not DOCKER_AVAILABLE:
        return None
    
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"获取 Docker 客户端失败: {e}")
        return None


def get_docker_status() -> Dict[str, Any]:
    """
    获取 Docker 状态信息

    Returns:
        包含 Docker 状态的字典
    """
    status = {
        "sdkInstalled": DOCKER_AVAILABLE,
        "socketAvailable": False,
        "socketPath": DOCKER_SOCKET_PATH,
        "socketExists": Path(DOCKER_SOCKET_PATH).exists(),
        "canRestart": False,
        "canUpdate": False,
    }

    if not DOCKER_AVAILABLE:
        status["message"] = "Docker SDK 未安装，请确保已安装 docker 库 (pip install docker)"
        return status

    if not Path(DOCKER_SOCKET_PATH).exists():
        status["message"] = f"Docker 套接字 未映射 ({DOCKER_SOCKET_PATH})，请在 docker-compose.yml 中添加: - /var/run/docker.sock:/var/run/docker.sock"
        return status

    try:
        client = docker.from_env()
        client.ping()
        status["socketAvailable"] = True
        status["canRestart"] = True
        status["canUpdate"] = True
        status["message"] = "Docker 连接正常"
    except PermissionError as e:
        status["message"] = f"权限不足，无法访问 Docker socket。请确保容器有权限访问 /var/run/docker.sock (错误: {str(e)})"
    except Exception as e:
        status["message"] = f"无法连接 Docker daemon: {str(e)}"

    return status


async def restart_container(container_name: str) -> Dict[str, Any]:
    """
    重启指定容器
    
    Args:
        container_name: 容器名称
        
    Returns:
        操作结果字典
    """
    if not is_docker_socket_available():
        return {
            "success": False,
            "message": "Docker socket 不可用，无法通过 Docker API 重启",
            "fallback": True
        }
    
    try:
        client = get_docker_client()
        if not client:
            return {"success": False, "message": "无法获取 Docker 客户端", "fallback": True}
        
        container = client.containers.get(container_name)
        logger.info(f"正在重启容器: {container_name}")
        container.restart(timeout=10)
        
        return {
            "success": True,
            "message": f"已向容器 '{container_name}' 发送重启指令"
        }
    except NotFound:
        return {
            "success": False,
            "message": f"找不到名为 '{container_name}' 的容器",
            "fallback": True
        }
    except Exception as e:
        logger.error(f"重启容器失败: {e}")
        return {
            "success": False,
            "message": f"重启容器失败: {str(e)}",
            "fallback": True
        }


def restart_via_exit() -> None:
    """
    通过退出进程来触发容器重启（依赖 Docker 的 restart policy）

    这是在没有 Docker socket 时的备用方案
    """
    logger.info("正在通过退出进程触发容器重启...")
    sys.exit(0)


def pull_image_stream(image_name: str, proxy_url: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
    """
    流式拉取 Docker 镜像

    Args:
        image_name: 镜像名称（含标签）
        proxy_url: 代理 URL（可选）

    Yields:
        拉取进度信息
    """
    if not is_docker_socket_available():
        yield {"status": "Docker 套接字 不可用", "event": "ERROR"}
        return

    # 设置代理环境变量
    old_env = os.environ.copy()
    try:
        if proxy_url:
            os.environ['HTTPS_PROXY'] = proxy_url
            os.environ['HTTP_PROXY'] = proxy_url
            yield {"status": f"使用代理: {proxy_url}"}

        client = get_docker_client()
        if not client:
            yield {"status": "无法获取 Docker 客户端", "event": "ERROR"}
            return

        yield {"status": f"正在拉取镜像: {image_name}..."}

        # 使用低级 API 获取流式输出
        stream = client.api.pull(image_name, stream=True, decode=True)

        last_line = {}
        for line in stream:
            last_line = line
            # 可以在这里发送更详细的进度，但为简化只保留最后状态

        # 检查最终状态
        final_status = last_line.get('status', '')
        if 'Status: Image is up to date' in final_status:
            yield {"status": "当前已是最新版本", "event": "UP_TO_DATE"}
        elif 'errorDetail' in last_line:
            error_msg = last_line['errorDetail'].get('message', '未知错误')
            yield {"status": f"拉取失败: {error_msg}", "event": "ERROR"}
        else:
            yield {"status": "镜像拉取完成", "event": "PULLED"}

    except Exception as e:
        logger.error(f"拉取镜像失败: {e}")
        yield {"status": f"拉取镜像失败: {str(e)}", "event": "ERROR"}
    finally:
        # 恢复环境变量
        os.environ.clear()
        os.environ.update(old_env)


def update_container_with_watchtower(
    container_name: str,
    watchtower_image: str = "containrrr/watchtower"
) -> Generator[Dict[str, Any], None, None]:
    """
    使用 watchtower 更新容器

    Args:
        container_name: 要更新的容器名称
        watchtower_image: watchtower 镜像名称

    Yields:
        更新进度信息
    """
    if not is_docker_socket_available():
        yield {"status": "Docker socket 不可用", "event": "ERROR"}
        return

    try:
        client = get_docker_client()
        if not client:
            yield {"status": "无法获取 Docker 客户端", "event": "ERROR"}
            return

        # 确保 watchtower 镜像存在
        try:
            client.images.get(watchtower_image)
        except NotFound:
            yield {"status": f"正在拉取更新工具: {watchtower_image}..."}
            client.images.pull(watchtower_image)

        yield {"status": "正在启动更新任务..."}

        # 运行 watchtower 一次性更新
        command = ["--cleanup", "--run-once", container_name]

        client.containers.run(
            image=watchtower_image,
            command=command,
            remove=True,
            detach=True,
            volumes={DOCKER_SOCKET_PATH: {'bind': DOCKER_SOCKET_PATH, 'mode': 'rw'}}
        )

        yield {"status": "更新任务已启动，容器将在后台被重启"}
        yield {"status": "请稍后刷新页面访问新版本", "event": "DONE"}

    except NotFound:
        yield {"status": f"找不到容器: {container_name}", "event": "ERROR"}
    except Exception as e:
        logger.error(f"更新容器失败: {e}")
        yield {"status": f"更新失败: {str(e)}", "event": "ERROR"}

