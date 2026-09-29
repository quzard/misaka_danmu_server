"""弹幕保鲜（fork 扩展）。

新集刚入库时，视频网站上的弹幕只有最终量的三分之一左右，一天后到八成多，两三天后才稳定。
这里让弹幕在用户按下播放之前就是新的。全部在后台进行，取弹幕的请求不会因此等待。

1. 入库后按节奏重抓：Jellyfin 的 ItemAdded 事件登记新集，之后按 FULL_PLAN 里的小时数各重抓一次。
2. 播放第 N 集时顺带刷新第 N+1 集。
3. 每天夜里找出弹幕数明显少于同季邻近各集的分集，各重抓一次。

入口：
- register_ingest：webhook/_jellyfin_fork.py 在收到 ItemAdded 时调用
- on_play：api/dandan/predownload.py 在客户端取弹幕时调用
- tick：internal_tasks/fork_danmaku_freshness.py 每 5 分钟调用

重抓用的任务标识与上游的手动刷新相同（refresh-episode-<id>），
所以客户端取弹幕时如果正好在重抓，会按上游原有的逻辑等它一小会儿。
"""
import logging
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException, status
from sqlalchemy import BigInteger, Boolean, Column, Integer, MetaData, String, Table, insert, select, update

from src.core import get_now
from src.db.orm_models import Anime, AnimeSource, Episode, NaiveDateTime

logger = logging.getLogger(__name__)

# 入库后第几小时重抓。前密后疏，贴合弹幕增长的节奏
FULL_PLAN = (1, 2, 4, 8, 16, 24, 48, 72, 168)
# 入库时已经播出两天以上，弹幕大体成形，少抓几次
LATE_PLAN = (24, 168)
# 上映很久的电影：流媒体上线时间未知，先试一次，弹幕还在涨再继续
PROBE_PLAN = (24,)
PROBE_FOLLOW_UP = (72, 168, 336)
PROBE_MIN_GROWTH = 0.05
PROBE_CHECK_MINUTES = 20

EPISODE_FRESH_DAYS = 14
MOVIE_FRESH_DAYS = 60
LATE_AFTER_DAYS = 2

# 邻近各集的弹幕数低于这个值时，不做"偏少"判断
MIN_NEIGHBOR_COUNT = 2000
# 弹幕数不到邻近各集的六成算偏少。误判的代价只是多抓一次，而且同一集 30 天内只补一次
THIN_RATIO = 0.6
HEAL_HOUR = 4
HEAL_LIMIT = 15
HEAL_COOLDOWN_DAYS = 30

MAX_PER_TICK = 5
ENABLED_KEY = "forkDanmakuFreshnessEnabled"

_metadata = MetaData()
_schedule = Table(
    "fork_danmaku_freshness", _metadata,
    Column("item_id", String(64), primary_key=True),  # 媒体服务器的条目 ID
    Column("label", String(255), nullable=False),
    Column("plan", String(64), nullable=False),  # 逗号分隔的小时数
    Column("probe", Boolean, nullable=False, default=False),
    Column("ingested_at", NaiveDateTime, nullable=False),
    Column("stage", Integer, nullable=False, default=0),  # 已经处理到 plan 的第几项
    Column("next_refresh_at", NaiveDateTime, nullable=True),  # 为空表示已结束
    Column("last_count", Integer, nullable=True),
    Column("note", String(255), nullable=True),
)
_heal = Table(
    "fork_danmaku_heal", _metadata,
    Column("episode_id", BigInteger, primary_key=True),
    Column("healed_at", NaiveDateTime, nullable=False),
    Column("count_before", Integer, nullable=False),
)

_tables_ready = False
_last_heal_date: Optional[date] = None
_play_seen: Dict[int, float] = {}


@dataclass
class _Deps:
    session_factory: Any
    task_manager: Any
    scraper_manager: Any
    rate_limiter: Any
    config_manager: Any


@dataclass
class EpisodeStat:
    id: int
    index: int
    count: int
    fetched_at: Optional[datetime]


# --- 判断逻辑（不碰数据库，便于单独测试） ---

def choose_plan(item_type: str, premiere: Optional[date], today: date) -> Optional[Tuple[Tuple[int, ...], bool]]:
    """按首播日期决定重抓计划，返回（计划, 是否试探）。返回 None 表示不登记。"""
    age = (today - premiere).days if premiere else None
    if item_type == "Episode":
        # 首播很久的剧集弹幕早已稳定；没有首播日期的无从判断。这两种交给另外两个机制兜底
        if age is None or age > EPISODE_FRESH_DAYS:
            return None
        return (LATE_PLAN if age > LATE_AFTER_DAYS else FULL_PLAN), False
    if item_type == "Movie":
        # 电影的首播日期是院线上映日，流媒体上线通常晚得多，所以入库时弹幕往往还很新
        if age is not None and age <= MOVIE_FRESH_DAYS:
            return FULL_PLAN, False
        return PROBE_PLAN, True
    return None


def due_stage(plan: Sequence[int], stage: int, ingested_at: datetime, now: datetime) -> Optional[int]:
    """已到期的最后一项的下标；都没到期返回 None。错过多次（比如服务停过）只补最近的一次。"""
    due = None
    for i in range(stage, len(plan)):
        if ingested_at + timedelta(hours=plan[i]) > now:
            break
        due = i
    return due


def should_refresh_next(
    cur_count: int, next_count: int, next_fetched_at: Optional[datetime], now: datetime,
    in_hot_window: bool, healed_recently: bool,
) -> bool:
    """播放当前集时，要不要顺带刷新下一集。"""
    if not next_count or next_fetched_at is None:
        return False  # 还没有弹幕的交给上游的预下载
    age = now - next_fetched_at
    if in_hot_window:
        return age >= timedelta(hours=1)
    if healed_recently:
        return False  # 补过仍然偏少，说明这一集本来就少
    return (
        age >= timedelta(hours=24)
        and cur_count >= MIN_NEIGHBOR_COUNT
        and next_count < THIN_RATIO * cur_count
    )


def find_thin(episodes: Sequence[EpisodeStat], now: datetime) -> List[EpisodeStat]:
    """同一个源里，弹幕数明显少于前后各三集的分集。

    参照值取邻近各集的上四分位数而不是中位数：刚入库的新集、还没播出的占位数据本身就很少，
    会把中位数拉低，上四分位数不受它们影响。
    """
    eps = sorted((e for e in episodes if e.count > 0), key=lambda e: e.index)
    thin = []
    for i, e in enumerate(eps):
        neighbors = [x.count for x in eps[max(0, i - 3): i + 4] if x is not e]
        if len(neighbors) < 3:
            continue
        reference = statistics.quantiles(neighbors, n=4, method="inclusive")[2]
        if reference < MIN_NEIGHBOR_COUNT or e.count >= THIN_RATIO * reference:
            continue
        if e.fetched_at is not None and now - e.fetched_at < timedelta(hours=48):
            continue  # 刚抓过的还在涨，先不管
        thin.append(e)
    return thin


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_plan(text: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in text.split(",") if x)


def _label(payload: Dict[str, Any]) -> str:
    if payload.get("ItemType") == "Episode":
        season, episode = payload.get("SeasonNumber"), payload.get("EpisodeNumber")
        if season is not None and episode is not None:
            return f"{payload.get('SeriesName')} S{int(season):02d}E{int(episode):02d}"
        return f"{payload.get('SeriesName')} {payload.get('Name')}"
    return str(payload.get("Name"))


# --- 数据库与任务 ---

async def _ensure_tables(session) -> None:
    global _tables_ready
    if _tables_ready:
        return
    conn = await session.connection()
    await conn.run_sync(lambda c: _metadata.create_all(c, checkfirst=True))
    await session.commit()
    _tables_ready = True


async def _submit_refresh(deps: _Deps, episode_id: int, title: str) -> None:
    from src.tasks import refresh_episode_task

    def factory(session, progress_callback):
        return refresh_episode_task(
            episodeId=episode_id, session=session, manager=deps.scraper_manager,
            rate_limiter=deps.rate_limiter, progress_callback=progress_callback,
            config_manager=deps.config_manager,
        )

    try:
        await deps.task_manager.submit_task(factory, title, unique_key=f"refresh-episode-{episode_id}")
    except HTTPException as e:
        # 这一集正在刷新（409），不用重复提交
        if e.status_code != status.HTTP_409_CONFLICT:
            raise
        logger.info(f"弹幕保鲜: '{title}' 已有刷新任务在进行，跳过。")


async def _episode_label(session, episode: Episode) -> str:
    row = (await session.execute(
        select(Anime.title, Anime.season, Anime.type)
        .join(AnimeSource, AnimeSource.animeId == Anime.id)
        .where(AnimeSource.id == episode.sourceId)
    )).first()
    if not row:
        return f"分集 {episode.id}"
    if row.type == "movie":
        return row.title
    return f"{row.title} S{row.season:02d}E{episode.episodeIndex:02d}"


async def _is_enabled(config_manager) -> bool:
    return str(await config_manager.get(ENABLED_KEY, "true")).lower() == "true"


# --- 入口一：入库时登记 ---

async def register_ingest(session_factory, payload: Dict[str, Any]) -> None:
    """Jellyfin 的 ItemAdded 事件：给新入库的单集或电影登记重抓计划。出错只记日志，不影响入库处理。"""
    try:
        item_id = payload.get("ItemId")
        chosen = choose_plan(payload.get("ItemType"), _parse_date(payload.get("PremiereDate")), get_now().date())
        if not item_id or not chosen:
            return
        plan, probe = chosen
        now = get_now()
        label = _label(payload)
        async with session_factory() as session:
            await _ensure_tables(session)
            exists = await session.execute(select(_schedule.c.item_id).where(_schedule.c.item_id == str(item_id)))
            if exists.first():
                return
            await session.execute(insert(_schedule).values(
                item_id=str(item_id), label=label[:255], plan=",".join(str(h) for h in plan), probe=probe,
                ingested_at=now, stage=0, next_refresh_at=now + timedelta(hours=plan[0]),
            ))
            await session.commit()
        logger.info(f"弹幕保鲜: 已登记 '{label}'，入库后第 {'、'.join(str(h) for h in plan)} 小时重抓。")
    except Exception as e:
        logger.error(f"弹幕保鲜: 登记入库事件失败: {e}", exc_info=True)


# --- 入口二：播放时刷新下一集 ---

async def on_play(current_episode_id: int, session_factory, task_manager, scraper_manager, rate_limiter, config_manager) -> None:
    """客户端取第 N 集的弹幕时调用。出错只记日志，不影响取弹幕。"""
    try:
        if not await _is_enabled(config_manager):
            return
        # 客户端一次播放可能取好几次弹幕，十分钟内同一集只看一次
        mono = time.monotonic()
        for key in [k for k, t in _play_seen.items() if mono - t >= 600]:
            del _play_seen[key]
        if current_episode_id in _play_seen:
            return
        _play_seen[current_episode_id] = mono

        deps = _Deps(session_factory, task_manager, scraper_manager, rate_limiter, config_manager)
        now = get_now()
        async with session_factory() as session:
            await _ensure_tables(session)
            cur = await session.get(Episode, current_episode_id)
            if not cur:
                return
            nxt = (await session.execute(
                select(Episode).where(Episode.sourceId == cur.sourceId, Episode.episodeIndex == cur.episodeIndex + 1)
            )).scalar_one_or_none()
            if not nxt:
                return

            in_hot_window = False
            if nxt.mediaServerEpisodeId:
                in_hot_window = (await session.execute(
                    select(_schedule.c.item_id).where(
                        _schedule.c.item_id == nxt.mediaServerEpisodeId, _schedule.c.next_refresh_at.is_not(None))
                )).first() is not None
            healed_recently = (await session.execute(
                select(_heal.c.episode_id).where(
                    _heal.c.episode_id == nxt.id, _heal.c.healed_at >= now - timedelta(days=HEAL_COOLDOWN_DAYS))
            )).first() is not None

            if not should_refresh_next(cur.commentCount, nxt.commentCount, nxt.fetchedAt, now, in_hot_window, healed_recently):
                return
            if not in_hot_window:
                await _record_heal(session, nxt.id, nxt.commentCount, now)
            label = await _episode_label(session, nxt)
            next_id, next_count = nxt.id, nxt.commentCount
            await session.commit()

        logger.info(f"弹幕保鲜: 正在播放上一集，顺带刷新 '{label}'（现有 {next_count} 条）。")
        await _submit_refresh(deps, next_id, f"弹幕保鲜: {label}（播放上一集时刷新）")
    except Exception as e:
        logger.error(f"弹幕保鲜: 播放时刷新下一集失败 (episodeId={current_episode_id}): {e}", exc_info=True)


# --- 入口三：定时处理 ---

async def tick(app) -> None:
    """每 5 分钟一次：处理到期的重抓计划；凌晨补一次偏少的分集。"""
    state = app.state
    deps = _Deps(state.db_session_factory, state.task_manager, state.scraper_manager, state.rate_limiter, state.config_manager)
    if not await _is_enabled(deps.config_manager):
        return
    now = get_now()
    async with deps.session_factory() as session:
        await _ensure_tables(session)
        await _process_due(session, deps, now)
    await _heal_thin_episodes(deps, now)


async def _process_due(session, deps: _Deps, now: datetime) -> None:
    rows = (await session.execute(
        select(_schedule)
        .where(_schedule.c.next_refresh_at.is_not(None), _schedule.c.next_refresh_at <= now)
        .order_by(_schedule.c.next_refresh_at)
        .limit(MAX_PER_TICK)
    )).mappings().all()

    for row in rows:
        plan = _parse_plan(row["plan"])
        values: Dict[str, Any]
        episode = (await session.execute(
            select(Episode).where(Episode.mediaServerEpisodeId == row["item_id"])
            .order_by(Episode.commentCount.desc()).limit(1)
        )).scalar_one_or_none()

        if episode is None:
            # 入库时没搜到弹幕源，或导入还没完成
            if now - row["ingested_at"] > timedelta(hours=24):
                values = {"next_refresh_at": None, "note": "库里没有对应的弹幕"}
            else:
                values = {"next_refresh_at": now + timedelta(minutes=30)}
        elif row["probe"] and row["stage"] >= len(plan):
            # 试探的那次重抓已经做完，看弹幕涨了多少
            base = row["last_count"] or 0
            if base > 0 and (episode.commentCount - base) / base >= PROBE_MIN_GROWTH:
                plan = plan + PROBE_FOLLOW_UP
                values = {
                    "plan": ",".join(str(h) for h in plan), "probe": False,
                    "next_refresh_at": row["ingested_at"] + timedelta(hours=plan[row["stage"]]),
                    "note": f"弹幕还在增长（{base} → {episode.commentCount}），继续重抓",
                }
            else:
                values = {"next_refresh_at": None, "note": "弹幕已不再增长"}
        else:
            stage = due_stage(plan, row["stage"], row["ingested_at"], now)
            if stage is None:
                values = {"next_refresh_at": row["ingested_at"] + timedelta(hours=plan[row["stage"]])}
            else:
                # 刚被别的途径刷新过（比如用户手动标记已看）就不重复抓
                if episode.fetchedAt is None or now - episode.fetchedAt >= timedelta(minutes=20):
                    logger.info(f"弹幕保鲜: 重抓 '{row['label']}'（入库后第 {plan[stage]} 小时，现有 {episode.commentCount} 条）。")
                    await _submit_refresh(deps, episode.id, f"弹幕保鲜: {row['label']}（入库后第 {plan[stage]} 小时）")
                values = {"stage": stage + 1, "last_count": episode.commentCount, "note": None}
                if stage + 1 < len(plan):
                    values["next_refresh_at"] = row["ingested_at"] + timedelta(hours=plan[stage + 1])
                elif row["probe"]:
                    values["next_refresh_at"] = now + timedelta(minutes=PROBE_CHECK_MINUTES)
                else:
                    values.update(next_refresh_at=None, note="已完成")

        await session.execute(update(_schedule).where(_schedule.c.item_id == row["item_id"]).values(**values))
    await session.commit()


async def _record_heal(session, episode_id: int, count_before: int, now: datetime) -> None:
    exists = (await session.execute(select(_heal.c.episode_id).where(_heal.c.episode_id == episode_id))).first()
    stmt = (
        update(_heal).where(_heal.c.episode_id == episode_id).values(healed_at=now, count_before=count_before)
        if exists else insert(_heal).values(episode_id=episode_id, healed_at=now, count_before=count_before)
    )
    await session.execute(stmt)


async def _heal_thin_episodes(deps: _Deps, now: datetime) -> None:
    global _last_heal_date
    if now.hour != HEAL_HOUR or _last_heal_date == now.date():
        return
    _last_heal_date = now.date()

    async with deps.session_factory() as session:
        rows = (await session.execute(
            select(Episode.id, Episode.sourceId, Episode.episodeIndex, Episode.commentCount, Episode.fetchedAt,
                   Episode.mediaServerEpisodeId)
        )).all()
        # 还在按计划重抓的分集不用补。在 Python 里比对，不在 SQL 里 join：
        # 新表按库的默认排序规则建，与 episode 表的不一定相同，MySQL 会拒绝两列直接比较
        active = {r.item_id for r in (await session.execute(
            select(_schedule.c.item_id).where(_schedule.c.next_refresh_at.is_not(None))
        )).all()}
        scheduled = {r.id for r in rows if r.mediaServerEpisodeId in active}
        by_source: Dict[int, List[EpisodeStat]] = {}
        for r in rows:
            by_source.setdefault(r.sourceId, []).append(EpisodeStat(r.id, r.episodeIndex, r.commentCount or 0, r.fetchedAt))

        healed = {r.episode_id for r in (await session.execute(
            select(_heal.c.episode_id).where(_heal.c.healed_at >= now - timedelta(days=HEAL_COOLDOWN_DAYS))
        )).all()}

        # 最近有动静的源排在前面：那是正在看的剧
        candidates: List[Tuple[datetime, EpisodeStat]] = []
        for episodes in by_source.values():
            latest = max((e.fetched_at for e in episodes if e.fetched_at), default=datetime.min)
            candidates += [(latest, e) for e in find_thin(episodes, now) if e.id not in healed and e.id not in scheduled]
        candidates.sort(key=lambda c: c[0], reverse=True)
        chosen = [e for _, e in candidates[:HEAL_LIMIT]]
        if len(candidates) > len(chosen):
            logger.info(f"弹幕保鲜: 有 {len(candidates)} 集弹幕偏少，今晚先补 {len(chosen)} 集，其余留到明晚。")

        todo = []
        for e in chosen:
            episode = await session.get(Episode, e.id)
            todo.append((e, await _episode_label(session, episode)))
            await _record_heal(session, e.id, e.count, now)
        await session.commit()

    for e, label in todo:
        logger.info(f"弹幕保鲜: '{label}' 只有 {e.count} 条，明显少于邻近各集，重抓一次。")
        await _submit_refresh(deps, e.id, f"弹幕保鲜: {label}（弹幕偏少，补抓）")
