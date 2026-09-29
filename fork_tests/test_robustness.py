"""fork 修的几处数据一致性问题的测试。在 misaka 镜像的一次性容器里运行，用 MySQL 里的临时数据库，跑完删除。

- 合并作品（关联）的冲突解决路径：源编号冲突、选「保留源分集」时不再失败，也不留下错位或丢失的弹幕文件
- 弹幕文件丢失时，刷新即使条数没增加也照常写入
- 海报按内容命名：同一张图重复下载只存一份

用法: python /t/test_robustness.py
环境变量: MYSQL_ROOT_PASSWORD
"""
import asyncio
import os
import sys
import traceback
from datetime import datetime

sys.path.insert(0, "/app")
import src.services  # noqa: E402,F401  与应用启动时的导入顺序一致

import httpx  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker  # noqa: E402

from src.db import models  # noqa: E402
from src.db.crud import reassociation as R  # noqa: E402
from src.db.crud import danmaku as D  # noqa: E402
from src.db.orm_models import Base, Anime, AnimeSource, Episode  # noqa: E402
from src.utils import image_utils  # noqa: E402

DB = "danmuapi_forktest_rb"
URL = "mysql+asyncmy://root:%s@mysql:3306/" % os.environ["MYSQL_ROOT_PASSWORD"]
NOW = datetime(2026, 9, 29)
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  ok   " if cond else "  FAIL ") + name + ((" | " + str(detail)) if detail and not cond else ""))


async def reset(engine):
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    for p in D.DANMAKU_BASE_DIR.rglob("*.xml"):
        p.unlink()


async def seed(sf, episodes):
    """目标作品 1：bilibili(1)、tencent(2)；源作品 2：iqiyi(1)、bilibili(2)。episodes: [(分集 id, 源 id, 集号)]"""
    async with sf() as s:
        s.add_all([Anime(id=1, title="目标", season=1, createdAt=NOW), Anime(id=2, title="源", season=1, createdAt=NOW)])
        await s.flush()
        s.add_all([
            AnimeSource(id=10, animeId=1, sourceOrder=1, providerName="bilibili", mediaId="b1", createdAt=NOW),
            AnimeSource(id=30, animeId=1, sourceOrder=2, providerName="tencent", mediaId="t1", createdAt=NOW),
            AnimeSource(id=20, animeId=2, sourceOrder=1, providerName="iqiyi", mediaId="i2", createdAt=NOW),
            AnimeSource(id=11, animeId=2, sourceOrder=2, providerName="bilibili", mediaId="b2", createdAt=NOW),
        ])
        await s.flush()
        for eid, sid, idx in episodes:
            aid = 1 if sid in (10, 30) else 2
            p = D.DANMAKU_BASE_DIR / str(aid) / f"{eid}.xml"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("<i>%d</i>" % eid)
            s.add(Episode(id=eid, sourceId=sid, title="e", episodeIndex=idx, commentCount=1,
                          danmakuFilePath=f"/app/config/danmaku/{aid}/{eid}.xml"))
        await s.commit()


async def state(sf):
    """返回 (剩下的作品 id, 路径指向不存在文件的分集, 没被引用的文件, 各分集 {id: (作品, 源, 集号)})"""
    async with sf() as s:
        rows = (await s.execute(select(Episode.id, Episode.danmakuFilePath, Episode.episodeIndex, AnimeSource.animeId, AnimeSource.providerName)
                                .join(AnimeSource, Episode.sourceId == AnimeSource.id))).all()
        animes = sorted(a for (a,) in (await s.execute(select(Anime.id))).all())
    refs = {r.danmakuFilePath.split("/danmaku/")[1] for r in rows}
    files = {str(p.relative_to(D.DANMAKU_BASE_DIR)) for p in D.DANMAKU_BASE_DIR.rglob("*.xml")}
    return animes, sorted(refs - files), sorted(files - refs), {r.id: (r.animeId, r.providerName, r.episodeIndex) for r in rows}


async def reassociation_tests(engine, sf):
    print("== 合并作品：冲突解决路径")
    # 源编号冲突：iqiyi 移到目标后与 tencent 的编号撞上（旧代码报 Duplicate entry，且弹幕文件已被挪走）
    await reset(engine)
    await seed(sf, [(25000001010001, 10, 1), (25000001020001, 30, 1), (25000002010001, 20, 1), (25000002020002, 11, 2)])
    req = models.ReassociationResolveRequest(targetAnimeId=1, resolutions=[models.ProviderResolution(providerName="bilibili", episodeResolutions=[])])
    async with sf() as s:
        ok = await R.reassociate_anime_sources_with_resolution(s, 2, req)
    animes, missing, orphans, eps = await state(sf)
    check("源编号冲突：合并成功", ok and animes == [1], (ok, animes))
    check("源编号冲突：没有丢失或错位的弹幕文件", not missing and not orphans, (missing, orphans))
    check("源编号冲突：各分集都归到目标作品", all(a == 1 for a, _, _ in eps.values()), eps)

    # 保留源分集：同一集号两边都有，选保留源（旧代码报 Duplicate entry，且目标分集的文件已被删掉）
    await reset(engine)
    await seed(sf, [(25000001010001, 10, 1), (25000001020001, 30, 1), (25000002020001, 11, 1)])
    req = models.ReassociationResolveRequest(targetAnimeId=1, resolutions=[models.ProviderResolution(
        providerName="bilibili", episodeResolutions=[models.EpisodeResolution(episodeIndex=1, keepSource=True)])])
    async with sf() as s:
        ok = await R.reassociate_anime_sources_with_resolution(s, 2, req)
    animes, missing, orphans, eps = await state(sf)
    check("保留源分集：合并成功", ok and animes == [1], (ok, animes))
    check("保留源分集：留下的是源分集", 25000002020001 in eps and 25000001010001 not in eps, eps)
    check("保留源分集：没有丢失或错位的弹幕文件", not missing and not orphans, (missing, orphans))

    print("== 合并作品：普通路径")
    await reset(engine)
    await seed(sf, [(25000001010001, 10, 1), (25000001020001, 30, 1), (25000002010001, 20, 1), (25000002020002, 11, 2)])
    async with sf() as s:
        ok = await R.reassociate_anime_sources(s, 2, 1)
    animes, missing, orphans, eps = await state(sf)
    check("普通路径：合并成功且文件一致", ok and animes == [1] and not missing and not orphans, (ok, animes, missing, orphans))


async def refresh_tests(engine, sf):
    print("== 弹幕文件丢失时的刷新")
    await reset(engine)
    async with sf() as s:
        s.add(Anime(id=40, title="T", season=1, createdAt=NOW))
        await s.flush()
        s.add(AnimeSource(id=51, animeId=40, sourceOrder=1, providerName="iqiyi", mediaId="i", createdAt=NOW))
        await s.flush()
        # 库里记着路径和 5 条，文件不存在
        s.add(Episode(id=25000040010001, sourceId=51, title="e", episodeIndex=1, commentCount=5,
                      danmakuFilePath="/app/config/danmaku/40/25000040010001.xml"))
        await s.commit()
    comments = [{"cid": i, "p": f"{i}.0,1,16777215,[iqiyi]", "m": f"c{i}"} for i in range(3)]
    async with sf() as s:
        added = await D.save_danmaku_for_episode(s, 25000040010001, comments, None)
        await s.commit()
    f = D.DANMAKU_BASE_DIR / "40" / "25000040010001.xml"
    check("文件丢失：条数没增加也照常写入", added == 3 and f.exists(), (added, f.exists()))
    async with sf() as s:
        added = await D.save_danmaku_for_episode(s, 25000040010001, comments[:2], None)
        await s.commit()
    check("文件还在：条数没增加照旧跳过", added == 0, added)


async def image_tests(sf):
    print("== 海报按内容命名")
    payload = {"a": b"\x89PNG-poster-a", "b": b"\x89PNG-poster-b"}

    def handler(request):
        return httpx.Response(200, content=payload[request.url.path.strip("/")], headers={"content-type": "image/png"})

    real_client = httpx.AsyncClient

    def fake_client(**kw):
        kw.pop("proxy", None)
        return real_client(transport=httpx.MockTransport(handler), **kw)

    image_utils.httpx.AsyncClient = fake_client
    try:
        before = set(image_utils.IMAGE_DIR.glob("*")) if image_utils.IMAGE_DIR.exists() else set()
        async with sf() as s:
            p1 = await image_utils.download_image("http://img.test/a", s, None)
            p2 = await image_utils.download_image("http://img.test/a", s, None)
            p3 = await image_utils.download_image("http://img.test/b", s, None)
        new = set(image_utils.IMAGE_DIR.glob("*")) - before
        check("同一张图两次下载得到同一个路径", p1 and p1 == p2, (p1, p2))
        check("不同的图得到不同的路径", p3 and p3 != p1, (p1, p3))
        check("只多存了两个文件", len(new) == 2, sorted(str(x) for x in new))
    finally:
        image_utils.httpx.AsyncClient = real_client


async def main():
    admin = create_async_engine(URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text("DROP DATABASE IF EXISTS %s" % DB))
        await c.execute(text("CREATE DATABASE %s CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci" % DB))
    engine = create_async_engine(URL + DB + "?charset=utf8mb4")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await reassociation_tests(engine, sf)
        await refresh_tests(engine, sf)
        await image_tests(sf)
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
