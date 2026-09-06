# ADR-0011：持久媒体资源并由服务端运行 Playlist

## 状态

Accepted for implementation on 2026-09-05.

## 背景

ADR-0009 把 Playlist 留在 Agent helper，ADR-0010 则刻意不建立稳定媒体 ID。这适合一次性 URL、
文件和实时 PCM，但 helper 退出后列表无法继续，用户也无法复用资源、查询按 Playlist 组织的历史，
或从明确记录恢复播放。产品研究和三轮线框图评审已经确认，需要把这些能力收回 CastFabric 长期
服务进程，同时保持它是局域网音频投放工具而不是完整媒体库。

## 决策

1. 在现有单进程中增加一个 SQLite repository、一个媒体资源服务和一个 Playlist 服务/runner；
   HTTP 与 MCP 继续共用 Application Service、Web 端口和容器。
2. 业务关系只使用 `media_assets`、`playlists`、`playlist_items`、`playback_runs`、
   `media_sessions`、`activity_events` 六张表。使用显式 schema version、foreign keys、默认
   journal mode 和短事务；不启用 WAL，不增加 ORM、worker 或消息队列。
3. 上传文件按 SHA-256 存入 `<conf>/media/blobs`；短期上传票据只在内存中。外部 URL 保留为
   稳定资源但所有公开投影必须去掉 query/fragment。
4. Playlist 是实时定义，不复制 queue 或 revision 快照。`revision` 只做乐观并发；下一项读取
   当前定义，上一项读取该 run 的实际 session 历史。
5. 每个 target 最多一个活动 run 和一个未结束 session。同一 Playlist 可在多个 target 上独立
   运行。新的普通播放或 Playlist 播放稳定 preempt 该 target 的旧 session/run。
6. 失败记录原因并停止，不自动跳过、重试、换音响或选择备用资源。重启把遗留活动状态记为
   interrupted，绝不自动发声。
7. 续播候选来自 `media_sessions` 最终进度；调用方按 `playlist_id` 查询后显式选择候选、target、
   item 和位置。session/run ID 同时用作延迟控制命令的 fencing。
8. Web 用户面对音响、播放列表和音频资源。播放记录只读；续播只在 Playlist 上下文出现。
9. Skill/helper 删除客户端 Playlist loop 和等待轮询，仅保留一次性播放、持久上传、实时 PCM 与
   一次性 manifest 导入。导入后 SQLite 是唯一事实源。

## 对既有 ADR 的影响

- 本 ADR 只取代 ADR-0009 第 7–8 条“客户端维持 Playlist”和 ADR-0010 的“无稳定 media ID”
  边界。
- ADR-0009 的薄 MCP、同源 `/mcp`、无 sidecar，以及 ADR-0010 的 Play+Seek 原语和 fencing
  继续有效。
- ADR-0005 的可观测字段与隐私规则、ADR-0007 的实体 DMR 拉流确认边界继续有效。

## 明确不采用

- QueueSnapshot、PlaylistRevision、Checkpoint、UploadJob 或 PlaybackEvent 表；
- GraphQL、事件溯源、目录扫描、自动转码、艺术家/专辑/封面/歌词；
- 后台轮询 Skill、动态 Queue、Play Next、多音响同步或自动恢复状态机。

## 验证

- schema、迁移、约束、重启中断与并发 fencing 使用本地测试；
- Playlist 自动切项与 renderer pull 使用 fake DMR/in-process integration；
- HTTP/MCP/Skill/UI 使用契约和端到端测试；
- Home Server 先隔离、再静默部署；真实音箱发声必须另行获得用户许可并独立记录。
