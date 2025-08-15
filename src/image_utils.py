import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 图片存储在 config/image/ 目录下
IMAGE_DIR = Path(__file__).parent.parent / "config" / "image"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)


async def download_image(image_url: Optional[str]) -> Optional[str]:
    """
    从给定的URL下载图片，保存到本地，并返回其相对Web路径。

    :param image_url: 要下载的图片的URL。
    :return: 成功则返回图片的Web可访问路径 (e.g., /images/xxxx.jpg)，失败则返回 None。
    """
    if not image_url:
        return None

    # 修正：确保URL以http开头
    if image_url.startswith('//'):
        image_url = 'https:' + image_url

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(image_url, headers={"Referer": "https://www.bilibili.com"})
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            extension = ".jpg"  # 默认扩展名
            if "jpeg" in content_type: extension = ".jpg"
            elif "png" in content_type: extension = ".png"
            elif "webp" in content_type: extension = ".webp"

            filename = f"{uuid.uuid4()}{extension}"
            save_path = IMAGE_DIR / filename
            save_path.write_bytes(response.content)
            logger.info(f"图片已成功缓存到: {save_path}")
            return f"/images/{filename}"  # 返回Web可访问的相对路径
    except Exception as e:
        logger.error(f"下载图片失败 (URL: {image_url}): {e}", exc_info=True)
        return None

