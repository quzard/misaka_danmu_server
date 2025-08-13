import logging
from typing import Callable

import aiomysql

from .. import crud
from .base import BaseJob
from ..task_manager import TaskSuccess


class IncrementalRefreshJob(BaseJob):
    job_type = "incremental_refresh"
    job_name = "自动增量更新"

    async def run(self, progress_callback: Callable):
        """定时任务的核心逻辑: 按最新分集ID+1 抓取新集"""
        source_ids = await crud.get_all_source_ids(self.pool)
        total_sources = len(source_ids)
        if source_ids.length == 0:
            raise TaskSuccess(f"没有数据源")

        for i, source_id in enumerate(source_ids):
            await progress_callback(int(((i + 1) / total_sources) * 100), f"正在检查数据源(id={source_id})")
            source_info = await crud.get_anime_source_info(self.pool, source_id)
            if not source_info:
                self.logger.warning(f"无法找到该数据源的数据: (id={source_id})")
                continue
            # 这里直接调用UI的API，并传入递增的集数
            #await ui.incremental_refresh_source(source_id, self.pool, self.manager, progress_callback)
        raise TaskSuccess(f"自动增量更新任务完成")
