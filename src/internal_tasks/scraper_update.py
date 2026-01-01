"""
弹幕源资源自动更新处理器

用于后台自动检查并更新弹幕源资源。
"""
import json
import asyncio
import logging
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any

import httpx
from fastapi import FastAPI

# 复用 scraper_resources 中的工具函数
from ..api.endpoints.scraper_resources import (
    parse_github_url,
    _build_base_url,
    get_platform_key,
    get_platform_info,
    _get_scrapers_dir,
    SCRAPERS_VERSIONS_FILE,
    SCRAPERS_PACKAGE_FILE,
    _download_lock,
    backup_scrapers,
    _fetch_github_release_asset,
    _download_and_extract_release,
)

logger = logging.getLogger("ScraperAutoUpdate")


class SystemUser:
    """用于自动更新时的虚拟用户对象"""
    username = "system_auto_update"


async def scraper_auto_update_handler(app: FastAPI) -> None:
    """
    弹幕源自动更新处理器

    检查是否有新版本，如果有则自动下载更新。
    """
    config_manager = app.state.config_manager
    scraper_manager = app.state.scraper_manager

    # 获取资源仓库URL
    repo_url = await config_manager.get("scraper_resource_repo", "")
    if not repo_url:
        logger.debug("未配置资源仓库URL，跳过自动更新")
        return

    logger.info("开始检查弹幕源更新...")

    # 获取本地版本
    local_version = await _get_local_version()

    # 获取代理配置
    proxy_to_use = await _get_proxy_config(config_manager)

    # 解析仓库URL并获取headers
    headers, repo_info = await _get_repo_headers(config_manager, repo_url)
    base_url = _build_base_url(repo_info, repo_url)

    # 获取远程版本和包数据
    package_data = await _fetch_remote_package(base_url, headers, proxy_to_use)
    if not package_data:
        logger.debug("无法获取远程版本信息，跳过更新")
        return

    remote_version = package_data.get("version")
    if not remote_version:
        logger.debug("远程 package.json 中没有版本号")
        return

    # 比较版本
    if local_version == remote_version:
        logger.debug(f"弹幕源已是最新版本 ({local_version})")
        return

    logger.info(f"检测到新版本: {local_version} -> {remote_version}，开始自动更新...")

    # 执行更新
    await _perform_update(
        app=app,
        package_data=package_data,
        base_url=base_url,
        headers=headers,
        proxy_to_use=proxy_to_use,
        local_version=local_version,
        remote_version=remote_version,
        repo_info=repo_info
    )


async def _get_local_version() -> str:
    """获取本地版本号"""
    local_package_file = _get_scrapers_dir() / "package.json"
    if local_package_file.exists():
        try:
            local_package = json.loads(await asyncio.to_thread(local_package_file.read_text))
            return local_package.get("version", "unknown")
        except Exception as e:
            logger.warning(f"读取本地 package.json 失败: {e}")
    return "unknown"


async def _get_proxy_config(config_manager) -> Optional[str]:
    """获取代理配置"""
    proxy_url = await config_manager.get("proxyUrl", "")
    proxy_enabled_str = await config_manager.get("proxyEnabled", "false")
    proxy_enabled = proxy_enabled_str.lower() == 'true'
    return proxy_url if proxy_enabled and proxy_url else None


async def _get_repo_headers(config_manager, repo_url: str) -> tuple:
    """获取仓库请求头和解析信息"""
    headers = {}
    repo_info = None
    try:
        repo_info = parse_github_url(repo_url)
    except ValueError:
        pass

    if repo_info:
        github_token = await config_manager.get("github_token", "")
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

    return headers, repo_info


async def _fetch_remote_package(base_url: str, headers: Dict, proxy: Optional[str]) -> Optional[Dict]:
    """获取远程 package.json"""
    package_url = f"{base_url}/package.json"
    timeout = httpx.Timeout(5.0, read=15.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True, proxy=proxy) as client:
            response = await client.get(package_url)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"获取远程 package.json 失败: HTTP {response.status_code}")
    except Exception as e:
        logger.warning(f"获取远程版本失败: {e}")

    return None


async def _perform_update(
    app: FastAPI,
    package_data: Dict[str, Any],
    base_url: str,
    headers: Dict,
    proxy_to_use: Optional[str],
    local_version: str,
    remote_version: str,
    repo_info: Optional[Dict] = None
) -> None:
    """执行实际的更新操作"""
    config_manager = app.state.config_manager
    scraper_manager = app.state.scraper_manager

    # 检查下载锁
    if _download_lock.locked():
        logger.info("另一个下载任务正在进行中，跳过本次更新")
        return

    async with _download_lock:
        # 备份当前文件
        try:
            await backup_scrapers(SystemUser())
            logger.info("备份当前弹幕源成功")
        except Exception as e:
            logger.error(f"备份失败，取消更新: {e}")
            return

        # 获取平台信息
        platform_key = get_platform_key()
        platform_info = get_platform_info()
        scrapers_dir = _get_scrapers_dir()

        # 检查是否启用全量替换模式
        full_replace_enabled = await config_manager.get("scraperFullReplaceEnabled", "false")
        use_full_replace = full_replace_enabled.lower() == "true"

        # ========== 全量替换模式 ==========
        if use_full_replace and repo_info:
            logger.info("使用全量替换模式，从 GitHub Releases 下载压缩包")

            asset_info = await _fetch_github_release_asset(
                repo_info=repo_info,
                platform_key=platform_key,
                headers=headers,
                proxy=proxy_to_use
            )

            if asset_info:
                success = await _download_and_extract_release(
                    asset_info=asset_info,
                    scrapers_dir=scrapers_dir,
                    headers=headers,
                    proxy=proxy_to_use
                )

                if success:
                    # 更新 versions.json
                    from datetime import datetime
                    release_version = asset_info['version'].lstrip('v')
                    versions_data = {
                        "platform": platform_info['platform'],
                        "type": platform_info['arch'],
                        "version": release_version,
                        "scrapers": {},
                        "hashes": {},
                        "full_replace": True,
                        "update_time": datetime.now().isoformat()
                    }
                    versions_json_str = json.dumps(versions_data, indent=2, ensure_ascii=False)
                    await asyncio.to_thread(SCRAPERS_VERSIONS_FILE.write_text, versions_json_str)

                    # 同时更新 package.json 的版本号（前端从这里读取版本）
                    local_package_file = scrapers_dir / "package.json"
                    try:
                        if local_package_file.exists():
                            package_content = json.loads(await asyncio.to_thread(local_package_file.read_text))
                            package_content['version'] = release_version
                        else:
                            package_content = {"version": release_version}
                        package_json_str = json.dumps(package_content, indent=2, ensure_ascii=False)
                        await asyncio.to_thread(local_package_file.write_text, package_json_str)
                        logger.info(f"已更新 package.json 版本号为: {release_version}")
                    except Exception as pkg_err:
                        logger.warning(f"更新 package.json 失败: {pkg_err}")

                    # 重载弹幕源
                    try:
                        await scraper_manager.load_and_sync_scrapers()
                        logger.info(f"弹幕源全量替换完成: {local_version} -> {release_version}")
                        logger.warning("⚠️ 全量替换完成，建议重启服务以确保 .so 文件更新生效")

                        # 清除版本缓存
                        import src.api.endpoints.scraper_resources as sr
                        sr._version_cache = None
                        sr._version_cache_time = None
                    except Exception as e:
                        logger.error(f"重载弹幕源失败: {e}")
                    return
                else:
                    logger.warning("全量替换失败，回退到逐文件下载模式")
            else:
                logger.warning("未找到匹配的 Release 压缩包，回退到逐文件下载模式")

        # ========== 逐文件下载模式（默认）==========
        # 获取资源列表
        resources = package_data.get('resources', {})
        if not resources:
            logger.warning("资源包中未找到弹幕源文件")
            return

        total_count = len(resources)
        download_count = 0
        skip_count = 0
        failed_downloads = []
        versions_data = {}
        hashes_data = {}

        # 保存 package.json
        local_package_file = scrapers_dir / "package.json"
        package_json_str = json.dumps(package_data, indent=2, ensure_ascii=False)
        await asyncio.to_thread(local_package_file.write_text, package_json_str)

        # 下载文件
        download_timeout = httpx.Timeout(3.0, read=15.0)
        async with httpx.AsyncClient(timeout=download_timeout, headers=headers, follow_redirects=True, proxy=proxy_to_use) as client:
            for scraper_name, scraper_info in resources.items():
                result = await _download_single_scraper(
                    client=client,
                    scraper_name=scraper_name,
                    scraper_info=scraper_info,
                    platform_key=platform_key,
                    base_url=base_url,
                    scrapers_dir=scrapers_dir,
                    versions_data=versions_data,
                    hashes_data=hashes_data
                )

                if result == "downloaded":
                    download_count += 1
                elif result == "skipped":
                    skip_count += 1
                elif result == "failed":
                    failed_downloads.append(scraper_name)

        # 保存版本信息
        await _save_versions(versions_data, hashes_data, platform_info, package_data, failed_downloads)

        # 重载弹幕源
        try:
            await scraper_manager.load_and_sync_scrapers()
            logger.info(f"弹幕源自动更新完成: {local_version} -> {remote_version} (下载: {download_count}, 跳过: {skip_count}, 失败: {len(failed_downloads)})")

            # 清除版本缓存
            import src.api.endpoints.scraper_resources as sr
            sr._version_cache = None
            sr._version_cache_time = None
        except Exception as e:
            logger.error(f"重载弹幕源失败: {e}")



async def _download_single_scraper(
    client: httpx.AsyncClient,
    scraper_name: str,
    scraper_info: Dict,
    platform_key: str,
    base_url: str,
    scrapers_dir: Path,
    versions_data: Dict,
    hashes_data: Dict
) -> str:
    """
    下载单个弹幕源文件

    Returns:
        "downloaded" - 下载成功
        "skipped" - 跳过（哈希值相同）
        "failed" - 下载失败
    """
    try:
        # 获取当前平台的文件路径
        files = scraper_info.get('files', {})
        file_path = files.get(platform_key)

        if not file_path:
            return "failed"

        filename = Path(file_path).name
        target_path = scrapers_dir / filename

        # 获取远程文件的哈希值
        remote_hashes = scraper_info.get('hashes', {})
        remote_hash = remote_hashes.get(platform_key)

        # 检查是否需要下载
        if remote_hash and SCRAPERS_VERSIONS_FILE.exists():
            try:
                local_versions = json.loads(await asyncio.to_thread(SCRAPERS_VERSIONS_FILE.read_text))
                local_hash = local_versions.get('hashes', {}).get(scraper_name)
                if local_hash and local_hash == remote_hash:
                    versions_data[scraper_name] = scraper_info.get('version', 'unknown')
                    hashes_data[scraper_name] = remote_hash
                    return "skipped"
            except Exception:
                pass

        # 下载文件
        file_url = f"{base_url}/{file_path}"
        max_retries = 3

        for retry in range(max_retries):
            try:
                response = await asyncio.wait_for(client.get(file_url), timeout=18.0)
                if response.status_code == 200:
                    file_content = response.content

                    # 让出控制权
                    await asyncio.sleep(0)

                    # 验证哈希值（异步方式，防止阻塞事件循环）
                    if remote_hash:
                        # 将哈希计算放到线程池中执行
                        local_hash = await asyncio.to_thread(
                            lambda data: hashlib.sha256(data).hexdigest(),
                            file_content
                        )
                        if local_hash != remote_hash:
                            logger.warning(f"\t哈希验证失败 {scraper_name} (重试 {retry + 1}/{max_retries})")
                            if retry == max_retries - 1:
                                return "failed"
                            await asyncio.sleep(0)
                            continue
                        hashes_data[scraper_name] = remote_hash
                        logger.debug(f"\t哈希验证通过: {scraper_name}")

                    # 写入文件（异步方式）
                    logger.debug(f"\t写入文件: {scraper_name} ({len(file_content)} 字节)")
                    await asyncio.to_thread(target_path.write_bytes, file_content)

                    versions_data[scraper_name] = scraper_info.get('version', 'unknown')
                    logger.debug(f"✓ 成功下载: {scraper_name}")

                    # 让出控制权
                    await asyncio.sleep(0)
                    return "downloaded"
                elif retry == max_retries - 1:
                    logger.warning(f"\t下载失败 {scraper_name}: HTTP {response.status_code}")
                    return "failed"
                # 让出控制权
                await asyncio.sleep(0)
            except Exception as e:
                if retry == max_retries - 1:
                    logger.warning(f"下载 {scraper_name} 失败: {e}", exc_info=True)
                    return "failed"
                # 重试前让出控制权
                await asyncio.sleep(0.5)

        return "failed"
    except Exception as e:
        logger.error(f"处理 {scraper_name} 时出错: {e}")
        return "failed"


async def _save_versions(
    versions_data: Dict,
    hashes_data: Dict,
    platform_info: Dict,
    package_data: Dict,
    failed_downloads: list
) -> None:
    """保存版本信息"""
    if not versions_data:
        return

    try:
        # 如果有下载失败的文件，合并旧版本信息
        existing_scrapers = {}
        existing_hashes = {}
        if failed_downloads and SCRAPERS_VERSIONS_FILE.exists():
            try:
                existing_versions = json.loads(await asyncio.to_thread(SCRAPERS_VERSIONS_FILE.read_text))
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
            "scrapers": merged_scrapers
        }

        if merged_hashes:
            full_versions_data["hashes"] = merged_hashes

        versions_json_str = json.dumps(full_versions_data, indent=2, ensure_ascii=False)
        await asyncio.to_thread(SCRAPERS_VERSIONS_FILE.write_text, versions_json_str)
        logger.debug(f"已保存 {len(merged_scrapers)} 个弹幕源的版本信息")
    except Exception as e:
        logger.warning(f"保存版本信息失败: {e}")

