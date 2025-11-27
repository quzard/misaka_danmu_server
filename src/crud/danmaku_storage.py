"""
弹幕存储管理相关的CRUD操作
包括批量迁移、重命名、模板转换
"""

import logging
import shutil
import re
from pathlib import Path
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ..orm_models import Anime, AnimeSource, Episode
from ..config import settings

logger = logging.getLogger(__name__)

# 弹幕文件基础目录
DANMAKU_BASE_DIR = Path(settings.config_path) / "danmaku"


def get_fs_path_from_web_path(web_path: str) -> Optional[Path]:
    """将web路径转换为文件系统路径"""
    if not web_path:
        return None
    # web_path 格式: /app/config/danmaku/xxx/yyy.xml
    # 实际路径: {config_path}/danmaku/xxx/yyy.xml
    if web_path.startswith("/app/config/"):
        relative_path = web_path[len("/app/config/"):]
        return Path(settings.config_path) / relative_path
    return None


async def get_episodes_for_anime(session: AsyncSession, anime_id: int) -> List[Episode]:
    """获取anime的所有episodes"""
    stmt = (
        select(Episode)
        .join(AnimeSource, Episode.sourceId == AnimeSource.id)
        .where(AnimeSource.animeId == anime_id)
        .options(selectinload(Episode.source).selectinload(AnimeSource.anime))
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def batch_migrate_danmaku(
    session: AsyncSession,
    anime_ids: List[int],
    target_path: str,
    keep_structure: bool = True,
    conflict_action: str = "skip"
) -> Dict[str, Any]:
    """批量迁移弹幕文件到新目录"""
    results = {
        "success": True, 
        "totalCount": 0, 
        "successCount": 0, 
        "failedCount": 0, 
        "skippedCount": 0, 
        "details": []
    }
    
    target_base = Path(target_path.replace("/app/config/", str(settings.config_path) + "/"))
    target_base.mkdir(parents=True, exist_ok=True)
    
    for anime_id in anime_ids:
        episodes = await get_episodes_for_anime(session, anime_id)
        
        for episode in episodes:
            results["totalCount"] += 1
            
            if not episode.danmakuFilePath:
                results["skippedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id, 
                    "status": "skipped", 
                    "reason": "无弹幕文件"
                })
                continue
            
            old_path = get_fs_path_from_web_path(episode.danmakuFilePath)
            if not old_path or not old_path.exists():
                results["skippedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id, 
                    "status": "skipped", 
                    "reason": "文件不存在"
                })
                continue
            
            # 计算新路径
            if keep_structure:
                try:
                    relative = old_path.relative_to(DANMAKU_BASE_DIR)
                except ValueError:
                    relative = old_path.name
                new_path = target_base / relative
            else:
                new_path = target_base / old_path.name
            
            # 处理冲突
            if new_path.exists():
                if conflict_action == "skip":
                    results["skippedCount"] += 1
                    results["details"].append({
                        "episodeId": episode.id, 
                        "status": "skipped", 
                        "reason": "目标文件已存在"
                    })
                    continue
                elif conflict_action == "rename":
                    stem, suffix = new_path.stem, new_path.suffix
                    counter = 1
                    while new_path.exists():
                        new_path = new_path.parent / f"{stem}_{counter}{suffix}"
                        counter += 1
            
            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(new_path))
                
                # 更新数据库路径
                new_web_path = "/app/config/" + str(new_path.relative_to(Path(settings.config_path)))
                await session.execute(
                    update(Episode).where(Episode.id == episode.id).values(danmakuFilePath=new_web_path)
                )
                
                results["successCount"] += 1
                results["details"].append({
                    "episodeId": episode.id, 
                    "status": "success", 
                    "newPath": new_web_path
                })
            except Exception as e:
                logger.error(f"迁移文件失败: {e}")
                results["failedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id, 
                    "status": "failed", 
                    "reason": str(e)
                })
    
    await session.commit()
    results["success"] = results["failedCount"] == 0
    return results


async def batch_rename_danmaku(
    session: AsyncSession,
    anime_ids: List[int],
    mode: str,
    prefix: str = "",
    suffix: str = "",
    regex_pattern: str = "",
    regex_replace: str = ""
) -> Dict[str, Any]:
    """批量重命名弹幕文件"""
    results = {
        "success": True,
        "totalCount": 0,
        "successCount": 0,
        "failedCount": 0,
        "skippedCount": 0,
        "details": []
    }

    for anime_id in anime_ids:
        episodes = await get_episodes_for_anime(session, anime_id)

        for episode in episodes:
            results["totalCount"] += 1

            if not episode.danmakuFilePath:
                results["skippedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "skipped",
                    "reason": "无弹幕文件"
                })
                continue

            old_path = get_fs_path_from_web_path(episode.danmakuFilePath)
            if not old_path or not old_path.exists():
                results["skippedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "skipped",
                    "reason": "文件不存在"
                })
                continue

            old_name = old_path.stem
            extension = old_path.suffix

            # 计算新文件名
            if mode == "prefix":
                new_name = f"{prefix}{old_name}{suffix}{extension}"
            elif mode == "regex":
                try:
                    new_name = re.sub(regex_pattern, regex_replace, old_name) + extension
                except re.error as e:
                    results["failedCount"] += 1
                    results["details"].append({
                        "episodeId": episode.id,
                        "status": "failed",
                        "reason": f"正则表达式错误: {e}"
                    })
                    continue
            else:
                new_name = old_name + extension

            new_path = old_path.parent / new_name

            # 如果新旧路径相同，跳过
            if new_path == old_path:
                results["skippedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "skipped",
                    "reason": "文件名未变化"
                })
                continue

            # 处理冲突
            if new_path.exists():
                stem, suffix_ext = new_path.stem, new_path.suffix
                counter = 1
                while new_path.exists():
                    new_path = new_path.parent / f"{stem}_{counter}{suffix_ext}"
                    counter += 1

            try:
                old_path.rename(new_path)

                # 更新数据库路径
                new_web_path = "/app/config/" + str(new_path.relative_to(Path(settings.config_path)))
                await session.execute(
                    update(Episode).where(Episode.id == episode.id).values(danmakuFilePath=new_web_path)
                )

                results["successCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "success",
                    "oldName": old_path.name,
                    "newName": new_path.name
                })
            except Exception as e:
                logger.error(f"重命名文件失败: {e}")
                results["failedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "failed",
                    "reason": str(e)
                })

    await session.commit()
    results["success"] = results["failedCount"] == 0
    return results


async def apply_danmaku_template(
    session: AsyncSession,
    anime_ids: List[int],
    template_type: str,
    config_manager = None
) -> Dict[str, Any]:
    """按新的存储模板重新组织弹幕文件"""
    results = {
        "success": True,
        "totalCount": 0,
        "successCount": 0,
        "failedCount": 0,
        "skippedCount": 0,
        "details": []
    }

    # 根据模板类型确定目标目录和命名模板
    if template_type == "tv":
        base_dir = "/app/config/danmaku/tv"
        template = "${title}/Season ${season}/${title} - S${season}E${episode}"
        if config_manager:
            base_dir = await config_manager.get('tvDanmakuDirectoryPath', base_dir)
            template = await config_manager.get('tvDanmakuFilenameTemplate', template)
    elif template_type == "movie":
        base_dir = "/app/config/danmaku/movies"
        template = "${title}/${title}"
        if config_manager:
            base_dir = await config_manager.get('movieDanmakuDirectoryPath', base_dir)
            template = await config_manager.get('movieDanmakuFilenameTemplate', template)
    else:  # id
        base_dir = "/app/config/danmaku"
        template = "${animeId}/${episodeId}"

    # 转换base_dir为实际路径
    if base_dir.startswith("/app/config/"):
        base_path = Path(settings.config_path) / base_dir[len("/app/config/"):]
    else:
        base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    for anime_id in anime_ids:
        episodes = await get_episodes_for_anime(session, anime_id)
        if not episodes:
            continue

        anime = episodes[0].source.anime

        for episode in episodes:
            results["totalCount"] += 1

            if not episode.danmakuFilePath:
                results["skippedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "skipped",
                    "reason": "无弹幕文件"
                })
                continue

            old_path = get_fs_path_from_web_path(episode.danmakuFilePath)
            if not old_path or not old_path.exists():
                results["skippedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "skipped",
                    "reason": "文件不存在"
                })
                continue

            # 构建新路径
            try:
                relative_path = template.replace("${title}", anime.title or "Unknown")
                relative_path = relative_path.replace("${season}", str(anime.season or 1).zfill(2))
                relative_path = relative_path.replace("${episode}", str(episode.episodeIndex or 1).zfill(2))
                relative_path = relative_path.replace("${animeId}", str(anime.id))
                relative_path = relative_path.replace("${episodeId}", str(episode.id))

                # 清理非法字符
                relative_path = re.sub(r'[<>:"|?*]', '_', relative_path)

                new_path = base_path / f"{relative_path}.xml"

                # 如果新旧路径相同，跳过
                if new_path == old_path:
                    results["skippedCount"] += 1
                    results["details"].append({
                        "episodeId": episode.id,
                        "status": "skipped",
                        "reason": "路径未变化"
                    })
                    continue

                # 处理冲突
                if new_path.exists():
                    stem, suffix = new_path.stem, new_path.suffix
                    counter = 1
                    while new_path.exists():
                        new_path = new_path.parent / f"{stem}_{counter}{suffix}"
                        counter += 1

                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(new_path))

                # 更新数据库路径
                new_web_path = "/app/config/" + str(new_path.relative_to(Path(settings.config_path)))
                await session.execute(
                    update(Episode).where(Episode.id == episode.id).values(danmakuFilePath=new_web_path)
                )

                results["successCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "success",
                    "oldPath": episode.danmakuFilePath,
                    "newPath": new_web_path
                })
            except Exception as e:
                logger.error(f"应用模板失败: {e}")
                results["failedCount"] += 1
                results["details"].append({
                    "episodeId": episode.id,
                    "status": "failed",
                    "reason": str(e)
                })

    await session.commit()
    results["success"] = results["failedCount"] == 0
    return results

