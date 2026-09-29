"""弹幕保鲜的测试。在 misaka 镜像的一次性容器里运行，用 MySQL 里的临时数据库，跑完删除。

用法: python /t/test_freshness.py
环境变量: MYSQL_ROOT_PASSWORD
"""
import asyncio
import os
import sys
import traceback
from datetime import date, datetime, timedelta

sys.path.insert(0, "/app")
import src.services  # noqa: E402,F401  与应用启动时的导入顺序一致

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text, select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker  # noqa: E402

import src.fork_freshness as ff  # noqa: E402
from src.db.orm_models import Base, Anime, AnimeSource, Episode  # noqa: E402

DB = "danmuapi_forktest"
URL = "mysql+asyncmy://root:%s@mysql:3306/" % os.environ["MYSQL_ROOT_PASSWORD"]
T0 = datetime(2026, 9, 29, 19, 0, 0)  # 入库时间
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  ok   " if cond else "  FAIL ") + name + ((" | " + str(detail)) if detail and not cond else ""))


class FakeTaskManager:
    def __init__(self):
        self.calls = []
        self.busy = set()

    async def submit_task(self, factory, title, unique_key=None, **kw):
        if unique_key in self.busy:
            raise HTTPException(status_code=409, detail="dup")
        self.calls.append((title, unique_key))
        return "task-id", asyncio.Event()


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    async def get(self, key, default=None):
        return self.values.get(key, default)


def set_now(now):
    ff.get_now = lambda: now


async def rows(sf):
    async with sf() as s:
        return {r["item_id"]: dict(r) for r in (await s.execute(select(ff._schedule))).mappings().all()}


async def heal_rows(sf):
    async with sf() as s:
        return {r["episode_id"]: dict(r) for r in (await s.execute(select(ff._heal))).mappings().all()}


async def add_source(sf, title, counts, fetched, item_ids=None, kind="tv_series", source_no=1):
    """建一部作品和它的分集。counts: {集号: 弹幕数}；fetched: {集号: 抓取时间}。返回 {集号: 分集 id}。"""
    async with sf() as s:
        a = Anime(title=title, type=kind, season=1, createdAt=T0)
        s.add(a); await s.flush()
        src = AnimeSource(animeId=a.id, sourceOrder=1, providerName="tencent", mediaId="m%d" % source_no, createdAt=T0)
        s.add(src); await s.flush()
        ids = {}
        for idx, c in counts.items():
            eid = 25000000000000 + source_no * 10000 + idx
            s.add(Episode(id=eid, sourceId=src.id, title="第 %d 集" % idx, episodeIndex=idx, providerEpisodeId="p%d" % idx,
                          commentCount=c, fetchedAt=fetched.get(idx), mediaServerEpisodeId=(item_ids or {}).get(idx)))
            ids[idx] = eid
        await s.commit()
        return ids


async def set_episode(sf, eid, **values):
    async with sf() as s:
        e = await s.get(Episode, eid)
        for k, v in values.items():
            setattr(e, k, v)
        await s.commit()


def pure_tests():
    print("== 判断逻辑")
    today = date(2026, 9, 29)
    check("当天首播的单集用完整计划", ff.choose_plan("Episode", today, today) == (ff.FULL_PLAN, False))
    check("首播 3 天的单集用精简计划", ff.choose_plan("Episode", today - timedelta(days=3), today) == (ff.LATE_PLAN, False))
    check("首播 14 天的单集仍登记", ff.choose_plan("Episode", today - timedelta(days=14), today) is not None)
    check("首播 15 天的单集不登记", ff.choose_plan("Episode", today - timedelta(days=15), today) is None)
    check("没有首播日期的单集不登记", ff.choose_plan("Episode", None, today) is None)
    check("首播日期在未来的单集用完整计划", ff.choose_plan("Episode", today + timedelta(days=1), today) == (ff.FULL_PLAN, False))
    check("上映 30 天的电影用完整计划", ff.choose_plan("Movie", today - timedelta(days=30), today) == (ff.FULL_PLAN, False))
    check("上映 90 天的电影先试探", ff.choose_plan("Movie", today - timedelta(days=90), today) == (ff.PROBE_PLAN, True))
    check("没有上映日期的电影先试探", ff.choose_plan("Movie", None, today) == (ff.PROBE_PLAN, True))
    check("季和整部剧不登记", ff.choose_plan("Season", today, today) is None and ff.choose_plan("Series", today, today) is None)

    p = ff.FULL_PLAN
    check("还没到第一次", ff.due_stage(p, 0, T0, T0 + timedelta(minutes=59)) is None)
    check("刚到第一次", ff.due_stage(p, 0, T0, T0 + timedelta(hours=1)) == 0)
    check("错过多次只补最近一次", ff.due_stage(p, 1, T0, T0 + timedelta(hours=9)) == 3)
    check("全部过期取最后一项", ff.due_stage(p, 0, T0, T0 + timedelta(days=30)) == len(p) - 1)
    check("计划走完后没有到期项", ff.due_stage(p, len(p), T0, T0 + timedelta(days=30)) is None)

    now = T0
    hot = dict(in_hot_window=True, healed_recently=False)
    cold = dict(in_hot_window=False, healed_recently=False)
    check("热门期内抓取超过 1 小时就刷新", ff.should_refresh_next(30000, 11000, now - timedelta(hours=2), now, **hot))
    check("热门期内刚抓过不刷新", not ff.should_refresh_next(30000, 11000, now - timedelta(minutes=30), now, **hot))
    check("偏少且超过一天就刷新", ff.should_refresh_next(29522, 15906, now - timedelta(days=2), now, **cold))
    check("偏少但一天内抓过不刷新", not ff.should_refresh_next(29522, 15906, now - timedelta(hours=5), now, **cold))
    check("数量相近不刷新", not ff.should_refresh_next(29522, 25875, now - timedelta(days=2), now, **cold))
    check("补过仍偏少不再刷新", not ff.should_refresh_next(29522, 15906, now - timedelta(days=2), now, in_hot_window=False, healed_recently=True))
    check("当前集本身弹幕很少时不判断", not ff.should_refresh_next(1500, 500, now - timedelta(days=2), now, **cold))
    check("下一集没有弹幕交给预下载", not ff.should_refresh_next(29522, 0, now - timedelta(days=2), now, **cold))
    check("下一集没有抓取时间不刷新", not ff.should_refresh_next(29522, 100, None, now, **cold))

    old = now - timedelta(days=3)
    real = [29853, 29623, 28458, 31836, 29522, 15906, 15818, 25875, 11344, 417]  # 兰香如故 E30 到 E39 的真实数据
    eps = [ff.EpisodeStat(i, 30 + i, c, old) for i, c in enumerate(real)]
    eps[8].fetched_at = eps[9].fetched_at = now - timedelta(hours=1)  # E38、E39 刚抓过
    thin = sorted(e.index for e in ff.find_thin(eps, now))
    check("真实数据里只挑出 E35 和 E36", thin == [35, 36], thin)
    check("不足 4 集不判断", ff.find_thin([ff.EpisodeStat(i, i, c, old) for i, c in enumerate([30000, 100, 30000])], now) == [])
    check("整体弹幕都很少不判断", ff.find_thin([ff.EpisodeStat(i, i, c, old) for i, c in enumerate([1500, 1400, 100, 1600, 1500])], now) == [])
    check("没有弹幕的分集不参与", [e.index for e in ff.find_thin([ff.EpisodeStat(i, i, c, old) for i, c in enumerate([30000, 0, 29000, 31000, 9000, 30000])], now)] == [4])


async def db_tests(sf):
    tm = FakeTaskManager()
    deps = ff._Deps(sf, tm, None, None, FakeConfig())

    print("== 入库登记")
    set_now(T0)
    ep = {"ItemType": "Episode", "SeriesName": "兰香如故", "SeasonNumber": 1, "EpisodeNumber": 38, "Name": "第 38 集", "PremiereDate": "2026-09-29"}
    await ff.register_ingest(sf, {**ep, "ItemId": "item38"})
    await ff.register_ingest(sf, {**ep, "ItemId": "item38"})  # 重复事件
    await ff.register_ingest(sf, {**ep, "ItemId": "itemold", "EpisodeNumber": 1, "PremiereDate": "2026-08-01"})
    await ff.register_ingest(sf, {**ep, "ItemId": "itemlate", "EpisodeNumber": 36, "PremiereDate": "2026-09-25"})
    await ff.register_ingest(sf, {**ep, "ItemId": None})
    await ff.register_ingest(sf, {"ItemType": "Movie", "Name": "无双", "ItemId": "movie1", "PremiereDate": "2018-09-30"})
    await ff.register_ingest(sf, {"ItemType": "Season", "Name": "第 1 季", "ItemId": "season1", "PremiereDate": "2026-09-29"})
    await ff.register_ingest(sf, {"ItemType": "Episode", "SeriesName": "坏数据", "ItemId": "bad", "PremiereDate": "not-a-date", "SeasonNumber": "x"})
    r = await rows(sf)
    check("只登记了新集、晚入库的集和电影", sorted(r) == ["item38", "itemlate", "movie1"], sorted(r))
    check("新集：完整计划，一小时后第一次", r["item38"]["plan"] == "1,2,4,8,16,24,48,72,168" and r["item38"]["next_refresh_at"] == T0 + timedelta(hours=1) and r["item38"]["label"] == "兰香如故 S01E38", r["item38"])
    check("晚入库的集：精简计划", r["itemlate"]["plan"] == "24,168" and not r["itemlate"]["probe"])
    check("老电影：试探", r["movie1"]["plan"] == "24" and r["movie1"]["probe"] and r["movie1"]["label"] == "无双")

    print("== 到期处理")
    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(minutes=30))
    check("没到期不处理", tm.calls == [] and (await rows(sf))["item38"]["stage"] == 0)

    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(hours=1, minutes=3))
    r = await rows(sf)
    check("弹幕还没入库时推迟 30 分钟", tm.calls == [] and r["item38"]["stage"] == 0 and r["item38"]["next_refresh_at"] == T0 + timedelta(hours=1, minutes=33), r["item38"])

    ids = await add_source(sf, "兰香如故", {37: 25875, 38: 11344}, {37: T0 - timedelta(days=1), 38: T0 + timedelta(minutes=4)}, {38: "item38", 36: "itemlate"})
    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(hours=1, minutes=35))
    r = await rows(sf)
    check("第 1 小时：提交一次重抓", tm.calls == [("弹幕保鲜: 兰香如故 S01E38（入库后第 1 小时）", "refresh-episode-%d" % ids[38])], tm.calls)
    check("第 1 小时：进入下一阶段", r["item38"]["stage"] == 1 and r["item38"]["next_refresh_at"] == T0 + timedelta(hours=2) and r["item38"]["last_count"] == 11344, r["item38"])

    tm.calls.clear()
    await set_episode(sf, ids[38], fetchedAt=T0 + timedelta(hours=1, minutes=36), commentCount=14000)
    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(hours=9))
    r = await rows(sf)
    check("错过第 2、4、8 小时：只补一次", [c[0] for c in tm.calls] == ["弹幕保鲜: 兰香如故 S01E38（入库后第 8 小时）"], tm.calls)
    check("错过后直接跳到第 16 小时", r["item38"]["stage"] == 4 and r["item38"]["next_refresh_at"] == T0 + timedelta(hours=16), r["item38"])

    tm.calls.clear()
    await set_episode(sf, ids[38], fetchedAt=T0 + timedelta(hours=15, minutes=50))
    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(hours=16))
    r = await rows(sf)
    check("20 分钟内刚抓过：不重复抓，但照常前进", tm.calls == [] and r["item38"]["stage"] == 5, (tm.calls, r["item38"]))

    tm.calls.clear()
    tm.busy.add("refresh-episode-%d" % ids[38])
    await set_episode(sf, ids[38], fetchedAt=T0 + timedelta(hours=16))
    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(hours=24))
    r = await rows(sf)
    check("已有刷新任务在跑：不报错，照常前进", tm.calls == [] and r["item38"]["stage"] == 6, r["item38"])
    tm.busy.clear()

    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(days=8))
    r = await rows(sf)
    check("最后一次之后结束", r["item38"]["stage"] == 9 and r["item38"]["next_refresh_at"] is None and r["item38"]["note"] == "已完成", r["item38"])
    check("晚入库但库里没有弹幕的集：一天后放弃", r["itemlate"]["next_refresh_at"] is None and r["itemlate"]["note"] == "库里没有对应的弹幕", r["itemlate"])

    print("== 电影试探")
    tm.calls.clear()
    async with sf() as s:  # 上面跳到 8 天后时 movie1 已被处理过，重新登记
        await s.execute(ff._schedule.delete().where(ff._schedule.c.item_id == "movie1"))
        await s.commit()
    await ff.register_ingest(sf, {"ItemType": "Movie", "Name": "无双", "ItemId": "movie1", "PremiereDate": "2018-09-30"})
    mids = await add_source(sf, "无双", {1: 20000}, {1: T0}, {1: "movie1"}, kind="movie", source_no=2)
    await ff.register_ingest(sf, {"ItemType": "Movie", "Name": "新电影", "ItemId": "movie2", "PremiereDate": None})
    m2 = await add_source(sf, "新电影", {1: 5000}, {1: T0}, {1: "movie2"}, kind="movie", source_no=3)
    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(hours=24, minutes=1))
    r = await rows(sf)
    check("试探：第 24 小时重抓两部电影", sorted(c[0] for c in tm.calls) == ["弹幕保鲜: 新电影（入库后第 24 小时）", "弹幕保鲜: 无双（入库后第 24 小时）"], tm.calls)
    check("试探：20 分钟后回来看结果", r["movie1"]["stage"] == 1 and r["movie1"]["next_refresh_at"] == T0 + timedelta(hours=24, minutes=21) and r["movie1"]["last_count"] == 20000, r["movie1"])
    await set_episode(sf, mids[1], commentCount=20300)  # 涨了 1.5%
    await set_episode(sf, m2[1], commentCount=9000)  # 涨了 80%
    tm.calls.clear()
    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(hours=24, minutes=25))
    r = await rows(sf)
    check("试探：不再增长的结束", r["movie1"]["next_refresh_at"] is None and r["movie1"]["note"] == "弹幕已不再增长", r["movie1"])
    check("试探：还在增长的转为继续重抓", r["movie2"]["plan"] == "24,72,168,336" and not r["movie2"]["probe"] and r["movie2"]["next_refresh_at"] == T0 + timedelta(hours=72) and tm.calls == [], r["movie2"])
    async with sf() as s:
        await ff._process_due(s, deps, T0 + timedelta(hours=72, minutes=1))
    check("试探转正后按计划重抓", [c[0] for c in tm.calls] == ["弹幕保鲜: 新电影（入库后第 72 小时）"], tm.calls)

    print("== 播放时刷新下一集")
    tm.calls.clear()
    now = T0 + timedelta(hours=3)
    set_now(now)
    await ff.register_ingest(sf, {**ep, "ItemId": "hot40", "EpisodeNumber": 40})
    real = {30: 29853, 31: 29623, 32: 28458, 33: 31836, 34: 29522, 35: 15906, 36: 15818, 39: 0, 40: 9000, 41: 28000}
    fetched = {i: now - timedelta(days=3) for i in real}
    fetched[40] = now - timedelta(hours=2)
    fetched[41] = now - timedelta(minutes=30)
    play = await add_source(sf, "连看测试", real, fetched, {40: "hot40"}, source_no=4)
    args = (sf, tm, None, None, FakeConfig())

    await ff.on_play(play[34], *args)
    check("播 E34：下一集偏少，刷新 E35", tm.calls == [("弹幕保鲜: 连看测试 S01E35（播放上一集时刷新）", "refresh-episode-%d" % play[35])], tm.calls)
    check("记下补过 E35", play[35] in await heal_rows(sf))
    tm.calls.clear()
    await ff.on_play(play[34], *args)
    check("十分钟内重复取弹幕不再处理", tm.calls == [])
    ff._play_seen.clear()
    await ff.on_play(play[34], *args)
    check("补过的集 30 天内不再补", tm.calls == [])
    await ff.on_play(play[30], *args)
    check("下一集数量正常不刷新", tm.calls == [])
    await ff.on_play(play[36], *args)
    check("没有下一集不处理", tm.calls == [])
    await ff.on_play(play[39], *args)
    check("播 E39：E40 在热门期且抓取超过 1 小时，刷新", [c[0] for c in tm.calls] == ["弹幕保鲜: 连看测试 S01E40（播放上一集时刷新）"], tm.calls)
    check("热门期的刷新不占用补抓名额", play[40] not in await heal_rows(sf))
    tm.calls.clear()
    await ff.on_play(play[40], *args)
    check("下一集半小时前刚抓过不刷新", tm.calls == [])
    await ff.on_play(999, *args)
    check("分集不存在不报错", tm.calls == [])
    ff._play_seen.clear()
    await ff.on_play(play[34], sf, tm, None, None, FakeConfig({ff.ENABLED_KEY: "false"}))
    check("开关关闭时不处理", tm.calls == [])

    print("== 夜间补抓")
    tm.calls.clear()
    ff._play_seen.clear()
    async with sf() as s:
        await s.execute(ff._heal.delete())
        await s.commit()
    night = datetime(2026, 10, 3, 4, 10)
    await ff._heal_thin_episodes(deps, datetime(2026, 10, 3, 3, 59))
    check("不到 4 点不运行", tm.calls == [])
    await ff._heal_thin_episodes(deps, night)
    titles = sorted(c[0] for c in tm.calls)
    check("4 点补抓偏少的 E35、E36，还在按计划重抓的 E40 不补", titles == ["弹幕保鲜: 连看测试 S01E35（弹幕偏少，补抓）", "弹幕保鲜: 连看测试 S01E36（弹幕偏少，补抓）"], titles)
    h = await heal_rows(sf)
    check("记录补抓前的数量", h[play[35]]["count_before"] == 15906 and h[play[36]]["count_before"] == 15818, h)
    tm.calls.clear()
    await ff._heal_thin_episodes(deps, night + timedelta(minutes=5))
    check("同一晚不重复运行", tm.calls == [])
    await ff._heal_thin_episodes(deps, night + timedelta(days=1))
    check("第二晚：补过的不再补", tm.calls == [])
    await ff._heal_thin_episodes(deps, night + timedelta(days=31))
    check("31 天后仍偏少会再试一次", len(tm.calls) == 2, tm.calls)

    tm.calls.clear()
    async with sf() as s:
        await s.execute(ff._heal.delete())
        await s.commit()
    many = {i: (30000 if i % 2 else 9000) for i in range(1, 61)}
    await add_source(sf, "大量偏少", many, {i: night - timedelta(days=5) for i in many}, source_no=5)
    await ff._heal_thin_episodes(deps, night + timedelta(days=40))
    check("一晚最多补 %d 集" % ff.HEAL_LIMIT, len(tm.calls) == ff.HEAL_LIMIT, len(tm.calls))

    print("== 上游修复：已有分集的分集 ID 跟着 URL 更新")
    from src.db.crud.episode import create_episode_if_not_exists
    async with sf() as s:
        a = Anime(title="占位测试", type="tv_series", season=1, createdAt=T0)
        s.add(a); await s.flush()
        src = AnimeSource(animeId=a.id, sourceOrder=1, providerName="tencent", mediaId="m9", createdAt=T0)
        s.add(src); await s.flush()
        # 预下载先用花絮建了第 39 集
        eid = await create_episode_if_not_exists(s, a.id, src.id, 39, "花絮", "https://v.qq.com/x/cover/c/trailer.html", "trailer")
        await s.commit()
        await create_episode_if_not_exists(s, a.id, src.id, 39, "第 39 集", None, "failover")
        await s.commit()
    async with sf() as s:
        check("没有 URL 的调用不改分集 ID", (await s.get(Episode, eid)).providerEpisodeId == "trailer")
        await create_episode_if_not_exists(s, a.id, src.id, 39, "第 39 集", "https://v.qq.com/x/cover/c/real.html", "real")
        await s.commit()
    async with sf() as s:
        e = await s.get(Episode, eid)
        check("正片导入时分集 ID 跟着 URL 更新", e.providerEpisodeId == "real" and e.sourceUrl.endswith("real.html"), (e.providerEpisodeId, e.sourceUrl))

    print("== 总开关")

    class App:
        pass
    app = App(); app.state = App()
    app.state.db_session_factory, app.state.task_manager = sf, tm
    app.state.scraper_manager = app.state.rate_limiter = None
    app.state.config_manager = FakeConfig({ff.ENABLED_KEY: "false"})
    tm.calls.clear()
    set_now(T0 + timedelta(days=400))
    await ff.tick(app)
    check("关闭后定时处理什么都不做", tm.calls == [])
    app.state.config_manager = FakeConfig()
    await ff.tick(app)
    check("开启后定时处理正常运行不报错", True)


async def main():
    pure_tests()
    admin = create_async_engine(URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text("DROP DATABASE IF EXISTS %s" % DB))
        await c.execute(text("CREATE DATABASE %s CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci" % DB))
    engine = create_async_engine(URL + DB + "?charset=utf8mb4")
    try:
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
            # 与正式库一致：库默认 general_ci（新表跟着它），episode 表是 0900_ai_ci
            await c.execute(text("ALTER TABLE episode CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        await db_tests(sf)
    except Exception:
        traceback.print_exc()
        results.append(("测试中途异常", False, ""))
    finally:
        await engine.dispose()
        async with admin.connect() as c:
            await c.execute(text("DROP DATABASE IF EXISTS %s" % DB))
        await admin.dispose()
    failed = [r for r in results if not r[1]]
    print("\n共 %d 项，失败 %d 项" % (len(results), len(failed)))
    for name, _, detail in failed:
        print("  FAIL", name, detail)
    sys.exit(1 if failed else 0)


asyncio.run(main())
