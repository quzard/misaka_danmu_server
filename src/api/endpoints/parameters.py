"""
参数配置相关的API端点
"""
import logging
import json
import tempfile
import zipfile
import tarfile
import shutil
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import httpx

from ... import models
from ...security import get_current_user
from ...config_manager import ConfigManager
from ..dependencies import get_config_manager, get_scraper_manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_docker_environment():
    """检测是否在Docker容器中运行"""
    import os
    if Path("/.dockerenv").exists():
        return True
    if os.getenv("DOCKER_CONTAINER") == "true" or os.getenv("IN_DOCKER") == "true":
        return True
    if Path.cwd() == Path("/app"):
        return True
    return False


def _get_scrapers_dir() -> Path:
    """获取 scrapers 目录路径"""
    if _is_docker_environment():
        return Path("/app/src/scrapers")
    else:
        return Path("src/scrapers")


@router.get("/config/github-token", summary="获取GitHub Token")
async def get_github_token(
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """获取GitHub Token配置"""
    token = await config_manager.get("github_token", "")
    return {"token": token}


@router.post("/config/github-token", summary="保存GitHub Token")
async def save_github_token(
    payload: Dict[str, Any],
    current_user: models.User = Depends(get_current_user),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """保存GitHub Token配置"""
    token = payload.get("token", "")
    await config_manager.setValue("github_token", token)
    logger.info(f"用户 '{current_user.username}' 保存了GitHub Token")
    return {"message": "保存成功"}


@router.post("/config/github-token/verify", summary="验证GitHub Token")
async def verify_github_token(
    payload: Dict[str, Any],
    current_user: models.User = Depends(get_current_user)
):
    """验证GitHub Token有效性"""
    token = payload.get("token", "")
    if not token:
        raise HTTPException(status_code=400, detail="Token不能为空")
    
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        async with httpx.AsyncClient() as client:
            # 获取用户信息
            user_response = await client.get("https://api.github.com/user", headers=headers)
            if user_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Token无效")
            
            user_data = user_response.json()
            
            # 获取速率限制信息
            rate_response = await client.get("https://api.github.com/rate_limit", headers=headers)
            rate_data = rate_response.json()
            
            return {
                "valid": True,
                "username": user_data.get("login"),
                "rateLimit": {
                    "limit": rate_data["rate"]["limit"],
                    "remaining": rate_data["rate"]["remaining"],
                    "reset": rate_data["rate"]["reset"]
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证GitHub Token失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")


@router.post("/scrapers/upload-package", summary="上传弹幕源离线包")
async def upload_scraper_package(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    manager = Depends(get_scraper_manager)
):
    """上传并安装弹幕源离线包"""
    try:
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 保存上传的文件
            file_path = temp_path / file.filename
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            
            # 解压文件
            extract_dir = temp_path / "extracted"
            extract_dir.mkdir()
            
            if file.filename.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            elif file.filename.endswith(('.tar.gz', '.tgz')):
                with tarfile.open(file_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(extract_dir)
            else:
                raise HTTPException(status_code=400, detail="不支持的文件格式,仅支持 .zip 或 .tar.gz")
            
            # 验证 versions.json
            versions_file = extract_dir / "versions.json"
            if not versions_file.exists():
                raise HTTPException(status_code=400, detail="压缩包中缺少 versions.json 文件")

            with open(versions_file, 'r', encoding='utf-8') as f:
                versions_data = json.load(f)

            # 验证平台和架构
            import platform
            import sys

            current_platform = platform.system().lower()
            current_arch = platform.machine().lower()

            # 映射平台名称
            platform_map = {
                'linux': 'linux',
                'darwin': 'macos',
                'windows': 'windows'
            }

            # 映射架构名称
            arch_map = {
                'x86_64': 'x86',
                'amd64': 'x86',
                'aarch64': 'arm',
                'arm64': 'arm'
            }

            package_platform = versions_data.get('platform', '').lower()
            package_arch = versions_data.get('type', '').lower()

            expected_platform = platform_map.get(current_platform, current_platform)
            expected_arch = arch_map.get(current_arch, current_arch)

            if package_platform != expected_platform:
                raise HTTPException(
                    status_code=400,
                    detail=f"平台不匹配: 当前系统是 {expected_platform}, 压缩包是 {package_platform}"
                )

            if package_arch != expected_arch:
                raise HTTPException(
                    status_code=400,
                    detail=f"架构不匹配: 当前系统是 {expected_arch}, 压缩包是 {package_arch}"
                )

            # 备份当前弹幕源
            from .scraper_resources import backup_scrapers as backup_func
            await backup_func(current_user)
            logger.info("已备份当前弹幕源")

            # 复制文件到 scrapers 目录
            scrapers_dir = _get_scrapers_dir()
            file_count = 0

            # 复制 .so 和 .pyd 文件
            for file in extract_dir.iterdir():
                if file.is_file() and file.suffix in ['.so', '.pyd']:
                    shutil.copy2(file, scrapers_dir / file.name)
                    file_count += 1
                    logger.info(f"已复制文件: {file.name}")

            # 复制 versions.json (必需)
            versions_file = extract_dir / "versions.json"
            if versions_file.exists():
                shutil.copy2(versions_file, scrapers_dir / "versions.json")
                logger.info("已复制 versions.json")
            else:
                logger.warning("离线包中缺少 versions.json")

            # 复制 package.json (如果存在)
            package_file = extract_dir / "package.json"
            if package_file.exists():
                shutil.copy2(package_file, scrapers_dir / "package.json")
                logger.info("已复制 package.json")
            else:
                # 如果离线包中没有 package.json,从 versions.json 创建一个
                logger.info("离线包中没有 package.json,从 versions.json 创建")
                package_data = {
                    "version": versions_data.get('version', 'unknown'),
                    "platform": versions_data.get('platform', ''),
                    "type": versions_data.get('type', ''),
                    "created_from_upload": True,
                    "upload_time": datetime.now().isoformat()
                }
                package_file_path = scrapers_dir / "package.json"
                package_file_path.write_text(json.dumps(package_data, indent=2, ensure_ascii=False))
                logger.info("已创建 package.json")

            logger.info(f"用户 '{current_user.username}' 上传了离线包,共 {file_count} 个文件")

            # 先返回响应,再在后台异步重载弹幕源
            response_data = {
                "message": f"上传成功,共安装 {file_count} 个文件",
                "version": versions_data.get('version'),
                "scrapers": list(versions_data.get('scrapers', {}).keys())
            }

            # 在后台异步重载弹幕源,添加延迟避免阻塞响应
            async def reload_scrapers_background():
                try:
                    import asyncio
                    await asyncio.sleep(0.5)  # 延迟0.5秒,确保响应已发送
                    await manager.load_and_sync_scrapers()
                    logger.info("弹幕源重载完成")
                except Exception as e:
                    logger.error(f"后台重载弹幕源失败: {e}", exc_info=True)

            import asyncio
            asyncio.create_task(reload_scrapers_background())

            return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传弹幕源离线包失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")

