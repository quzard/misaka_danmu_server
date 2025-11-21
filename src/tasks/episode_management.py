"""分集管理任务模块"""
import logging
from typing import Callable, List
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import crud, orm_models
from ..task_manager import TaskSuccess
from ..crud import _get_fs_path_from_web_path

logger = logging.getLogger(__name__)


async def reorder_episodes_task(sourceId: int, session: AsyncSession, progress_callback: Callable):
    """后台任务：重新编号一个源的所有分集，并同步更新其ID和物理文件。"""
    logger.info(f"开始重整源 ID: {sourceId} 的分集顺序。")
    await progress_callback(0, "正在获取分集列表...")

    dialect_name = session.bind.dialect.name
    is_mysql = dialect_name == 'mysql'
    is_postgres = dialect_name == 'postgresql'

    try:
        # 根据数据库方言，暂时禁用外键检查
        if is_mysql:
            try:
                await session.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
                # MySQL需要提交SET命令
                await session.commit()
            except Exception as e:
                logger.warning(f"无法禁用MySQL外键检查: {e}")
        elif is_postgres:
            # PostgreSQL的session_replication_role必须在同一事务中使用
            # 不要在这里提交,保持在同一事务中
            try:
                await session.execute(text("SET session_replication_role = 'replica';"))
            except Exception as e:
                logger.error(f"❌ PostgreSQL权限不足: 无法设置 session_replication_role")
                logger.error(f"📝 解决方法:")
                logger.error(f"   1. 授予数据库用户超级用户权限:")
                logger.error(f"      ALTER USER your_username WITH SUPERUSER;")
                logger.error(f"   2. 或者使用超级用户账户连接数据库")
                logger.error(f"   3. 注意: 超级用户权限仅建议在开发/测试环境使用")
                raise

        try:
            # 1. 获取计算新ID所需的信息
            source_info = await crud.get_anime_source_info(session, sourceId)
            if not source_info:
                raise ValueError(f"找不到源ID {sourceId} 的信息。")
            anime_id = source_info['animeId']
            source_order = source_info.get('sourceOrder')

            if source_order is None:
                # 如果由于某种原因（例如，非常旧的数据）没有 sourceOrder，则不允许重整
                raise ValueError(f"源 ID {sourceId} 没有持久化的 sourceOrder，无法重整。请尝试重新添加此源。")

            # 2. 获取所有分集ORM对象，按现有顺序排序
            episodes_orm_res = await session.execute(
                select(orm_models.Episode)
                .where(orm_models.Episode.sourceId == sourceId)
                .order_by(orm_models.Episode.episodeIndex, orm_models.Episode.id)
            )
            episodes_to_migrate = episodes_orm_res.scalars().all()

            if not episodes_to_migrate:
                raise TaskSuccess("没有找到分集，无需重整。")

            await progress_callback(10, "正在计算新的分集编号...")

            old_episodes_to_delete = []
            new_episodes_to_add = []

            for i, old_ep in enumerate(episodes_to_migrate):
                new_index = i + 1
                new_id = int(f"25{anime_id:06d}{source_order:02d}{new_index:04d}")

                if old_ep.id == new_id and old_ep.episodeIndex == new_index:
                    continue

                # 修正：使用正确的Web路径格式，并使用辅助函数进行文件路径转换
                new_danmaku_web_path = f"/app/config/danmaku/{anime_id}/{new_id}.xml" if old_ep.danmakuFilePath else None
                if old_ep.danmakuFilePath:
                    old_full_path = _get_fs_path_from_web_path(old_ep.danmakuFilePath)
                    new_full_path = _get_fs_path_from_web_path(new_danmaku_web_path)
                    if old_full_path.is_file() and old_full_path != new_full_path:
                        new_full_path.parent.mkdir(parents=True, exist_ok=True)
                        old_full_path.rename(new_full_path)

                new_episodes_to_add.append(orm_models.Episode(id=new_id, sourceId=old_ep.sourceId, episodeIndex=new_index, title=old_ep.title, sourceUrl=old_ep.sourceUrl, providerEpisodeId=old_ep.providerEpisodeId, fetchedAt=old_ep.fetchedAt, commentCount=old_ep.commentCount, danmakuFilePath=new_danmaku_web_path))
                old_episodes_to_delete.append(old_ep)

            if not old_episodes_to_delete:
                raise TaskSuccess("所有分集顺序和ID都正确，无需重整。")

            await progress_callback(30, f"准备迁移 {len(old_episodes_to_delete)} 个分集...")

            for old_ep in old_episodes_to_delete:
                await session.delete(old_ep)
            await session.flush()
            session.add_all(new_episodes_to_add)

            await session.commit()
            raise TaskSuccess(f"重整完成，共迁移了 {len(new_episodes_to_add)} 个分集的记录。")
        except TaskSuccess:
            # TaskSuccess 不是错误，直接向上传递
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"重整分集任务 (源ID: {sourceId}) 事务中失败: {e}", exc_info=True)
            raise
        finally:
            # 务必重新启用外键检查/恢复会话角色
            if is_mysql:
                try:
                    await session.execute(text("SET FOREIGN_KEY_CHECKS=1;"))
                    await session.commit()
                except Exception as e:
                    logger.warning(f"无法恢复MySQL外键检查: {e}")
            elif is_postgres:
                try:
                    await session.execute(text("SET session_replication_role = 'origin';"))
                    await session.commit()
                except Exception as e:
                    logger.warning(f"无法恢复PostgreSQL会话角色: {e}")
    except Exception as e:
        logger.error(f"重整分集任务 (源ID: {sourceId}) 失败: {e}", exc_info=True)
        raise


async def offset_episodes_task(episode_ids: List[int], offset: int, session: AsyncSession, progress_callback: Callable):
    """后台任务：对选中的分集进行集数偏移，并同步更新其ID和物理文件。"""
    if not episode_ids:
        raise TaskSuccess("没有选中任何分集。")

    logger.info(f"开始集数偏移任务，偏移量: {offset}, 分集IDs: {episode_ids}")
    await progress_callback(0, "正在验证偏移操作...")

    dialect_name = session.bind.dialect.name
    is_mysql = dialect_name == 'mysql'
    is_postgres = dialect_name == 'postgresql'

    try:
        # --- Execution Phase ---
        # Temporarily disable foreign key checks
        if is_mysql:
            try:
                await session.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
                # MySQL需要提交SET命令
                await session.commit()
            except Exception as e:
                logger.warning(f"无法禁用MySQL外键检查: {e}")
        elif is_postgres:
            # PostgreSQL的session_replication_role必须在同一事务中使用
            # 不要在这里提交,保持在同一事务中
            try:
                await session.execute(text("SET session_replication_role = 'replica';"))
            except Exception as e:
                logger.error(f"❌ PostgreSQL权限不足: 无法设置 session_replication_role")
                logger.error(f"📝 解决方法:")
                logger.error(f"   1. 授予数据库用户超级用户权限:")
                logger.error(f"      ALTER USER your_username WITH SUPERUSER;")
                logger.error(f"   2. 或者使用超级用户账户连接数据库")
                logger.error(f"   3. 注意: 超级用户权限仅建议在开发/测试环境使用")
                raise
        # --- Validation Phase ---
        # 1. Fetch all selected episodes and ensure they belong to the same source
        selected_episodes_res = await session.execute(
            select(orm_models.Episode)
            .where(orm_models.Episode.id.in_(episode_ids))
            .options(selectinload(orm_models.Episode.source))
        )
        selected_episodes = selected_episodes_res.scalars().all()

        if len(selected_episodes) != len(set(episode_ids)):
            raise ValueError("部分选中的分集未找到。")

        first_ep = selected_episodes[0]
        source_id = first_ep.sourceId
        anime_id = first_ep.source.animeId
        source_order = first_ep.source.sourceOrder

        if any(ep.sourceId != source_id for ep in selected_episodes):
            raise ValueError("选中的分集必须属于同一个数据源。")

        if source_order is None:
            raise ValueError(f"源 ID {source_id} 没有持久化的 sourceOrder，无法进行偏移操作。")

        # 2. Check for conflicts
        selected_indices = {ep.episodeIndex for ep in selected_episodes}
        new_indices = {idx + offset for idx in selected_indices}

        if any(idx <= 0 for idx in new_indices):
            # 此检查作为最后的安全防线，API层应已进行初步验证
            raise ValueError("偏移后的集数必须大于0。")

        all_source_episodes_res = await session.execute(
            select(orm_models.Episode.episodeIndex).where(orm_models.Episode.sourceId == source_id)
        )
        all_existing_indices = set(all_source_episodes_res.scalars().all())
        unselected_indices = all_existing_indices - selected_indices

        conflicts = new_indices.intersection(unselected_indices)
        if conflicts:
            raise ValueError(f"操作将导致集数冲突，无法执行。冲突集数: {sorted(list(conflicts))}")

        await progress_callback(20, "验证通过，准备迁移数据...")

        # --- Execution Phase ---
        try:
            old_episodes_to_delete = []
            new_episodes_to_add = []

            total_to_migrate = len(selected_episodes)
            for i, old_ep in enumerate(selected_episodes):
                await progress_callback(20 + int((i / total_to_migrate) * 70), f"正在处理分集 {i+1}/{total_to_migrate}...")

                new_index = old_ep.episodeIndex + offset
                new_id = int(f"25{anime_id:06d}{source_order:02d}{new_index:04d}")

                new_danmaku_web_path = None
                if old_ep.danmakuFilePath:
                    new_danmaku_web_path = f"/app/config/danmaku/{anime_id}/{new_id}.xml"
                    old_full_path = _get_fs_path_from_web_path(old_ep.danmakuFilePath)
                    new_full_path = _get_fs_path_from_web_path(new_danmaku_web_path)
                    if old_full_path and old_full_path.is_file() and old_full_path != new_full_path:
                        new_full_path.parent.mkdir(parents=True, exist_ok=True)
                        old_full_path.rename(new_full_path)

                new_episodes_to_add.append(orm_models.Episode(
                    id=new_id,
                    sourceId=old_ep.sourceId,
                    episodeIndex=new_index,
                    title=old_ep.title,
                    sourceUrl=old_ep.sourceUrl,
                    providerEpisodeId=old_ep.providerEpisodeId,
                    fetchedAt=old_ep.fetchedAt,
                    commentCount=old_ep.commentCount,
                    danmakuFilePath=new_danmaku_web_path
                ))
                old_episodes_to_delete.append(old_ep)

            # Perform DB operations
            for old_ep in old_episodes_to_delete:
                await session.delete(old_ep)
            await session.flush()

            session.add_all(new_episodes_to_add)
            await session.commit()

            raise TaskSuccess(f"集数偏移完成，共迁移了 {len(new_episodes_to_add)} 个分集。")

        except TaskSuccess:
            # TaskSuccess 不是错误，直接向上传递
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"集数偏移任务 (源ID: {source_id}) 事务中失败: {e}", exc_info=True)
            raise
        finally:
            # Re-enable foreign key checks
            if is_mysql:
                try:
                    await session.execute(text("SET FOREIGN_KEY_CHECKS=1;"))
                except Exception as e:
                    logger.warning(f"无法恢复MySQL外键检查: {e}")
            elif is_postgres:
                try:
                    await session.execute(text("SET session_replication_role = 'origin';"))
                except Exception as e:
                    logger.warning(f"无法恢复PostgreSQL会话角色: {e}")

    except ValueError as e:
        # Catch validation errors and report them as task failures
        logger.error(f"集数偏移任务验证失败: {e}")
        raise TaskSuccess(f"操作失败: {e}")
    except Exception as e:
        logger.error(f"集数偏移任务失败: {e}", exc_info=True)
        raise

