"""在 misaka 镜像的一次性容器里运行：把各种 Jellyfin webhook 负载喂给处理器，记录分发出去的任务。

用法: python /t/test_webhooks.py <输出 json 路径>
"""
import asyncio
import json
import sys
from urllib.parse import urlencode

sys.path.insert(0, "/app")

import src.services  # noqa: E402,F401  与应用启动时的导入顺序一致，避免循环导入
from src.webhook.jellyfin import JellyfinWebhook  # noqa: E402


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    async def get(self, key, default=None):
        return self.values.get(key, default)


class Result:
    def __init__(self, title, season, type="tv_series"):
        self.title, self.season, self.type = title, season, type


class FakeScraper:
    async def search_all(self, keywords):
        # 同名作品两季 + 一个名字相近的其他作品，后者不应被算进季列表
        return [Result("兰香如故", 1), Result("兰香如故 第二季", 2), Result("兰香如故之外传", 3), Result("兰香如故", 1, "movie")]


class FakeRequest:
    def __init__(self, body, content_type="application/json"):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = {"content-type": content_type}

    async def body(self):
        return self._body

    async def json(self):
        return json.loads(self._body)


def make(cls, config=None):
    h = cls(None, None, FakeScraper(), None, None, FakeConfig(config), None, None)
    calls = []
    conflict_keys = (config or {}).get("_conflict_keys", [])

    async def dispatch(task_title, unique_key, payload, webhook_source):
        if unique_key in conflict_keys:
            from fastapi import HTTPException
            calls.append({"conflict": unique_key})
            raise HTTPException(status_code=409, detail="dup")
        calls.append({"title": task_title, "key": unique_key, "payload": payload})

    async def delete(payload, webhook_source):
        calls.append({"delete": payload.get("ItemType") or payload.get("Item", {}).get("Type")})

    h.dispatch_task = dispatch
    h._handle_delete = delete
    return h, calls


async def run(cls, body, config=None, content_type="application/json"):
    try:
        from src.webhook import _jellyfin_fork
        _jellyfin_fork._recent_triggers.clear()
    except ImportError:
        pass
    h, calls = make(cls, config)
    for b in (body if isinstance(body, list) else [body]):
        try:
            await h.handle(FakeRequest(b, content_type), "test")
        except Exception as e:
            calls.append({"raised": f"{type(e).__name__}: {getattr(e, 'status_code', '')}"})
    # 等后台的季探测任务跑完
    for _ in range(50):
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            break
        await asyncio.gather(*pending, return_exceptions=True)
    return calls


JF_EP = {
    "NotificationType": "ItemAdded", "ItemType": "Episode", "Name": "第2集", "ItemId": "ep-1",
    "SeriesName": "兰香如故", "SeriesId": "series-1", "SeasonId": "season-1", "SeasonNumber": 1, "EpisodeNumber": 2,
    "Year": 2025, "PremiereDate": "2026-09-01", "Provider_tmdb": "123", "Provider_imdb": "tt1", "Provider_tvdb": "9",
}
JF_UD = {"NotificationType": "UserDataSaved", "NotificationUsername": "qiu", "Played": False, "Favorite": False, "Likes": False}
JF_SERIES = {"ItemType": "Series", "Name": "兰香如故", "ItemId": "series-1", "Year": 2025, "Provider_tmdb": "555", "Provider_Douban": "db1"}
JF_SEASON = {"ItemType": "Season", "Name": "第 2 季", "ItemId": "season-2", "SeriesName": "兰香如故", "SeriesId": "series-1", "SeasonNumber": 2, "Year": 2025}

CASES = {
    "jf_itemadded_episode": (JellyfinWebhook, JF_EP, None),
    "jf_itemadded_episode_form": (JellyfinWebhook, urlencode({"payload": json.dumps(JF_EP)}).encode(), None, "application/x-www-form-urlencoded"),
    "jf_itemadded_movie_premiere_only": (JellyfinWebhook, {"NotificationType": "ItemAdded", "ItemType": "Movie", "Name": "无双", "ItemId": "m-1", "PremiereDate": "2018-09-30"}, None),
    "jf_itemadded_series_ignored": (JellyfinWebhook, {**JF_SERIES, "NotificationType": "ItemAdded"}, None),
    "jf_itemadded_season_ignored": (JellyfinWebhook, {**JF_SEASON, "NotificationType": "ItemAdded"}, None),
    "jf_ud_progress_ignored": (JellyfinWebhook, {**JF_EP, **JF_UD, "SaveReason": "PlaybackProgress"}, None),
    "jf_ud_finished_ignored": (JellyfinWebhook, {**JF_EP, **JF_UD, "SaveReason": "PlaybackFinished", "Played": True}, None),
    "jf_ud_toggle_unplayed_ignored": (JellyfinWebhook, {**JF_EP, **JF_UD, "SaveReason": "TogglePlayed", "Played": False}, None),
    "jf_ud_toggle_played_episode": (JellyfinWebhook, {**JF_EP, **JF_UD, "SaveReason": "TogglePlayed", "Played": True, "PlayCount": 1}, None),
    "jf_ud_toggle_propagated_version_ignored": (JellyfinWebhook, {**JF_EP, **JF_UD, "SaveReason": "TogglePlayed", "Played": True, "PlayCount": 0}, None),
    "jf_ud_toggle_repeat_deduped": (JellyfinWebhook, [{**JF_EP, **JF_UD, "SaveReason": "TogglePlayed", "Played": True, "PlayCount": 2}] * 3, None),
    "jf_ud_toggle_bulk_three_episodes": (JellyfinWebhook, [{**JF_EP, **JF_UD, "SaveReason": "TogglePlayed", "Played": True, "PlayCount": 1, "EpisodeNumber": n, "ItemId": f"ep-{n}"} for n in (1, 2, 3)], None),
    "jf_ud_toggle_no_season_number": (JellyfinWebhook, {**JF_EP, **JF_UD, "SeriesName": "编辑部的故事", "SeasonNumber": None, "EpisodeNumber": 3, "SaveReason": "TogglePlayed", "Played": True, "PlayCount": 1}, None),
    "jf_ud_toggle_no_season_no_episode_ignored": (JellyfinWebhook, {**JF_EP, **JF_UD, "SeriesName": "快乐驿站", "SeasonNumber": None, "EpisodeNumber": None, "SaveReason": "TogglePlayed", "Played": True, "PlayCount": 1}, None),
    "jf_itemadded_no_season_number": (JellyfinWebhook, {**JF_EP, "SeriesName": "编辑部的故事", "SeasonNumber": None, "EpisodeNumber": 3}, None),
    "jf_ud_favorite_series_probe_s1_conflict": (JellyfinWebhook, {**JF_SERIES, **JF_UD, "SaveReason": "UpdateUserRating", "Favorite": True}, {"_conflict_keys": ["webhook-search-兰香如故-S1-全季"]}),
    "jf_ud_unfavorite_ignored": (JellyfinWebhook, {**JF_SERIES, **JF_UD, "SaveReason": "UpdateUserRating"}, None),
    "jf_ud_favorite_series_probe": (JellyfinWebhook, {**JF_SERIES, **JF_UD, "SaveReason": "UpdateUserRating", "Favorite": True}, None),
    "jf_ud_like_season": (JellyfinWebhook, {**JF_SEASON, **JF_UD, "SaveReason": "UpdateUserRating", "Likes": True, "PremiereDate": "2026-03-01"}, None),
    "jf_ud_favorite_season_no_number_probe": (JellyfinWebhook, {**JF_SEASON, **JF_UD, "SeasonNumber": None, "Name": "Season Unknown", "SaveReason": "UpdateUserRating", "Favorite": True}, None),
    "jf_ud_favorite_movie": (JellyfinWebhook, {**JF_UD, "ItemType": "Movie", "Name": "无双", "ItemId": "m-1", "Year": 2018, "SaveReason": "UpdateUserRating", "Favorite": True}, None),
    "jf_ud_favorite_series_disabled": (JellyfinWebhook, {**JF_SERIES, **JF_UD, "SaveReason": "UpdateUserRating", "Favorite": True}, {"webhookEnabled": "false"}),
    "jf_ud_favorite_series_blacklisted": (JellyfinWebhook, {**JF_SERIES, **JF_UD, "SaveReason": "UpdateUserRating", "Favorite": True}, {"webhookFilterRegex": "兰香"}),
    "jf_item_deleted": (JellyfinWebhook, {**JF_EP, "NotificationType": "ItemDeleted"}, None),
    "jf_item_removed_legacy": (JellyfinWebhook, {**JF_EP, "NotificationType": "ItemRemoved"}, None),
    "jf_playback_start_ignored": (JellyfinWebhook, {**JF_EP, "NotificationType": "PlaybackStart"}, None),
}


async def main():
    out = {}
    for name, case in CASES.items():
        cls, body, config = case[:3]
        content_type = case[3] if len(case) > 3 else "application/json"
        try:
            out[name] = await run(cls, body, config, content_type)
        except Exception as e:  # 记录异常，方便对比
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    with open(sys.argv[1], "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)


asyncio.run(main())
