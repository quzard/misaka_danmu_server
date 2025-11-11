"""
弹幕源资源管理 API
支持从 GitHub 仓库加载编译好的 scraper 资源文件
"""
import logging
import shutil
import platform
import sys
import re
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, AsyncGenerator
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from ...database import get_db_session
from ...config_manager import ConfigManager
from ...api.dependencies import get_scraper_manager, get_config_manager
from ... import models
from ...security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_docker_environment():
    """检测是否在Docker容器中运行"""
    import os
    # 方法1: 检查 /.dockerenv 文件（Docker标准做法）
    if Path("/.dockerenv").exists():
        return True
    # 方法2: 检查环境变量
    if os.getenv("DOCKER_CONTAINER") == "true" or os.getenv("IN_DOCKER") == "true":
        return True
    # 方法3: 检查当前工作目录是否为 /app
    if Path.cwd() == Path("/app"):
        return True
    return False


def _get_scrapers_dir() -> Path:
    """获取 scrapers 目录路径"""
    if _is_docker_environment():
        return Path("/app/src/scrapers")
    else:
        return Path("src/scrapers")


def _get_backup_dir() -> Path:
    """获取备份目录路径"""
    if _is_docker_environment():
        return Path("/app/config/scrapers_backup")
    else:
        return Path("config/scrapers_backup")


# 备份目录配置
BACKUP_DIR = _get_backup_dir()
BACKUP_METADATA_FILE = BACKUP_DIR / "backup_metadata.json"

# 弹幕源版本信息文件
SCRAPERS_VERSIONS_FILE = _get_scrapers_dir() / "versions.json"


# 进度管理器
class ProgressManager:
    """管理操作进度的单例类"""
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.progress = {}
            cls._instance.queues = {}
        return cls._instance

    async def create_task(self, task_id: str):
        """创建新任务"""
        async with self._lock:
            self.progress[task_id] = {
                "status": "running",
                "current": 0,
                "total": 0,
                "message": ""
            }
            self.queues[task_id] = asyncio.Queue()

    async def update_progress(self, task_id: str, current: int, total: int, message: str = ""):
        """更新进度"""
        async with self._lock:
            if task_id in self.progress:
                self.progress[task_id] = {
                    "status": "running",
                    "current": current,
                    "total": total,
                    "message": message
                }
                if task_id in self.queues:
                    await self.queues[task_id].put({
                        "type": "progress",
                        "current": current,
                        "total": total,
                        "message": message
                    })

    async def complete_task(self, task_id: str, message: str = "完成"):
        """完成任务"""
        async with self._lock:
            if task_id in self.progress:
                self.progress[task_id]["status"] = "completed"
                self.progress[task_id]["message"] = message
                if task_id in self.queues:
                    await self.queues[task_id].put({
                        "type": "complete",
                        "message": message
                    })

    async def fail_task(self, task_id: str, error: str):
        """任务失败"""
        async with self._lock:
            if task_id in self.progress:
                self.progress[task_id]["status"] = "failed"
                self.progress[task_id]["message"] = error
                if task_id in self.queues:
                    await self.queues[task_id].put({
                        "type": "error",
                        "message": error
                    })

    async def get_queue(self, task_id: str) -> asyncio.Queue:
        """获取任务队列"""
        return self.queues.get(task_id)

    async def cleanup_task(self, task_id: str):
        """清理任务"""
        async with self._lock:
            self.progress.pop(task_id, None)
            self.queues.pop(task_id, None)


progress_manager = ProgressManager()


def get_platform_info() -> Dict[str, str]:
    """获取当前平台信息"""
    system = platform.system().lower()
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    machine = platform.machine().lower()

    # 映射平台名称
    platform_map = {
        'linux': 'linux',
        'darwin': 'macos',
        'windows': 'windows'
    }

    # 映射架构
    arch_map = {
        'x86_64': 'x86_64',
        'amd64': 'x86_64',
        'aarch64': 'aarch64',
        'arm64': 'aarch64'
    }

    return {
        'platform': platform_map.get(system, system),
        'python_version': python_version,
        'arch': arch_map.get(machine, machine)
    }


def get_platform_key() -> str:
    """获取当前平台的资源key (linux-x86/linux-arm/windows-amd64)"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # 映射架构
    arch_map = {
        'x86_64': 'x86',
        'amd64': 'amd64',
        'aarch64': 'arm',
        'arm64': 'arm'
    }

    arch = arch_map.get(machine, machine)

    if system == 'linux':
        return f'linux-{arch}'
    elif system == 'windows':
        return f'windows-{arch}'
    elif system == 'darwin':
        return f'macos-{arch}'
    else:
        return f'{system}-{arch}'


def parse_github_url(url: str) -> Dict[str, str]:
    """解析 GitHub 仓库 URL"""
    # 支持多种格式
    patterns = [
        r'github\.com/([^/]+)/([^/]+?)(?:\.git)?$',
        r'github\.com/([^/]+)/([^/]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return {
                'owner': match.group(1),
                'repo': match.group(2).replace('.git', '')
            }
    
    raise ValueError("无效的 GitHub 仓库链接")


@router.get("/scrapers/resource-repo", summary="获取资源仓库配置")
async def get_resource_repo(
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """获取当前配置的资源仓库链接"""
    repo_url = await config_manager.get("scraper_resource_repo", "")
    return {"repoUrl": repo_url}


@router.get("/scrapers/versions", summary="获取资源包版本信息")
async def get_versions(
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """获取本地和远程资源包版本号"""
    try:
        # 获取本地版本
        local_version = "unknown"
        local_package_file = _get_scrapers_dir() / "package.json"
        if local_package_file.exists():
            try:
                local_package = json.loads(local_package_file.read_text())
                local_version = local_package.get("version", "unknown")
            except Exception as e:
                logger.warning(f"读取本地 package.json 失败: {e}")

        # 获取远程版本
        remote_version = None
        repo_url = await config_manager.get("scraper_resource_repo", "")

        if repo_url:
            try:
                repo_info = parse_github_url(repo_url)
                owner = repo_info['owner']
                repo = repo_info['repo']

                # 获取 GitHub Token (如果配置了)
                github_token = await config_manager.get("github_token", "")
                headers = {}
                if github_token:
                    headers["Authorization"] = f"Bearer {github_token}"

                # 下载远程 package.json
                package_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/package.json"
                async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                    response = await client.get(package_url)
                    if response.status_code == 200:
                        remote_package = response.json()
                        remote_version = remote_package.get("version", "unknown")
            except Exception as e:
                logger.warning(f"获取远程版本失败: {e}")

        return {
            "localVersion": local_version,
            "remoteVersion": remote_version,
            "hasUpdate": remote_version and local_version != "unknown" and remote_version != local_version
        }

    except Exception as e:
        logger.error(f"获取版本信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取版本信息失败: {str(e)}")


@router.get("/scrapers/progress/{task_id}", summary="获取操作进度(SSE)")
async def get_progress_stream(
    task_id: str,
    current_user: models.User = Depends(get_current_user)
):
    """通过 Server-Sent Events 实时推送操作进度"""

    async def event_generator() -> AsyncGenerator[str, None]:
        """生成 SSE 事件流"""
        queue = await progress_manager.get_queue(task_id)
        if not queue:
            yield f"data: {json.dumps({'type': 'error', 'message': '任务不存在'})}\n\n"
            return

        try:
            while True:
                # 等待进度更新
                event = await asyncio.wait_for(queue.get(), timeout=30.0)

                # 发送事件
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                # 如果任务完成或失败,结束流
                if event.get("type") in ["complete", "error"]:
                    break

        except asyncio.TimeoutError:
            # 超时,发送心跳
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except Exception as e:
            logger.error(f"SSE 流错误: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # 清理任务
            await progress_manager.cleanup_task(task_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 nginx 缓冲
        }
    )


@router.put("/scrapers/resource-repo", status_code=status.HTTP_204_NO_CONTENT, summary="保存资源仓库配置")
async def save_resource_repo(
    payload: Dict[str, str],
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """保存资源仓库链接"""
    repo_url = payload.get("repoUrl", "").strip()
    if repo_url:
        # 验证 URL 格式
        try:
            parse_github_url(repo_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    await config_manager.setValue("scraper_resource_repo", repo_url)
    logger.info(f"用户 '{current_user.username}' 更新了资源仓库配置: {repo_url}")


@router.post("/scrapers/backup", summary="备份当前弹幕源")
async def backup_scrapers(
    current_user: models.User = Depends(get_current_user)
):
    """备份当前 scrapers 目录下的编译文件到持久化目录"""
    try:
        scrapers_dir = _get_scrapers_dir()

        # 创建备份目录
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        # 读取版本信息
        versions = {}
        if SCRAPERS_VERSIONS_FILE.exists():
            try:
                versions = json.loads(SCRAPERS_VERSIONS_FILE.read_text())
            except Exception as e:
                logger.warning(f"读取版本信息失败: {e}")

        # 清空旧备份文件（保留metadata.json）
        for file in BACKUP_DIR.glob("*"):
            if file.is_file() and file.name != "backup_metadata.json":
                file.unlink()

        # 备份 .so 和 .pyd 文件
        backup_count = 0
        backed_files = []
        for file in scrapers_dir.glob("*"):
            if file.suffix in ['.so', '.pyd']:
                shutil.copy2(file, BACKUP_DIR / file.name)

                # 从文件名提取弹幕源名称 (去掉扩展名)
                scraper_name = file.stem

                file_info = {
                    "name": file.name,
                    "scraper": scraper_name,
                    "size": file.stat().st_size,
                    "modified": datetime.fromtimestamp(file.stat().st_mtime).isoformat()
                }

                # 添加版本号（如果有）
                if scraper_name in versions:
                    file_info["version"] = versions[scraper_name]

                backed_files.append(file_info)
                backup_count += 1

        # 保存备份元数据
        metadata = {
            "backup_time": datetime.now().isoformat(),
            "backup_user": current_user.username,
            "file_count": backup_count,
            "files": backed_files,
            "platform": get_platform_key()
        }

        BACKUP_METADATA_FILE.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

        logger.info(f"用户 '{current_user.username}' 备份了 {backup_count} 个弹幕源文件到 {BACKUP_DIR}")
        return {"message": f"成功备份 {backup_count} 个文件", "count": backup_count}

    except Exception as e:
        logger.error(f"备份弹幕源失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"备份失败: {str(e)}")


@router.get("/scrapers/backup-info", summary="获取备份信息")
async def get_backup_info(
    current_user: models.User = Depends(get_current_user)
):
    """获取当前备份的详细信息"""
    try:
        if not BACKUP_DIR.exists() or not BACKUP_METADATA_FILE.exists():
            return {
                "hasBackup": False,
                "message": "暂无备份"
            }

        metadata = json.loads(BACKUP_METADATA_FILE.read_text())

        return {
            "hasBackup": True,
            "backupTime": metadata.get("backup_time"),
            "backupUser": metadata.get("backup_user"),
            "fileCount": metadata.get("file_count"),
            "platform": metadata.get("platform"),
            "files": metadata.get("files", [])
        }

    except Exception as e:
        logger.error(f"获取备份信息失败: {e}", exc_info=True)
        return {
            "hasBackup": False,
            "message": f"读取备份信息失败: {str(e)}"
        }


@router.post("/scrapers/restore", summary="从备份还原弹幕源")
async def restore_scrapers(
    current_user: models.User = Depends(get_current_user),
    manager = Depends(get_scraper_manager)
):
    """从持久化备份目录还原弹幕源文件"""
    try:
        scrapers_dir = _get_scrapers_dir()

        if not BACKUP_DIR.exists():
            raise HTTPException(status_code=404, detail="未找到备份目录")

        # 读取备份元数据
        backup_info = None
        if BACKUP_METADATA_FILE.exists():
            try:
                backup_info = json.loads(BACKUP_METADATA_FILE.read_text())
                logger.info(f"备份信息: {backup_info.get('backup_time')} by {backup_info.get('backup_user')}")
            except Exception as e:
                logger.warning(f"读取备份元数据失败: {e}")

        # 还原文件
        restore_count = 0
        for file in BACKUP_DIR.glob("*"):
            if file.is_file() and file.suffix in ['.so', '.pyd']:
                shutil.copy2(file, scrapers_dir / file.name)
                restore_count += 1

        if restore_count == 0:
            raise HTTPException(status_code=404, detail="备份目录为空")

        # 重新加载 scrapers
        await manager.load_and_sync_scrapers()

        logger.info(f"用户 '{current_user.username}' 从备份还原了 {restore_count} 个弹幕源文件")

        result = {
            "message": f"成功还原 {restore_count} 个文件",
            "count": restore_count
        }

        if backup_info:
            result["backupInfo"] = {
                "backupTime": backup_info.get("backup_time"),
                "backupUser": backup_info.get("backup_user"),
                "fileCount": backup_info.get("file_count")
            }

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"还原弹幕源失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"还原失败: {str(e)}")


@router.post("/scrapers/reload", summary="重载弹幕源")
async def reload_scrapers(
    current_user: models.User = Depends(get_current_user),
    manager = Depends(get_scraper_manager)
):
    """重新加载所有弹幕源"""
    try:
        await manager.load_and_sync_scrapers()
        logger.info(f"用户 '{current_user.username}' 重载了弹幕源")
        return {"message": "弹幕源重载成功"}
    except Exception as e:
        logger.error(f"重载弹幕源失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重载失败: {str(e)}")


@router.post("/scrapers/load-resources", summary="从资源仓库加载弹幕源")
async def load_resources(
    payload: Dict[str, Any],
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager),
    manager = Depends(get_scraper_manager)
):
    """从 GitHub 资源仓库下载并加载编译好的弹幕源文件"""
    # 生成任务ID
    task_id = payload.get("taskId")
    if not task_id:
        import uuid
        task_id = str(uuid.uuid4())

    # 创建进度任务
    await progress_manager.create_task(task_id)

    try:
        # 获取仓库链接
        await progress_manager.update_progress(task_id, 0, 100, "正在获取仓库信息...")
        repo_url = payload.get("repoUrl")
        if not repo_url:
            repo_url = await config_manager.get("scraper_resource_repo", "")

        if not repo_url:
            await progress_manager.fail_task(task_id, "未配置资源仓库链接")
            raise HTTPException(status_code=400, detail="未配置资源仓库链接")

        # 解析仓库信息
        repo_info = parse_github_url(repo_url)
        owner = repo_info['owner']
        repo = repo_info['repo']

        # 获取平台信息
        platform_key = get_platform_key()
        logger.info(f"当前平台: {platform_key}")

        # 获取 GitHub Token (如果配置了)
        github_token = await config_manager.get("github_token", "")
        headers = {}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
            logger.info("使用 GitHub Token 请求 API")

        # 下载 package.json
        await progress_manager.update_progress(task_id, 10, 100, "正在下载资源包信息...")
        package_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/package.json"
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(package_url)
            if response.status_code != 200:
                await progress_manager.fail_task(task_id, "无法获取资源包信息")
                raise HTTPException(status_code=404, detail="无法获取资源包信息，请检查仓库链接")

            package_data = response.json()

        # 获取资源列表 (支持 resources 字段)
        resources = package_data.get('resources', {})
        if not resources:
            await progress_manager.fail_task(task_id, "资源包中未找到弹幕源文件")
            raise HTTPException(status_code=404, detail="资源包中未找到弹幕源文件")

        # 保存 package.json 到本地
        local_package_file = _get_scrapers_dir() / "package.json"
        local_package_file.write_text(json.dumps(package_data, indent=2, ensure_ascii=False))

        # 先备份当前文件
        await progress_manager.update_progress(task_id, 20, 100, "正在备份当前文件...")
        await backup_scrapers(current_user)

        # 下载并替换文件
        await progress_manager.update_progress(task_id, 30, 100, "开始下载弹幕源文件...")
        scrapers_dir = _get_scrapers_dir()
        download_count = 0
        failed_downloads = []
        versions_data = {}  # 用于保存版本信息

        total_resources = len(resources)
        current_index = 0

        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            for scraper_name, scraper_info in resources.items():
                current_index += 1
                progress_percent = 30 + int((current_index / total_resources) * 50)  # 30-80%
                await progress_manager.update_progress(
                    task_id,
                    progress_percent,
                    100,
                    f"正在下载 {scraper_name} ({current_index}/{total_resources})..."
                )
                try:
                    # 获取当前平台的文件路径
                    files = scraper_info.get('files', {})
                    file_path = files.get(platform_key)

                    if not file_path:
                        logger.warning(f"弹幕源 {scraper_name} 不支持当前平台 {platform_key}")
                        failed_downloads.append(scraper_name)
                        continue

                    # 从路径中提取文件名
                    filename = Path(file_path).name

                    # 下载文件
                    file_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{file_path}"
                    logger.info(f"下载: {file_url}")

                    response = await client.get(file_url)
                    if response.status_code == 200:
                        # 保存文件 (保持原文件名)
                        target_path = scrapers_dir / filename
                        target_path.write_bytes(response.content)
                        download_count += 1
                        logger.info(f"成功下载: {filename}")

                        # 保存版本信息
                        version = scraper_info.get('version', 'unknown')
                        versions_data[scraper_name] = version
                    else:
                        failed_downloads.append(scraper_name)
                        logger.warning(f"下载失败 ({response.status_code}): {filename}")

                except Exception as e:
                    failed_downloads.append(scraper_name)
                    logger.error(f"下载 {scraper_name} 失败: {e}")

        # 保存版本信息到本地文件
        await progress_manager.update_progress(task_id, 85, 100, "正在保存版本信息...")
        if versions_data:
            try:
                SCRAPERS_VERSIONS_FILE.write_text(json.dumps(versions_data, indent=2, ensure_ascii=False))
                logger.info(f"已保存 {len(versions_data)} 个弹幕源的版本信息")
            except Exception as e:
                logger.warning(f"保存版本信息失败: {e}")

        if download_count == 0:
            # 下载失败，还原备份
            await progress_manager.fail_task(task_id, "所有文件下载失败")
            await restore_scrapers(current_user, manager)
            raise HTTPException(status_code=500, detail="所有文件下载失败，已还原备份")

        # 重新加载 scrapers
        try:
            await progress_manager.update_progress(task_id, 90, 100, "正在加载弹幕源...")
            await manager.load_and_sync_scrapers()
            logger.info(f"用户 '{current_user.username}' 成功加载了 {download_count} 个弹幕源")

            await progress_manager.complete_task(task_id, f"成功加载 {download_count} 个弹幕源")

            result = {
                "taskId": task_id,
                "message": f"成功加载 {download_count} 个弹幕源",
                "downloadCount": download_count,
                "totalCount": len(resources)
            }

            if failed_downloads:
                result["failedScrapers"] = failed_downloads
                result["message"] += f"，{len(failed_downloads)} 个失败"

            return result

        except Exception as e:
            # 加载失败，还原备份
            logger.error(f"加载弹幕源失败: {e}", exc_info=True)
            await progress_manager.fail_task(task_id, f"加载失败: {str(e)}")
            await restore_scrapers(current_user, manager)
            raise HTTPException(status_code=500, detail=f"加载失败已还原备份: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"加载资源失败: {e}", exc_info=True)
        await progress_manager.fail_task(task_id, f"加载失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"加载失败: {str(e)}")

