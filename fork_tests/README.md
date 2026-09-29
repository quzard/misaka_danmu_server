# fork 扩展的测试

这两个脚本测试 fork 自己加的功能，在 misaka 镜像的一次性容器里运行，把工作区里改过的文件挂载进去。

- `test_webhooks.py <输出.json>`：把各种 Emby、Jellyfin 的 webhook 负载交给处理器，记录分发出去的任务。对新旧两版各跑一次，对比输出。不需要数据库和网络。
- `test_freshness.py`：弹幕保鲜（`src/fork_freshness.py`）。需要能连上 MySQL，会新建临时数据库 `danmuapi_forktest`，跑完删除，不碰正式的库。

```bash
I=ghcr.io/quzard/misaka_danmu_server:main
docker run --rm --network danmu_default -e MYSQL_ROOT_PASSWORD=... --entrypoint python \
  -v $PWD/fork_tests:/t -v $PWD/src/fork_freshness.py:/app/src/fork_freshness.py:ro \
  -v $PWD/src/db/crud/episode.py:/app/src/db/crud/episode.py:ro \
  $I /t/test_freshness.py
```
