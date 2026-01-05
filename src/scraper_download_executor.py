"""
弹幕源下载执行器

将下载逻辑从 SSE 连接中解耦，实现后台独立运行
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .download_task_manager import (
    DownloadTask,
    DownloadTaskManager,
    TaskStatus,
    get_download_task_manager,
)

logger = logging.getLogger(__name__)

# 导入需要的工具函数（稍后从 scraper_resources.py 中提取）
SCRAPERS_DIR = Path("/app/scrapers")
SCRAPERS_VERSIONS_FILE = SCRAPERS_DIR / "versions.json"


def _get_scrapers_dir() -> Path:
    """获取弹幕源目录"""
    from .api.endpoints.scraper_resources import _get_scrapers_dir as get_dir
    return get_dir()


def get_platform_key() -> str:
    """获取平台标识"""
    from .api.endpoints.scraper_resources import get_platform_key as get_key
    return get_key()


def get_platform_info() -> Dict[str, str]:
    """获取平台信息"""
    from .api.endpoints.scraper_resources import get_platform_info as get_info
    return get_info()


def parse_github_url(url: str):
    """解析 GitHub URL"""
    from .api.endpoints.scraper_resources import parse_github_url as parse_gh
    return parse_gh(url)


def parse_gitee_url(url: str):
    """解析 Gitee URL"""
    from .api.endpoints.scraper_resources import parse_gitee_url as parse_gt
    return parse_gt(url)


def _build_base_url(repo_info, repo_url: str, gitee_info) -> str:
    """构建基础 URL"""
    from .api.endpoints.scraper_resources import _build_base_url as build_url
    return build_url(repo_info, repo_url, gitee_info)


class ScraperDownloadExecutor:
    """弹幕源下载执行器"""

    def __init__(
        self,
        task: DownloadTask,
        config_manager,
        scraper_manager,
        current_user,
    ):
        self.task = task
        self.config_manager = config_manager
        self.scraper_manager = scraper_manager
        self.current_user = current_user
        self._task_manager = get_download_task_manager()

    def _log(self, message: str, level: str = "info"):
        """记录日志并添加到任务消息"""
        self.task.add_message(message)
        log_func = getattr(logger, level, logger.info)
        log_func(f"[任务 {self.task.task_id}] {message}")

    async def _log_async(self, message: str, level: str = "info"):
        """异步版本的日志记录（用于 progress_callback）"""
        self._log(message, level)

    async def execute(self):
        """执行下载任务"""
        self.task.status = TaskStatus.RUNNING
        self.task.started_at = datetime.now()
        self._task_manager.set_current_task(self.task.task_id)

        try:
            await self._do_download()
        except asyncio.CancelledError:
            self._log("任务被取消", "warning")
            self.task.status = TaskStatus.CANCELLED
            raise
        except Exception as e:
            self._log(f"任务执行失败: {e}", "error")
            self.task.status = TaskStatus.FAILED
            self.task.error_message = str(e)
        finally:
            self.task.completed_at = datetime.now()
            self._task_manager.clear_current_task()

    async def _do_download(self):
        """执行实际的下载逻辑"""
        repo_url = self.task.repo_url
        if not repo_url:
            repo_url = await self.config_manager.get("scraper_resource_repo", "")

        if not repo_url:
            raise ValueError("未配置资源仓库链接")

        self._log(f"开始下载，仓库: {repo_url}")

        # 获取平台信息
        platform_key = get_platform_key()
        platform_info = get_platform_info()
        self._log(f"当前平台: {platform_key}")

        # 解析仓库 URL
        headers = {}
        repo_info = None
        gitee_info = parse_gitee_url(repo_url)

        if not gitee_info:
            try:
                repo_info = parse_github_url(repo_url)
            except ValueError:
                pass

        # GitHub Token
        if repo_info:
            github_token = await self.config_manager.get("github_token", "")
            if github_token:
                headers["Authorization"] = f"Bearer {github_token}"

        base_url = _build_base_url(repo_info, repo_url, gitee_info)

        # 代理配置
        proxy_url = await self.config_manager.get("proxyUrl", "")
        proxy_enabled_str = await self.config_manager.get("proxyEnabled", "false")
        proxy_enabled = proxy_enabled_str.lower() == "true"
        proxy_to_use = proxy_url if proxy_enabled and proxy_url else None

        if proxy_to_use:
            self._log(f"使用代理: {proxy_to_use}")

        # 检查是否使用全量替换
        if self.task.use_full_replace:
            await self._do_full_replace(repo_info, gitee_info, headers, proxy_to_use, platform_key)
        else:
            await self._do_incremental_download(base_url, headers, proxy_to_use, platform_key, platform_info)

    async def _do_full_replace(self, repo_info, gitee_info, headers, proxy_to_use, platform_key):
        """全量替换模式"""
        from .api.endpoints.scraper_resources import (
            _fetch_github_release_asset,
            _fetch_gitee_release_asset,
            _download_and_extract_release,
            backup_scrapers,
        )

        self._log("使用全量替换模式")

        # 获取 Release 资产信息
        asset_info = None
        if gitee_info:
            self._log("正在从 Gitee Releases 获取压缩包...")
            asset_info = await _fetch_gitee_release_asset(
                gitee_info=gitee_info,
                platform_key=platform_key,
                headers=headers,
                proxy=proxy_to_use
            )
        elif repo_info:
            self._log("正在从 GitHub Releases 获取压缩包...")
            asset_info = await _fetch_github_release_asset(
                repo_info=repo_info,
                platform_key=platform_key,
                headers=headers,
                proxy=proxy_to_use
            )

        if not asset_info:
            raise ValueError("未找到匹配的 Release 压缩包")

        self._log(f"找到压缩包: {asset_info['filename']} (版本: {asset_info['version']})")

        # 备份当前文件
        self._log("正在备份当前弹幕源...")
        await backup_scrapers(self.current_user)
        self._log("备份完成")

        # 下载并解压
        scrapers_dir = _get_scrapers_dir()
        self._log("正在下载压缩包...")

        success = await _download_and_extract_release(
            asset_info=asset_info,
            scrapers_dir=scrapers_dir,
            headers=headers,
            proxy=proxy_to_use,
            progress_callback=self._log_async
        )

        if success:
            self.task.progress.current = 1
            self.task.progress.total = 1
            self.task.progress.downloaded.append("full_replace")
            self._log("全量替换完成")
            self.task.status = TaskStatus.COMPLETED

            # 备份新下载的资源
            self._log("正在备份新下载的资源...")
            await backup_scrapers(self.current_user)
            self._log("✓ 新资源备份完成")

            # 检查是否有 Docker socket，决定重启方式
            from .docker_utils import is_docker_socket_available, restart_container
            docker_available = is_docker_socket_available()

            if docker_available:
                # 有 Docker socket，执行容器级别重启
                from .docker_utils import get_current_container_id
                detected_id = get_current_container_id()

                self._log("⚠️ 全量替换后需要重启容器以加载新的 .so 文件")
                if detected_id:
                    self._log(f"检测到当前容器 ID: {detected_id}")
                    logger.info(f"自动检测到当前容器 ID: {detected_id}")
                else:
                    fallback_name = await self.config_manager.get("containerName", "misaka_danmu_server")
                    self._log(f"未能自动检测容器 ID，将使用兜底名称: {fallback_name}")
                    logger.info(f"未能自动检测容器 ID，将使用兜底名称: {fallback_name}")

                self._log("将在 2 秒后重启容器...")
                logger.info(f"用户 '{self.current_user.username}' 通过全量替换模式更新了弹幕源，即将重启容器")

                # 等待日志写入
                await asyncio.sleep(2.0)

                fallback_name = await self.config_manager.get("containerName", "misaka_danmu_server")
                result = await restart_container(fallback_name)
                if result.get("success"):
                    container_id = result.get("container_id", "unknown")
                    self._log(f"✓ 已向容器发送重启指令 (ID: {container_id})")
                    logger.info(f"已向容器发送重启指令 (ID: {container_id})")
                else:
                    self._log(f"重启容器失败: {result.get('message')}，尝试热加载")
                    logger.warning(f"重启容器失败: {result.get('message')}，尝试热加载")
                    await self.scraper_manager.load_and_sync_scrapers()
            else:
                # 没有 Docker socket，执行软重启（热加载）
                self._log("⚠️ 未检测到 Docker 套接字，执行热加载（.so 文件可能需要手动重启容器才能生效）")
                logger.info(f"用户 '{self.current_user.username}' 通过全量替换模式更新了弹幕源，执行热加载")
                await self.scraper_manager.load_and_sync_scrapers()
                self._log(f"用户 '{self.current_user.username}' 通过全量替换模式更新了弹幕源")
        else:
            raise ValueError("全量替换失败")

    async def _do_incremental_download(self, base_url, headers, proxy_to_use, platform_key, platform_info):
        """增量下载模式"""
        from .api.endpoints.scraper_resources import backup_scrapers, restore_scrapers

        # 下载 package.json
        package_url = f"{base_url}/package.json"
        self._log("正在获取资源包信息...")

        timeout_config = httpx.Timeout(30.0, read=30.0)
        package_data = await self._fetch_package_json(package_url, headers, proxy_to_use, timeout_config)

        if not package_data:
            raise ValueError("获取资源包信息失败")

        # 获取资源列表
        resources = package_data.get('resources', {})
        if not resources:
            raise ValueError("资源包中未找到弹幕源文件")

        total_count = len(resources)
        self._log(f"检测到 {total_count} 个弹幕源，正在比对哈希值...")

        # 比对哈希值
        scrapers_dir = _get_scrapers_dir()
        to_download, to_skip, unsupported, versions_data, hashes_data = await self._compare_hashes(
            resources, platform_key, scrapers_dir
        )

        skip_count = len(to_skip)
        need_download_count = len(to_download)
        self._log(f"比对完成: 需要下载 {need_download_count} 个，跳过 {skip_count} 个，不支持 {len(unsupported)} 个")

        self.task.progress.total = need_download_count
        self.task.progress.skipped = to_skip

        # 如果没有需要下载的文件
        if need_download_count == 0:
            self._log("所有弹幕源都是最新的，无需下载")
            self.task.status = TaskStatus.COMPLETED
            return

        # 保存 package.json
        local_package_file = scrapers_dir / "package.json"
        package_json_str = json.dumps(package_data, indent=2, ensure_ascii=False)
        await asyncio.to_thread(local_package_file.write_text, package_json_str)

        # 备份当前文件
        self._log("正在备份当前弹幕源...")
        await backup_scrapers(self.current_user)
        self._log(f"备份完成，开始下载 {need_download_count} 个文件...")

        # 下载文件
        download_timeout = httpx.Timeout(30.0, read=60.0)
        failed_downloads = []

        for index, (scraper_name, scraper_info, file_path, filename, remote_hash) in enumerate(to_download, 1):
            # 检查是否被取消
            if self.task.is_cancelled():
                self._log("任务被取消，停止下载")
                break

            self.task.progress.current = index
            self.task.progress.current_file = scraper_name
            self._log(f"正在下载 [{index}/{need_download_count}]: {scraper_name}")

            try:
                success = await self._download_single_file(
                    scraper_name, scraper_info, file_path, filename, remote_hash,
                    base_url, headers, proxy_to_use, download_timeout, scrapers_dir,
                    versions_data, hashes_data
                )
                if success:
                    self.task.progress.downloaded.append(scraper_name)
                else:
                    failed_downloads.append(scraper_name)
                    self.task.progress.failed.append(scraper_name)
            except Exception as e:
                self._log(f"下载 {scraper_name} 失败: {e}", "error")
                failed_downloads.append(scraper_name)
                self.task.progress.failed.append(scraper_name)

        download_count = len(self.task.progress.downloaded)
        self._log(f"下载完成: 成功 {download_count}/{need_download_count} 个，跳过 {skip_count} 个，失败 {len(failed_downloads)} 个")

        # 保存版本信息
        await self._save_versions(versions_data, hashes_data, platform_info, package_data, failed_downloads)

        # 检查下载结果
        if download_count == 0 and skip_count == 0:
            self._log("没有成功下载任何弹幕源，已取消重载", "error")
            await restore_scrapers(self.current_user, self.scraper_manager)
            self._log("已还原备份")
            self.task.status = TaskStatus.FAILED
            self.task.error_message = "没有成功下载任何弹幕源"
            return

        # 热加载或容器重启
        if download_count > 0:
            # 备份新下载的资源
            self._log("正在备份新下载的资源...")
            await backup_scrapers(self.current_user)
            self._log("✓ 新资源备份完成")

            # 检查是否有 Docker socket，决定重启方式
            from .docker_utils import is_docker_socket_available, restart_container
            docker_available = is_docker_socket_available()

            # 判断是否有更新已有源（需要容器重启）
            # 如果下载的文件中有任何一个是更新（而非新增），则需要容器重启
            has_updates = any(
                name in [s.name for s in self.scraper_manager.get_all_scrapers()]
                for name in self.task.progress.downloaded
            )

            if has_updates and docker_available:
                # 有更新已有源且有 Docker socket，执行容器级别重启
                from .docker_utils import get_current_container_id
                detected_id = get_current_container_id()

                self._log("⚠️ 检测到更新已有源，需要重启容器以加载新的 .so 文件")
                if detected_id:
                    self._log(f"检测到当前容器 ID: {detected_id}")
                    logger.info(f"自动检测到当前容器 ID: {detected_id}")
                else:
                    fallback_name = await self.config_manager.get("containerName", "misaka_danmu_server")
                    self._log(f"未能自动检测容器 ID，将使用兜底名称: {fallback_name}")
                    logger.info(f"未能自动检测容器 ID，将使用兜底名称: {fallback_name}")

                self._log("将在 2 秒后重启容器...")
                logger.info(f"用户 '{self.current_user.username}' 增量更新了 {download_count} 个弹幕源，即将重启容器")

                # 等待日志写入
                await asyncio.sleep(2.0)

                fallback_name = await self.config_manager.get("containerName", "misaka_danmu_server")
                result = await restart_container(fallback_name)
                if result.get("success"):
                    container_id = result.get("container_id", "unknown")
                    self._log(f"✓ 已向容器发送重启指令 (ID: {container_id})")
                    logger.info(f"已向容器发送重启指令 (ID: {container_id})")
                else:
                    self._log(f"重启容器失败: {result.get('message')}，尝试热加载")
                    logger.warning(f"重启容器失败: {result.get('message')}，尝试热加载")
                    await self.scraper_manager.load_and_sync_scrapers()
            else:
                # 只有新增源或没有 Docker socket：热加载
                if has_updates and not docker_available:
                    self._log("⚠️ 检测到更新已有源，但未检测到 Docker 套接字")
                    self._log("执行热加载（.so 文件可能需要手动重启容器才能生效）")
                else:
                    self._log("正在热加载弹幕源...")

                logger.info(f"用户 '{self.current_user.username}' 增量更新了 {download_count} 个弹幕源，正在热加载")
                await self.scraper_manager.load_and_sync_scrapers()
                self._log(f"用户 '{self.current_user.username}' 成功加载了 {download_count} 个弹幕源")

        self.task.status = TaskStatus.COMPLETED

    async def _fetch_package_json(self, package_url, headers, proxy_to_use, timeout_config):
        """获取 package.json"""
        max_retries = 3
        for retry in range(max_retries + 1):
            try:
                if retry > 0:
                    wait_time = min(2 ** retry, 8)
                    self._log(f"获取资源包信息重试 {retry}/{max_retries}，等待 {wait_time} 秒...")
                    await asyncio.sleep(wait_time)

                async with httpx.AsyncClient(timeout=timeout_config, headers=headers, follow_redirects=True, proxy=proxy_to_use) as client:
                    response = await client.get(package_url)
                    if response.status_code == 200:
                        self._log("成功获取资源包信息")
                        return response.json()
                    else:
                        self._log(f"获取资源包信息失败: HTTP {response.status_code}", "warning")
            except Exception as e:
                self._log(f"获取资源包信息异常: {e}", "warning")

        return None

    async def _compare_hashes(self, resources, platform_key, scrapers_dir):
        """比对哈希值，确定需要下载的文件"""
        to_download = []
        to_skip = []
        unsupported = []
        versions_data = {}
        hashes_data = {}

        # 读取本地 versions.json
        local_hashes = {}
        versions_file = scrapers_dir / "versions.json"
        if versions_file.exists():
            try:
                local_versions = json.loads(await asyncio.to_thread(versions_file.read_text))
                local_hashes = local_versions.get('hashes', {})
                self._log(f"已读取本地版本信息，包含 {len(local_hashes)} 个哈希值")
            except Exception as e:
                self._log(f"读取本地版本文件失败: {e}", "warning")

        for scraper_name, scraper_info in resources.items():
            files = scraper_info.get('files', {})
            file_path = files.get(platform_key)

            if not file_path:
                unsupported.append(scraper_name)
                continue

            filename = Path(file_path).name
            remote_hashes = scraper_info.get('hashes', {})
            remote_hash = remote_hashes.get(platform_key)
            local_hash = local_hashes.get(scraper_name)
            version = scraper_info.get('version', 'unknown')

            if remote_hash and local_hash and local_hash == remote_hash:
                to_skip.append(scraper_name)
                versions_data[scraper_name] = version
                hashes_data[scraper_name] = remote_hash
            else:
                to_download.append((scraper_name, scraper_info, file_path, filename, remote_hash))

        return to_download, to_skip, unsupported, versions_data, hashes_data

    async def _download_single_file(
        self, scraper_name, scraper_info, file_path, filename, remote_hash,
        base_url, headers, proxy_to_use, timeout_config, scrapers_dir,
        versions_data, hashes_data
    ):
        """下载单个文件"""
        file_url = f"{base_url}/{file_path}"
        target_path = scrapers_dir / filename
        max_retries = 3

        for retry in range(max_retries + 1):
            try:
                if retry > 0:
                    wait_time = min(2 ** (retry - 1), 10)
                    self._log(f"重试下载 {scraper_name} ({retry}/{max_retries})，等待 {wait_time} 秒...")
                    await asyncio.sleep(wait_time)

                async with httpx.AsyncClient(timeout=timeout_config, headers=headers, follow_redirects=True, proxy=proxy_to_use) as client:
                    response = await asyncio.wait_for(client.get(file_url), timeout=60.0)

                if response.status_code == 200:
                    file_content = response.content

                    # 验证哈希值
                    if remote_hash:
                        local_hash = await asyncio.to_thread(
                            lambda data: hashlib.sha256(data).hexdigest(),
                            file_content
                        )
                        if local_hash != remote_hash:
                            self._log(f"{scraper_name} 哈希验证失败", "warning")
                            if retry == max_retries:
                                return False
                            continue
                        hashes_data[scraper_name] = remote_hash

                    # 写入文件
                    await asyncio.to_thread(target_path.write_bytes, file_content)

                    version = scraper_info.get('version', 'unknown')
                    versions_data[scraper_name] = version
                    self._log(f"✓ 成功下载: {filename} (版本: {version}, 大小: {len(file_content)} 字节)")
                    return True
                else:
                    self._log(f"下载 {scraper_name} 返回 HTTP {response.status_code}", "warning")

            except (httpx.TimeoutException, asyncio.TimeoutError) as e:
                self._log(f"下载 {scraper_name} 超时", "warning")
            except Exception as e:
                self._log(f"下载 {scraper_name} 异常: {e}", "warning")

        self._log(f"✗ 下载失败: {scraper_name} (已重试 {max_retries} 次)", "error")
        return False

    async def _save_versions(self, versions_data, hashes_data, platform_info, package_data, failed_downloads):
        """保存版本信息"""
        if not versions_data:
            return

        try:
            scrapers_dir = _get_scrapers_dir()
            versions_file = scrapers_dir / "versions.json"

            # 合并旧版本信息
            existing_scrapers = {}
            existing_hashes = {}
            if failed_downloads and versions_file.exists():
                try:
                    existing_versions = json.loads(await asyncio.to_thread(versions_file.read_text))
                    existing_scrapers = existing_versions.get('scrapers', {})
                    existing_hashes = existing_versions.get('hashes', {})
                except Exception:
                    pass

            merged_scrapers = {**existing_scrapers, **versions_data}
            merged_hashes = {**existing_hashes, **hashes_data}

            full_versions_data = {
                "platform": platform_info['platform'],
                "type": platform_info['arch'],
                "version": package_data.get("version", "unknown"),
                "scrapers": merged_scrapers,
            }

            if merged_hashes:
                full_versions_data["hashes"] = merged_hashes

            versions_json_str = json.dumps(full_versions_data, indent=2, ensure_ascii=False)
            await asyncio.to_thread(versions_file.write_text, versions_json_str)
            self._log(f"已保存 {len(merged_scrapers)} 个弹幕源的版本信息")
        except Exception as e:
            self._log(f"保存版本信息失败: {e}", "warning")


async def start_download_task(
    repo_url: str,
    use_full_replace: bool,
    config_manager,
    scraper_manager,
    current_user,
) -> DownloadTask:
    """启动下载任务"""
    task_manager = get_download_task_manager()

    # 检查是否有任务正在运行
    if task_manager.is_running():
        raise ValueError("已有下载任务正在进行，请稍后再试")

    # 创建任务
    task = task_manager.create_task(repo_url, use_full_replace)

    # 创建执行器
    executor = ScraperDownloadExecutor(
        task=task,
        config_manager=config_manager,
        scraper_manager=scraper_manager,
        current_user=current_user,
    )

    # 启动后台任务
    async def run_task():
        try:
            await executor.execute()
        except asyncio.CancelledError:
            logger.info(f"任务 {task.task_id} 被取消")
        except Exception as e:
            logger.error(f"任务 {task.task_id} 执行失败: {e}", exc_info=True)

    task._asyncio_task = asyncio.create_task(run_task())
    logger.info(f"已启动下载任务: {task.task_id}")

    return task

