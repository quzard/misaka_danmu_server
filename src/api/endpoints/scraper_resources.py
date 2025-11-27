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
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
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

# 全局锁：防止并发下载
_download_lock = asyncio.Lock()

# 版本信息缓存
_version_cache: Optional[Dict[str, Any]] = None
_version_cache_time: Optional[datetime] = None
_VERSION_CACHE_DURATION = timedelta(minutes=3)  # 缓存3分钟


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
SCRAPERS_PACKAGE_FILE = _get_scrapers_dir() / "package.json"


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


def _build_base_url(repo_info: Optional[Dict[str, str]], repo_url: str) -> str:
    """构造资源下载的base URL

    Args:
        repo_info: GitHub仓库解析信息 (包含owner, repo, proxy, proxy_type)
        repo_url: 原始仓库URL

    Returns:
        构造好的base URL
    """
    if repo_info:
        owner = repo_info['owner']
        repo = repo_info['repo']
        proxy = repo_info.get('proxy')
        proxy_type = repo_info.get('proxy_type')

        if proxy:
            if proxy_type == 'jsdelivr':
                return f"{proxy}/gh/{owner}/{repo}@main"
            else:  # generic_proxy
                return f"{proxy}/https://raw.githubusercontent.com/{owner}/{repo}/main"
        else:
            return f"https://raw.githubusercontent.com/{owner}/{repo}/main"
    else:
        # 非 GitHub 地址：视为静态资源根路径
        return repo_url.rstrip("/")


def parse_github_url(url: str) -> Dict[str, str]:
    """解析 GitHub 仓库 URL,支持代理链接

    支持的格式:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - https://任意域名/https://github.com/owner/repo (通用代理格式)
    - https://任意域名/https://raw.githubusercontent.com/owner/repo/main (通用代理格式)
    - https://cdn.jsdelivr.net/gh/owner/repo@main (jsDelivr CDN)
    - https://cdn.jsdelivr.net/gh/owner/repo (jsDelivr CDN)

    返回:
        {
            'owner': 'owner',
            'repo': 'repo',
            'proxy': 'https://代理域名' (如果有代理),
            'proxy_type': 'generic_proxy' | 'jsdelivr' (代理类型)
        }
    """
    # 检查是否是 jsDelivr CDN 格式
    jsdelivr_match = re.match(r'^https?://cdn\.jsdelivr\.net/gh/([^/]+)/([^/@]+)(?:@[^/]+)?', url)
    if jsdelivr_match:
        return {
            'owner': jsdelivr_match.group(1),
            'repo': jsdelivr_match.group(2),
            'proxy': 'https://cdn.jsdelivr.net',
            'proxy_type': 'jsdelivr'
        }

    # 检查是否是通用代理格式: https://任意域名/https://github.com/... 或 https://任意域名/github.com/...
    generic_proxy_match = re.match(r'^(https?://[^/]+)/https?://(github\.com|raw\.githubusercontent\.com)/([^/]+)/([^/]+)', url)
    if generic_proxy_match:
        return {
            'owner': generic_proxy_match.group(3),
            'repo': generic_proxy_match.group(4).replace('.git', '').split('/')[0],  # 去掉可能的路径部分
            'proxy': generic_proxy_match.group(1),
            'proxy_type': 'generic_proxy'
        }

    # 检查是否是简化的代理格式: https://任意域名/github.com/... (不带 https://)
    simple_proxy_match = re.match(r'^(https?://[^/]+)/(github\.com|raw\.githubusercontent\.com)/([^/]+)/([^/]+)', url)
    if simple_proxy_match:
        return {
            'owner': simple_proxy_match.group(3),
            'repo': simple_proxy_match.group(4).replace('.git', '').split('/')[0],  # 去掉可能的路径部分
            'proxy': simple_proxy_match.group(1),
            'proxy_type': 'generic_proxy'
        }

    # 普通 GitHub URL
    patterns = [
        r'github\.com/([^/]+)/([^/]+?)(?:\.git)?$',
        r'github\.com/([^/]+)/([^/]+)',
        r'raw\.githubusercontent\.com/([^/]+)/([^/]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return {
                'owner': match.group(1),
                'repo': match.group(2).replace('.git', '').split('/')[0]  # 去掉可能的路径部分
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


async def _fetch_package_version_with_retry(package_url: str, headers: Dict[str, str], max_retries: int = 3, proxy: Optional[str] = None) -> Optional[str]:
    """
    带重试机制的版本获取函数

    Args:
        package_url: package.json 的 URL
        headers: HTTP 请求头
        max_retries: 最大重试次数（默认3次）
        proxy: 代理URL（可选）

    Returns:
        版本号字符串，失败返回 None
    """
    timeout_config = httpx.Timeout(3.0, read=5.0)  # 降低超时时间：连接3秒，读取5秒

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout_config, headers=headers, follow_redirects=True, proxy=proxy) as client:
                response = await client.get(package_url)
                if response.status_code == 200:
                    package_data = response.json()
                    version = package_data.get("version", "unknown")
                    logger.info(f"成功获取版本信息: {version} (尝试 {attempt + 1}/{max_retries})")
                    return version
                else:
                    logger.warning(f"获取版本失败 HTTP {response.status_code} (尝试 {attempt + 1}/{max_retries})")
        except httpx.TimeoutException:
            logger.warning(f"连接超时 (尝试 {attempt + 1}/{max_retries})")
        except httpx.ConnectError as e:
            logger.warning(f"连接失败: {e} (尝试 {attempt + 1}/{max_retries})")
        except Exception as e:
            logger.warning(f"获取版本异常: {e} (尝试 {attempt + 1}/{max_retries})")

        # 如果不是最后一次尝试，等待一小段时间再重试
        if attempt < max_retries - 1:
            await asyncio.sleep(0.5)

    logger.error(f"获取版本失败，已重试 {max_retries} 次: {package_url}")
    return None


@router.get("/scrapers/versions", summary="获取资源包版本信息")
async def get_versions(
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager),
    force_refresh: bool = False  # 新增参数：强制刷新缓存
):
    """获取本地和远程资源包版本号（带缓存机制）"""
    global _version_cache, _version_cache_time

    try:
        # 检查缓存是否有效
        if not force_refresh and _version_cache and _version_cache_time:
            cache_age = datetime.now() - _version_cache_time
            if cache_age < _VERSION_CACHE_DURATION:
                logger.debug(f"使用缓存的版本信息 (缓存时间: {cache_age.total_seconds():.1f}秒)")
                return _version_cache

        # 获取本地版本
        local_version = "unknown"
        local_package_file = _get_scrapers_dir() / "package.json"
        if local_package_file.exists():
            try:
                local_package = json.loads(local_package_file.read_text())
                local_version = local_package.get("version", "unknown")
            except Exception as e:
                logger.warning(f"读取本地 package.json 失败: {e}")

        # 获取代理配置
        proxy_url = await config_manager.get("proxyUrl", "")
        proxy_enabled_str = await config_manager.get("proxyEnabled", "false")
        proxy_enabled = proxy_enabled_str.lower() == 'true'
        proxy_to_use = proxy_url if proxy_enabled and proxy_url else None

        # 获取远程版本（当前配置的资源仓库）
        remote_version = None
        repo_url = await config_manager.get("scraper_resource_repo", "")

        if repo_url:
            headers = {}
            repo_info = None
            try:
                repo_info = parse_github_url(repo_url)
            except ValueError:
                pass

            # 如果是GitHub仓库,添加Token
            if repo_info:
                github_token = await config_manager.get("github_token", "")
                if github_token:
                    headers["Authorization"] = f"Bearer {github_token}"

            base_url = _build_base_url(repo_info, repo_url)
            package_url = f"{base_url}/package.json"
            remote_version = await _fetch_package_version_with_retry(package_url, headers, proxy=proxy_to_use)

        # 固定源仓库（官方仓库）版本
        official_version = None
        try:
            official_repo_info = parse_github_url("https://github.com/l429609201/Misaka-Scraper-Resources")

            github_token = await config_manager.get("github_token", "")
            headers_official = {}
            if github_token:
                headers_official["Authorization"] = f"Bearer {github_token}"

            official_base_url = _build_base_url(official_repo_info, "https://github.com/l429609201/Misaka-Scraper-Resources")
            official_package_url = f"{official_base_url}/package.json"
            official_version = await _fetch_package_version_with_retry(official_package_url, headers_official, proxy=proxy_to_use)
        except Exception as e:
            logger.warning(f"获取官方资源仓库版本失败: {e}")

        # 构建结果
        result = {
            "localVersion": local_version,
            "remoteVersion": remote_version,
            "officialVersion": official_version,
            "hasUpdate": remote_version and local_version != "unknown" and remote_version != local_version
        }

        # 更新缓存
        _version_cache = result
        _version_cache_time = datetime.now()

        return result

    except Exception as e:
        logger.error(f"获取版本信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取版本信息失败: {str(e)}")


@router.put("/scrapers/resource-repo", status_code=status.HTTP_204_NO_CONTENT, summary="保存资源仓库配置")
async def save_resource_repo(
    payload: Dict[str, str],
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """保存资源仓库链接"""
    repo_url = payload.get("repoUrl", "").strip()
    if repo_url:
        # 基础校验：要求是 http/https 链接，其他格式直接拒绝
        if not (repo_url.startswith("http://") or repo_url.startswith("https://")):
            raise HTTPException(status_code=400, detail="资源仓库链接必须以 http:// 或 https:// 开头")

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

        # 备份 package.json 和 versions.json
        if SCRAPERS_PACKAGE_FILE.exists():
            shutil.copy2(SCRAPERS_PACKAGE_FILE, BACKUP_DIR / "package.json")
            logger.info("已备份 package.json")

        if SCRAPERS_VERSIONS_FILE.exists():
            shutil.copy2(SCRAPERS_VERSIONS_FILE, BACKUP_DIR / "versions.json")
            logger.info("已备份 versions.json")

        # 读取 package.json 的版本号
        package_version = None
        if SCRAPERS_PACKAGE_FILE.exists():
            try:
                package_data = json.loads(SCRAPERS_PACKAGE_FILE.read_text())
                package_version = package_data.get("version")
            except Exception as e:
                logger.warning(f"读取 package.json 失败: {e}")

        # 保存备份元数据
        metadata = {
            "backup_time": datetime.now().isoformat(),
            "backup_user": current_user.username,
            "file_count": backup_count,
            "files": backed_files,
            "platform": get_platform_key(),
            "package_version": package_version  # 添加资源包版本号
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

        # 还原 package.json
        backup_package_file = BACKUP_DIR / "package.json"
        if backup_package_file.exists():
            try:
                shutil.copy2(backup_package_file, SCRAPERS_PACKAGE_FILE)
                logger.info("已还原 package.json")
            except Exception as e:
                logger.warning(f"还原 package.json 失败: {e}")

        # 还原 versions.json
        backup_versions_file = BACKUP_DIR / "versions.json"
        if backup_versions_file.exists():
            try:
                shutil.copy2(backup_versions_file, SCRAPERS_VERSIONS_FILE)
                logger.info("已还原 versions.json")
            except Exception as e:
                logger.warning(f"还原 versions.json 失败: {e}")
        else:
            # 如果备份中没有 versions.json,尝试从备份元数据恢复
            if backup_info and "files" in backup_info:
                versions = {}
                for file_info in backup_info["files"]:
                    if "version" in file_info and "scraper" in file_info:
                        versions[file_info["scraper"]] = file_info["version"]

                # 写入 versions.json
                if versions:
                    try:
                        SCRAPERS_VERSIONS_FILE.write_text(json.dumps(versions, indent=2, ensure_ascii=False))
                        logger.info(f"从元数据恢复了 {len(versions)} 个弹幕源的版本信息")
                    except Exception as e:
                        logger.warning(f"写入版本信息失败: {e}")

        # 从备份元数据恢复 package.json
        if backup_info and "package_version" in backup_info:
            try:
                package_data = {
                    "version": backup_info["package_version"],
                    "restored_from_backup": True,
                    "restore_time": datetime.now().isoformat()
                }
                SCRAPERS_PACKAGE_FILE.write_text(json.dumps(package_data, indent=2, ensure_ascii=False))
                logger.info(f"恢复了资源包版本信息: {backup_info['package_version']}")
            except Exception as e:
                logger.warning(f"写入 package.json 失败: {e}")

        logger.info(f"用户 '{current_user.username}' 从备份还原了 {restore_count} 个弹幕源文件")

        result = {
            "message": f"成功还原 {restore_count} 个文件，正在后台重载...",
            "count": restore_count
        }

        if backup_info:
            result["backupInfo"] = {
                "backupTime": backup_info.get("backup_time"),
                "backupUser": backup_info.get("backup_user"),
                "fileCount": backup_info.get("file_count")
            }

        # 创建后台任务重新加载 scrapers
        async def reload_scrapers_background():
            await asyncio.sleep(1)  # 延迟1秒,确保响应已发送
            try:
                await manager.load_and_sync_scrapers()
                logger.info(f"用户 '{current_user.username}' 成功从备份重载了 {restore_count} 个弹幕源")
            except Exception as e:
                logger.error(f"后台重载弹幕源失败: {e}", exc_info=True)

        # 启动后台任务
        asyncio.create_task(reload_scrapers_background())

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
        logger.info(f"用户 '{current_user.username}' 请求重载弹幕源")

        # 创建后台任务重新加载 scrapers
        async def reload_scrapers_background():
            await asyncio.sleep(1)  # 延迟1秒,确保响应已发送
            try:
                await manager.load_and_sync_scrapers()
                logger.info(f"用户 '{current_user.username}' 成功重载了弹幕源")
            except Exception as e:
                logger.error(f"后台重载弹幕源失败: {e}", exc_info=True)

        # 启动后台任务
        asyncio.create_task(reload_scrapers_background())

        return {"message": "弹幕源重载请求已提交，正在后台重载..."}
    except Exception as e:
        logger.error(f"重载弹幕源失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重载失败: {str(e)}")


@router.post("/scrapers/load-resources-stream", summary="从资源仓库加载弹幕源(SSE流式)")
async def load_resources_stream(
    payload: Dict[str, Any],
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager),
    manager = Depends(get_scraper_manager)
):
    """从资源仓库下载并加载弹幕源文件,通过SSE推送进度"""

    async def event_generator():
        """SSE事件生成器"""
        # 检查是否有其他下载任务正在进行
        if _download_lock.locked():
            logger.warning("检测到并发下载请求，已拒绝")
            yield f"data: {json.dumps({'type': 'error', 'message': '已有下载任务正在进行，请稍后再试'}, ensure_ascii=False)}\n\n"
            return

        # 获取锁，防止并发下载
        logger.info("开始下载任务，已获取下载锁")
        async with _download_lock:
            try:
                last_heartbeat = asyncio.get_event_loop().time()

                async def send_heartbeat_if_needed():
                    """如果距离上次发送超过5秒,发送心跳"""
                    nonlocal last_heartbeat
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat > 5:
                        last_heartbeat = current_time
                        return ": heartbeat\n\n"
                    return None

                try:
                    # 获取仓库链接
                    repo_url = payload.get("repoUrl")
                    if not repo_url:
                        repo_url = await config_manager.get("scraper_resource_repo", "")

                    if not repo_url:
                        yield f"data: {json.dumps({'type': 'error', 'message': '未配置资源仓库链接'}, ensure_ascii=False)}\n\n"
                        return

                    # 获取平台信息
                    platform_key = get_platform_key()
                    platform_info = get_platform_info()
                    last_heartbeat = asyncio.get_event_loop().time()
                    yield f"data: {json.dumps({'type': 'info', 'message': f'当前平台: {platform_key}'}, ensure_ascii=False)}\n\n"

                    # 解析仓库URL并构造base_url
                    headers = {}
                    repo_info = None
                    try:
                        repo_info = parse_github_url(repo_url)
                    except ValueError:
                        pass

                    # 如果是GitHub仓库,添加Token
                    if repo_info:
                        github_token = await config_manager.get("github_token", "")
                        if github_token:
                            headers["Authorization"] = f"Bearer {github_token}"

                    base_url = _build_base_url(repo_info, repo_url)

                    # 获取代理配置
                    proxy_url = await config_manager.get("proxyUrl", "")
                    proxy_enabled_str = await config_manager.get("proxyEnabled", "false")
                    proxy_enabled = proxy_enabled_str.lower() == 'true'
                    proxy_to_use = proxy_url if proxy_enabled and proxy_url else None

                    if proxy_to_use:
                        logger.info(f"GitHub资源下载将使用代理: {proxy_to_use}")
                        yield f"data: {json.dumps({'type': 'info', 'message': f'使用代理: {proxy_to_use}'}, ensure_ascii=False)}\n\n"

                    # 下载 package.json
                    package_url = f"{base_url}/package.json"
                    logger.info(f"正在从 {package_url} 获取资源包信息...")
                    yield f"data: {json.dumps({'type': 'info', 'message': '正在获取资源包信息...'}, ensure_ascii=False)}\n\n"

                    # 设置更详细的超时配置: 连接超时5秒, 读取超时15秒
                    timeout_config = httpx.Timeout(5.0, read=15.0)

                    try:
                        async with httpx.AsyncClient(timeout=timeout_config, headers=headers, follow_redirects=True, proxy=proxy_to_use) as client:
                            response = await client.get(package_url)
                            if response.status_code != 200:
                                logger.error(f"获取资源包信息失败: HTTP {response.status_code}")
                                yield f"data: {json.dumps({'type': 'error', 'message': f'无法获取资源包信息 (HTTP {response.status_code})，请检查仓库链接或更换CDN节点'}, ensure_ascii=False)}\n\n"
                                return

                            package_data = response.json()
                            logger.info("成功获取资源包信息")
                    except httpx.TimeoutException as timeout_err:
                        logger.error(f"连接超时: {timeout_err}")
                        yield f"data: {json.dumps({'type': 'error', 'message': '连接超时，请检查网络或更换CDN节点'}, ensure_ascii=False)}\n\n"
                        return
                    except httpx.ConnectError as conn_err:
                        logger.error(f"连接失败: {conn_err}")
                        yield f"data: {json.dumps({'type': 'error', 'message': '无法连接到资源仓库，请检查网络或更换CDN节点'}, ensure_ascii=False)}\n\n"
                        return
                    except Exception as e:
                        logger.error(f"获取资源包信息异常: {e}", exc_info=True)
                        yield f"data: {json.dumps({'type': 'error', 'message': f'获取资源包信息失败: {str(e)}'}, ensure_ascii=False)}\n\n"
                        return

                    # 获取资源列表 (支持 resources 字段)
                    resources = package_data.get('resources', {})
                    if not resources:
                        logger.error("资源包中未找到弹幕源文件")
                        yield f"data: {json.dumps({'type': 'error', 'message': '资源包中未找到弹幕源文件'}, ensure_ascii=False)}\n\n"
                        return

                    # 计算总数
                    total_count = len(resources)
                    logger.info(f"发现 {total_count} 个弹幕源待下载")
                    yield f"data: {json.dumps({'type': 'total', 'total': total_count}, ensure_ascii=False)}\n\n"

                    # 保存 package.json 到本地 - 使用异步IO
                    local_package_file = _get_scrapers_dir() / "package.json"
                    package_json_str = json.dumps(package_data, indent=2, ensure_ascii=False)
                    await asyncio.to_thread(local_package_file.write_text, package_json_str)

                    # 先备份当前文件
                    yield f"data: {json.dumps({'type': 'info', 'message': '正在备份当前弹幕源...'}, ensure_ascii=False)}\n\n"
                    try:
                        await backup_scrapers(current_user)
                        logger.info("备份当前弹幕源成功")
                        yield f"data: {json.dumps({'type': 'info', 'message': '备份完成,开始下载...'}, ensure_ascii=False)}\n\n"
                    except Exception as backup_error:
                        logger.error(f"备份失败: {backup_error}")
                        yield f"data: {json.dumps({'type': 'error', 'message': f'备份失败: {str(backup_error)}'}, ensure_ascii=False)}\n\n"
                        return

                    # 下载并替换文件
                    scrapers_dir = _get_scrapers_dir()
                    download_count = 0
                    skip_count = 0  # 跳过的文件数(哈希值相同)
                    failed_downloads = []
                    versions_data = {}  # 用于保存版本信息
                    hashes_data = {}  # 用于保存哈希值

                    # 下载并替换文件
                    download_timeout = httpx.Timeout(3.0, read=15.0)
                    async with httpx.AsyncClient(timeout=download_timeout, headers=headers, follow_redirects=True, proxy=proxy_to_use) as client:
                        for index, (scraper_name, scraper_info) in enumerate(resources.items(), 1):
                            await asyncio.sleep(0)

                            # 发送心跳
                            heartbeat = await send_heartbeat_if_needed()
                            if heartbeat:
                                yield heartbeat

                            try:
                                # 获取当前平台的文件路径
                                files = scraper_info.get('files', {})
                                file_path = files.get(platform_key)

                                if not file_path:
                                    logger.warning(f"\t弹幕源 {scraper_name} 不支持当前平台 {platform_key}")
                                    failed_downloads.append(scraper_name)
                                    last_heartbeat = asyncio.get_event_loop().time()
                                    yield f"data: {json.dumps({'type': 'skip', 'scraper': scraper_name, 'current': index, 'total': total_count}, ensure_ascii=False)}\n\n"
                                    continue

                                # 从路径中提取文件名
                                filename = Path(file_path).name
                                target_path = scrapers_dir / filename

                                # 获取远程文件的哈希值
                                remote_hashes = scraper_info.get('hashes', {})
                                remote_hash = remote_hashes.get(platform_key)

                                # 检查是否需要下载(只对比 JSON 中的哈希值)
                                should_download = True
                                if remote_hash:
                                    # 远程有哈希值,从本地 versions.json 读取哈希值
                                    local_hash = None
                                    if SCRAPERS_VERSIONS_FILE.exists():
                                        try:
                                            local_versions = json.loads(await asyncio.to_thread(SCRAPERS_VERSIONS_FILE.read_text))
                                            local_hashes = local_versions.get('hashes', {})
                                            local_hash = local_hashes.get(scraper_name)
                                        except Exception as e:
                                            logger.debug(f"读取本地版本文件失败: {e}")

                                    # 比较哈希值
                                    if local_hash and local_hash == remote_hash:
                                        # 哈希值相同,跳过下载
                                        should_download = False
                                        skip_count += 1
                                        version = scraper_info.get('version', 'unknown')
                                        versions_data[scraper_name] = version
                                        hashes_data[scraper_name] = remote_hash

                                        logger.info(f"\t跳过下载 {scraper_name} ({filename}) - 哈希值相同 [{index}/{total_count}]")
                                        last_heartbeat = asyncio.get_event_loop().time()
                                        yield f"data: {json.dumps({'type': 'skip_hash', 'scraper': scraper_name, 'filename': filename, 'current': index, 'total': total_count}, ensure_ascii=False)}\n\n"

                                if not should_download:
                                    continue

                                # 推送下载进度
                                progress = int((index / total_count) * 100)
                                last_heartbeat = asyncio.get_event_loop().time()
                                yield f"data: {json.dumps({'type': 'progress', 'scraper': scraper_name, 'filename': filename, 'current': index, 'total': total_count, 'progress': progress}, ensure_ascii=False)}\n\n"

                                # 下载文件 - 重试机制
                                file_url = f"{base_url}/{file_path}"
                                max_retries = 3
                                logger.info(f"\t开始下载 {scraper_name} ({filename}) [{index}/{total_count}]")

                                for retry_count in range(max_retries + 1):
                                    try:
                                        if retry_count > 0:
                                            logger.info(f"\t\t[重试 {retry_count}/{max_retries}] 下载 {scraper_name}")
                                            await asyncio.sleep(1.0)

                                        response = await asyncio.wait_for(client.get(file_url), timeout=18.0)

                                        if response.status_code == 200:
                                            # 写入文件
                                            await asyncio.to_thread(target_path.write_bytes, response.content)

                                            # 保存远程哈希值(如果有)
                                            if remote_hash:
                                                hashes_data[scraper_name] = remote_hash

                                            download_count += 1
                                            version = scraper_info.get('version', 'unknown')
                                            versions_data[scraper_name] = version

                                            logger.info(f"\t成功下载: {filename} (版本: {version})")
                                            last_heartbeat = asyncio.get_event_loop().time()
                                            yield f"data: {json.dumps({'type': 'success', 'scraper': scraper_name, 'filename': filename}, ensure_ascii=False)}\n\n"
                                            break
                                        else:
                                            if retry_count == max_retries:
                                                failed_downloads.append(scraper_name)
                                                logger.error(f"\t下载失败 {scraper_name}: HTTP {response.status_code}")
                                                yield f"data: {json.dumps({'type': 'failed', 'scraper': scraper_name, 'message': f'HTTP {response.status_code}'}, ensure_ascii=False)}\n\n"

                                    except (httpx.TimeoutException, asyncio.TimeoutError, httpx.ConnectError) as e:
                                        if retry_count == max_retries:
                                            failed_downloads.append(scraper_name)
                                            error_msg = "超时" if isinstance(e, (httpx.TimeoutException, asyncio.TimeoutError)) else "连接失败"
                                            logger.error(f"\t下载失败 {scraper_name}: {error_msg}")
                                            yield f"data: {json.dumps({'type': 'failed', 'scraper': scraper_name, 'message': error_msg}, ensure_ascii=False)}\n\n"

                            except Exception as e:
                                failed_downloads.append(scraper_name)
                                logger.error(f"\t下载 {scraper_name} 失败: {e}")
                                yield f"data: {json.dumps({'type': 'failed', 'scraper': scraper_name, 'message': str(e)}, ensure_ascii=False)}\n\n"

                    # 保存版本信息和哈希值
                    if versions_data:
                        try:
                            # 构建完整的版本信息
                            full_versions_data = {
                                "platform": platform_info['platform'],
                                "type": platform_info['arch'],
                                "version": package_data.get("version", "unknown"),
                                "scrapers": versions_data
                            }

                            # 只有当有哈希值数据时才添加 hashes 字段(兼容旧版本)
                            if hashes_data:
                                full_versions_data["hashes"] = hashes_data
                                logger.info(f"已保存 {len(versions_data)} 个弹幕源的版本信息和 {len(hashes_data)} 个哈希值")
                            else:
                                logger.info(f"已保存 {len(versions_data)} 个弹幕源的版本信息(无哈希值)")

                            versions_json_str = json.dumps(full_versions_data, indent=2, ensure_ascii=False)
                            await asyncio.to_thread(SCRAPERS_VERSIONS_FILE.write_text, versions_json_str)
                        except Exception as e:
                            logger.warning(f"保存版本信息失败: {e}")

                    # 检查下载结果
                    if download_count == 0 and skip_count == 0:
                        logger.error("没有成功下载任何弹幕源,取消重载")
                        yield f"data: {json.dumps({'type': 'error', 'message': '没有成功下载任何弹幕源,已取消重载。请检查网络连接或更换CDN节点'}, ensure_ascii=False)}\n\n"
                        try:
                            await restore_scrapers(current_user, manager)
                            logger.info("已还原备份")
                        except Exception as restore_error:
                            logger.error(f"还原备份失败: {restore_error}", exc_info=True)
                        return

                    # 推送完成信息
                    logger.info(f"下载完成: 成功 {download_count} 个, 跳过 {skip_count} 个, 失败 {len(failed_downloads)} 个")
                    yield f"data: {json.dumps({'type': 'complete', 'downloaded': download_count, 'skipped': skip_count, 'failed': len(failed_downloads), 'failed_list': failed_downloads}, ensure_ascii=False)}\n\n"

                    # 后台重载任务
                    async def reload_scrapers_background():
                        global _version_cache, _version_cache_time
                        await asyncio.sleep(0.5)
                        try:
                            logger.info("开始重载弹幕源...")
                            await manager.load_and_sync_scrapers()
                            logger.info(f"用户 '{current_user.username}' 成功加载了 {download_count} 个弹幕源")
                            _version_cache = None
                            _version_cache_time = None
                        except Exception as e:
                            logger.error(f"后台加载弹幕源失败: {e}", exc_info=True)
                            try:
                                logger.info("尝试还原备份...")
                                await restore_scrapers(current_user, manager)
                                logger.info("已还原备份")
                            except Exception as restore_error:
                                logger.error(f"还原备份失败: {restore_error}", exc_info=True)

                    asyncio.create_task(reload_scrapers_background())

                except Exception as e:
                    logger.error(f"加载资源失败: {e}", exc_info=True)
                    yield f"data: {json.dumps({'type': 'error', 'message': f'加载失败: {str(e)}'}, ensure_ascii=False)}\n\n"
            finally:
                logger.info("下载任务结束，释放下载锁")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/scrapers/auto-update", summary="获取自动更新配置")
async def get_auto_update_config(
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """获取弹幕源自动更新配置"""
    enabled = await config_manager.get("scraperAutoUpdateEnabled", "false")
    interval = await config_manager.get("scraperAutoUpdateInterval", "15")
    return {
        "enabled": enabled.lower() == "true",
        "interval": int(interval)
    }


@router.put("/scrapers/auto-update", status_code=status.HTTP_204_NO_CONTENT, summary="保存自动更新配置")
async def save_auto_update_config(
    payload: Dict[str, Any],
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """保存弹幕源自动更新配置"""
    enabled = payload.get("enabled", False)
    interval = payload.get("interval", 15)

    await config_manager.setValue("scraperAutoUpdateEnabled", str(enabled).lower())
    await config_manager.setValue("scraperAutoUpdateInterval", str(interval))

    logger.info(f"用户 '{current_user.username}' 更新了自动更新配置: enabled={enabled}, interval={interval}分钟")


@router.delete("/scrapers/backup", summary="删除弹幕源备份")
async def delete_backup(
    current_user: models.User = Depends(get_current_user)
):
    """删除持久化备份目录中的所有备份文件"""
    try:
        if not BACKUP_DIR.exists():
            raise HTTPException(status_code=404, detail="未找到备份目录")

        # 统计并删除备份文件
        deleted_count = 0
        for file in BACKUP_DIR.glob("*"):
            if file.is_file():
                file.unlink()
                deleted_count += 1

        # 删除备份目录（如果为空）
        try:
            BACKUP_DIR.rmdir()
        except OSError:
            pass  # 目录不为空或其他原因无法删除，忽略

        logger.info(f"用户 '{current_user.username}' 删除了 {deleted_count} 个备份文件")
        return {"message": f"成功删除 {deleted_count} 个备份文件"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除备份失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除备份失败: {str(e)}")


@router.delete("/scrapers/current", summary="删除当前弹幕源")
async def delete_current_scrapers(
    current_user: models.User = Depends(get_current_user),
    manager = Depends(get_scraper_manager)
):
    """删除当前 scrapers 目录下的所有编译文件（.so/.pyd）"""
    try:
        scrapers_dir = _get_scrapers_dir()

        if not scrapers_dir.exists():
            raise HTTPException(status_code=404, detail="未找到弹幕源目录")

        # 删除 .so 和 .pyd 文件
        deleted_count = 0
        for file in scrapers_dir.glob("*"):
            if file.suffix in ['.so', '.pyd']:
                file.unlink()
                deleted_count += 1

        # 删除 package.json 和 versions.json
        if SCRAPERS_PACKAGE_FILE.exists():
            SCRAPERS_PACKAGE_FILE.unlink()
            logger.info("已删除 package.json")

        if SCRAPERS_VERSIONS_FILE.exists():
            SCRAPERS_VERSIONS_FILE.unlink()
            logger.info("已删除 versions.json")

        # 清除版本缓存
        global _version_cache, _version_cache_time
        _version_cache = None
        _version_cache_time = None

        logger.info(f"用户 '{current_user.username}' 删除了 {deleted_count} 个弹幕源文件")

        # 创建后台任务重新加载 scrapers（此时应该是空的）
        async def reload_scrapers_background():
            await asyncio.sleep(1)
            try:
                await manager.load_and_sync_scrapers()
                logger.info(f"用户 '{current_user.username}' 删除弹幕源后已重载")
            except Exception as e:
                logger.error(f"后台重载弹幕源失败: {e}", exc_info=True)

        asyncio.create_task(reload_scrapers_background())

        return {"message": f"成功删除 {deleted_count} 个弹幕源文件，正在后台重载..."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除当前弹幕源失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
