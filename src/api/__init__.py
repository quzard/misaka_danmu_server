from fastapi import APIRouter

from .ui_api import router as ui_router, auth_router
from .webhook_api import router as webhook_router
from .control_api import router as control_router
from .endpoints import (
    config, auth, scraper, metadata_source, media_server,
    anime, source, episode, search, import_api, task,
    token, config_extra, settings, scheduled_task, webhook, system, auth_extra
)

# This router aggregates all non-dandanplay API endpoints.
api_router = APIRouter()

# The ui_router contains core UI functionalities.
api_router.include_router(ui_router, prefix="/ui", tags=["Web UI API"], include_in_schema=False)
api_router.include_router(auth_router, prefix="/ui/auth", tags=["Auth"], include_in_schema=False)

# 基础端点: Config, Auth, Scraper, Metadata Source, Media Server
api_router.include_router(config.router, prefix="/ui", tags=["Config"], include_in_schema=False)
api_router.include_router(auth.router, prefix="/ui/auth", tags=["Auth"], include_in_schema=False)
api_router.include_router(scraper.router, prefix="/ui", tags=["Scraper"], include_in_schema=False)
api_router.include_router(metadata_source.router, prefix="/ui", tags=["Metadata Source"], include_in_schema=False)
api_router.include_router(media_server.router, prefix="/ui", tags=["Media Server"], include_in_schema=False)

# 新增的模块化端点 - 第1批: Anime, Source, Episode
api_router.include_router(anime.router, prefix="/ui", tags=["Anime"], include_in_schema=False)
api_router.include_router(source.router, prefix="/ui", tags=["Source"], include_in_schema=False)
api_router.include_router(episode.router, prefix="/ui", tags=["Episode"], include_in_schema=False)

# 新增的模块化端点 - 第2批: Search, Import, Task
api_router.include_router(search.router, prefix="/ui", tags=["Search"], include_in_schema=False)
api_router.include_router(import_api.router, prefix="/ui", tags=["Import"], include_in_schema=False)
api_router.include_router(task.router, prefix="/ui", tags=["Task"], include_in_schema=False)

# 新增的模块化端点 - 第3批: Token, Config, Settings, ScheduledTask, Webhook, System, Auth
api_router.include_router(token.router, prefix="/ui", tags=["Token"], include_in_schema=False)
api_router.include_router(config_extra.router, prefix="/ui", tags=["Config"], include_in_schema=False)
api_router.include_router(settings.router, prefix="/ui", tags=["Settings"], include_in_schema=False)
api_router.include_router(scheduled_task.router, prefix="/ui", tags=["ScheduledTask"], include_in_schema=False)
api_router.include_router(webhook.router, prefix="/ui", tags=["Webhook"], include_in_schema=False)
api_router.include_router(system.router, prefix="/ui", tags=["System"], include_in_schema=False)
api_router.include_router(auth_extra.auth_router, prefix="/ui/auth", tags=["Auth"], include_in_schema=False)

api_router.include_router(webhook_router, prefix="/webhook", tags=["Webhook"], include_in_schema=False)

# 注意：dandan_router 在 main.py 中被单独处理，因为它的路径结构
# (/api/v1/{token}) 与其他嵌套在 /api 前缀下的路由 (例如 /api/ui, /api/tmdb) 不同，
# 需要位于 /api 前缀的根部。