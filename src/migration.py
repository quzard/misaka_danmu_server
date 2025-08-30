import asyncio
import logging
from pathlib import Path
from typing import List
import xml.etree.ElementTree as ET

from sqlalchemy import select, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy.orm import selectinload, DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, ForeignKey, Integer, String, TEXT

logger = logging.getLogger(__name__)

# --- 弹幕文件存储配置 ---
DANMAKU_BASE_DIR = Path(__file__).parent.parent / "config" / "danmaku"

# --- 临时的 ORM 模型定义，仅用于此脚本，以避免与已修改的主模型冲突 ---
class TmpBase(DeclarativeBase):
    pass

class TmpAnime(TmpBase):
    __tablename__ = "anime"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sources: Mapped[List["TmpAnimeSource"]] = relationship(back_populates="anime")

class TmpAnimeSource(TmpBase):
    __tablename__ = "anime_sources"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    animeId: Mapped[int] = mapped_column("anime_id", ForeignKey("anime.id"))
    episodes: Mapped[List["TmpEpisode"]] = relationship(back_populates="source")
    anime: Mapped["TmpAnime"] = relationship(back_populates="sources")

class TmpEpisode(TmpBase):
    __tablename__ = "episode"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sourceId: Mapped[int] = mapped_column("source_id", ForeignKey("anime_sources.id"))
    danmakuFilePath: Mapped[str] = mapped_column("danmaku_file_path", String(512), nullable=True)
    commentCount: Mapped[int] = mapped_column("comment_count", Integer)
    comments: Mapped[List["TmpComment"]] = relationship(back_populates="episode")
    source: Mapped["TmpAnimeSource"] = relationship(back_populates="episodes")

class TmpComment(TmpBase):
    __tablename__ = "comment"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    episodeId: Mapped[int] = mapped_column("episode_id", ForeignKey("episode.id"))
    p: Mapped[str] = mapped_column(String(255))
    m: Mapped[str] = mapped_column(TEXT)
    episode: Mapped["TmpEpisode"] = relationship(back_populates="comments")

def _generate_xml_from_comments(comments: List[TmpComment], episode_id: int) -> str:
    """根据弹幕对象列表生成符合dandanplay标准的XML字符串。"""
    root = ET.Element('i')
    ET.SubElement(root, 'chatserver').text = 'danmaku.misaka.org'
    ET.SubElement(root, 'chatid').text = str(episode_id)
    ET.SubElement(root, 'mission').text = '0'
    ET.SubElement(root, 'maxlimit').text = '2000'
    ET.SubElement(root, 'source').text = 'misaka'
    for comment in comments:
        ET.SubElement(root, 'd', p=comment.p).text = comment.m
    return ET.tostring(root, encoding='unicode', xml_declaration=True)

async def _add_danmaku_path_column_if_not_exists(session: AsyncSession):
    """如果 episode 表中不存在 danmaku_file_path 列，则添加它。"""
    def check_columns_sync(conn):
        inspector = inspect(conn.connection())
        columns = inspector.get_columns('episode')
        return any(c['name'] == 'danmaku_file_path' for c in columns)

    has_column = await session.run_sync(check_columns_sync)

    if not has_column:
        logger.info("检测到 'episode' 表中缺少 'danmaku_file_path' 列，正在添加...")
        await session.execute(text("ALTER TABLE episode ADD COLUMN danmaku_file_path VARCHAR(512);"))
        await session.commit()
        logger.info("'danmaku_file_path' 列已成功添加。")

async def run_db_migration(session_factory: async_sessionmaker[AsyncSession]):
    """
    在应用启动时执行数据库迁移。
    """
    logger.info("--- 正在检查数据库迁移需求 ---")
    async with session_factory() as session:
        def check_table_sync(conn):
            inspector = inspect(conn.connection())
            return inspector.has_table('comment')

        has_comment_table = await session.run_sync(check_table_sync)
        
        if not has_comment_table:
            logger.info("✅ 未找到 'comment' 表，无需迁移。")
            return

        logger.info("检测到旧的 'comment' 表，将开始执行数据迁移...")

        # 1. 确保新列存在
        await _add_danmaku_path_column_if_not_exists(session)

        # 2. 查询所有需要迁移的分集和弹幕
        logger.info("正在查询所有分集和关联的弹幕数据，这可能需要一些时间...")
        stmt = (
            select(TmpEpisode)
            .options(
                selectinload(TmpEpisode.comments),
                selectinload(TmpEpisode.source).selectinload(TmpAnimeSource.anime)
            )
            .where(TmpEpisode.comments.any(), TmpEpisode.danmakuFilePath == None)
        )
        result = await session.execute(stmt)
        episodes_to_migrate = result.scalars().unique().all()

        if not episodes_to_migrate:
            logger.info("✅ 数据库中没有找到需要迁移的弹幕数据。")
            logger.info("正在删除空的 'comment' 表...")
            await session.execute(text("DROP TABLE comment;"))
            await session.commit()
            logger.info("'comment' 表已删除。")
            return

        logger.info(f"共找到 {len(episodes_to_migrate)} 个分集需要迁移。")

        # 3. 遍历并处理每个分集
        migrated_count = 0
        try:
            for episode in episodes_to_migrate:
                if not episode.comments:
                    continue

                anime_id = episode.source.anime.id
                source_id = episode.source.id
                episode_id = episode.id

                # 4. 生成XML内容
                xml_content = _generate_xml_from_comments(episode.comments, episode_id)
                
                # 5. 构建文件路径并写入
                web_path = f"/data/danmaku/{anime_id}/{source_id}/{episode_id}.xml"
                absolute_path = DANMAKU_BASE_DIR / str(anime_id) / str(source_id) / f"{episode_id}.xml"
                
                try:
                    absolute_path.parent.mkdir(parents=True, exist_ok=True)
                    absolute_path.write_text(xml_content, encoding='utf-8')
                except OSError as e:
                    logger.error(f"❌ 写入文件失败: {absolute_path}。错误: {e}")
                    continue # 跳过这个分集

                # 6. 更新数据库记录
                episode.danmakuFilePath = web_path
                episode.commentCount = len(episode.comments)
                session.add(episode)
                migrated_count += 1
                if migrated_count % 100 == 0:
                    logger.info(f"已处理 {migrated_count}/{len(episodes_to_migrate)} 个分集...")
            
            # 7. 提交所有数据库更改
            logger.info("正在将所有文件路径更新提交到数据库...")
            await session.commit()
            logger.info("数据库更新完成。")

            # 8. 删除旧的 comment 表
            logger.info("正在删除旧的 'comment' 表...")
            await session.execute(text("DROP TABLE comment;"))
            await session.commit()
            logger.info("'comment' 表已成功删除。")

        except Exception as e:
            logger.error(f"迁移过程中发生严重错误: {e}", exc_info=True)
            await session.rollback()
            logger.error("数据库事务已回滚。请检查错误并手动重新运行迁移。")
            raise

    logger.info(f"🎉 --- 弹幕数据迁移成功！共迁移了 {migrated_count} 个分集的弹幕。 ---")