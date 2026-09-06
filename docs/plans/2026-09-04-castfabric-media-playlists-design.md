# CastFabric 媒体资源、播放列表与可恢复播放设计

状态：领域方案与产品线框图已于 2026-09-05 获批；授权进入生产实现
日期：2026-09-04

## 1. 目标

CastFabric 在现有一次性 URL、文件和实时 PCM 播放之外，增加由服务端长期执行的 Playlist，
并保存足以查询和恢复的播放记录。

产品仍然是局域网音频投放与控制系统，不扩张为完整媒体库。设计优先级依次为：

1. 一个事实源；
2. 少量稳定关系对象；
3. 短而直接的数据流；
4. 失败时明确停止并保留原因；
5. 不为假设场景增加后台任务、队列快照、事件溯源或自动 fallback。

## 2. 已确认的产品边界

- Playlist 是可复用内容定义，不绑定音箱；每次投向一个音箱产生独立 PlaybackRun。
- 同一 Playlist 可以同时投向多个音箱；一个音箱同时只有一个活动 MediaSession。
- 连续播放由 CastFabric 现有长期服务进程负责，Agent 和 Skill 退出后仍继续。
- 音乐与有声书共用一个 Playlist 模型，不建立两套领域对象。
- 支持顺序或随机，以及播完停止或列表循环；第一阶段不支持单曲循环。
- Agent 查询进度记录并选择是否续播；服务端不自动挑选唯一续播点。
- 配置继续保存在 `config.json`；业务关系进入 SQLite；媒体内容进入受管理目录。
- 旧 `activity.jsonl` 和内存 recent sessions 不导入 SQLite，也不主动删除旧文件。
- 不引入 GraphQL、外部数据库、消息队列、独立 worker 或 MCP sidecar。
- 主导航增加“播放列表 / Playlists”；音频文件只是该页面的次级管理入口。
- 内容播放记录属于 Playlist 页面；现有“活动”继续承担协议、输出和系统诊断。
- Web 与 MCP 调用同一 Application Service；浏览器不维护另一套播放状态。

第一阶段明确不做：艺术家、专辑、流派、封面抓取、歌词、在线推荐、目录扫描、RSS/Podcast
下载、多用户权限、动态 Queue 编辑、Play Next、Crossfade、自动转码和多房间精确同步。

## 3. 最小架构

```text
Web Console ── HTTP API ──┐
                          ├─ Application Service ── SQLite / media files
Agent ─────── MCP ────────┘          │
                                     └─ Playlist Runner ── existing PlaybackService

Agent local file / FFmpeg ── thin helper ── HTTP upload / PCM WebSocket
```

系统保持单进程：

- Application Service 持有业务规则；
- HTTP API 和 MCP 只是适配器；
- Playlist Runner 是进程内每个活动音箱一个 asyncio task；
- SQLite 使用一个 repository 层和短事务，写操作在进程内串行化；
- 第一阶段使用 SQLite 默认 journal，不预先引入 WAL、checkpoint 调优或独立数据库线程池。

## 4. 最小数据模型

只增加六类持久对象，不建立 revision 表、运行队列快照表、checkpoint 表、upload job 表或
playback event 表。

### `media_assets`

稳定、可复用的播放资源。

```text
id
source_kind          managed_file | external_url
display_name
description          nullable；用户可编辑短说明
tags_json            用户可编辑轻量标签数组；不建立标签表
original_filename    managed_file 可选；只作来源说明
content_type
size_bytes           nullable
duration_seconds     nullable
content_hash         managed_file 使用；external_url 为空
source_value         blob 相对定位或完整 URL
status               available | unavailable | deleted
created_at
updated_at
deleted_at           nullable
```

- `managed_file` 由 CastFabric 保存和校验；相同 SHA-256 只存一份内容。
- `external_url` 只保存定位，不下载、不刷新签名、不承诺远端可用。
- URL 原值只用于播放；API、MCP、活动和错误默认返回脱敏形式。
- 展示名称、说明和标签可编辑；原始文件名、探测格式、哈希和来源类型由系统维护。
- 上传 blob 不原地替换；external URL 只能通过显式“更新链接”改变定位并检查活动引用冲突。
- 删除文件后保留 tombstone 行，历史关系仍可查询。

### `playlists`

```text
id
name
description          nullable
default_order        sequential | random
default_repeat       none | all
revision             integer
created_at
updated_at
archived_at          nullable
```

`revision` 只是一个递增整数，用于避免 Web 与 Agent 相互覆盖；不保存旧版本内容。

### `playlist_items`

```text
id
playlist_id
asset_id
position
title                nullable
created_at
removed_at           nullable
```

item 标题属于 Playlist 上下文，同一 asset 在不同 Playlist 中可以有不同标题。移除使用
`removed_at`，只为保留历史关联，不提供恢复站或版本浏览界面。

### `playback_runs`

Playlist 投向一个音箱后产生的一次长期执行。普通 URL、一次性文件、PCM、AirPlay、DLNA
或 MiPlay 播放不创建 PlaybackRun。

```text
id
target_id
playlist_id
order_mode           sequential | random
repeat_mode          none | all
cycle_number
state                active | ended
end_reason           completed | stopped | preempted | failed | interrupted | null
started_at
updated_at
ended_at             nullable
```

一个 target 最多一条 `state != ended` 的 PlaylistRun。任何新的 Playlist 或普通播放都会把该
音箱上的旧 MediaSession 结束为 `preempted`；如果它属于 Playlist，同时结束旧 run，不保存或
恢复旧队列。

### `media_sessions`

一次实际媒体播放记录。普通播放直接产生一条独立 MediaSession；PlaylistRun 每播放一个 item
产生一条关联 MediaSession。

```text
id
run_id               nullable；普通播放为空
target_id
asset_id             nullable；一次性文件或 PCM 可以为空
playlist_item_id     nullable
item_title_snapshot  nullable
source_type
source_label         nullable；只保存可展示、已脱敏摘要
cycle_number         nullable
state                starting | playing | paused | ended
position_seconds     nullable
duration_seconds     nullable
seek_supported       boolean
started_at
updated_at
ended_at             nullable
end_reason           completed | stopped | skipped | failed | preempted | interrupted | null
error_code           nullable
```

每个 target 最多一条未结束 MediaSession；一个 PlaylistRun 下也最多一条未结束 MediaSession。
这条 session 就是当前 item 和当前播放状态，不在 PlaybackRun 重复保存指针或状态。
MediaSession 的最终位置就是续播 checkpoint，不另建 checkpoint 表。

### `activity_events`

替代新的 `activity.jsonl` 写入，继续保存协议、输出和系统诊断。它可以关联 `run_id` 或
`session_id`，但不承担 Playlist 进度恢复，也不建立完整事件溯源模型。

## 5. Playlist 定义与活动播放

Playlist 始终只有一个当前定义。活动 run 不复制完整列表：

- 顺序模式的下一项读取当前未移除 items 的最新 position；
- 随机模式从当前 cycle 尚未播放的 items 中选择；已播放集合由该 run 的 MediaSession 判断；
- 上一项读取该 run 的实际 MediaSession 历史；
- 列表循环结束时 `cycle_number + 1`；不循环则结束 run；
- 新增、重排和删除非当前 item 立即影响后续导航，但不中断当前声音。

只有三种修改会影响正在发声的内容：删除当前 item、替换当前 item 的 asset、归档整个
Playlist。服务默认拒绝并返回：

```json
{
  "code": "ACTIVE_PLAYBACK_CONFLICT",
  "affected_runs": [{"run_id": "...", "target_id": "...", "session_id": "..."}],
  "allowed_resolutions": ["keep", "reload", "stop"]
}
```

- `keep`：定义照常修改，当前声音播完后再使用新定义；
- `reload`：删除当前项时切到下一项，替换资源时从新资源开头重播本项；
- `stop`：先结束相关 runs，再完成修改。

取消由客户端处理，不发送第二次 mutation。MCP 与 Web 使用相同冲突结构。

## 6. 启动、切换和进度数据流

### 启动 Playlist

```text
validate playlist / item / target
  → 在一个 SQLite 事务中创建 PlaybackRun(active) + 第一条 MediaSession(starting)
  → 调用现有 PlaybackService 播放
  → 成功：session=playing
  → 失败：关闭 session 和 run，end_reason=failed
```

数据库写入失败时不向音箱发起新播放。音箱调用成功但最终状态写入失败时，不反向执行复杂
补偿；当前声音可以继续，但 runner 停止切换下一项并报告存储故障。

### 当前 item 正常结束

```text
关闭当前 MediaSession(completed)
  → 按当前 Playlist 定义选择下一项
  → 创建下一条 MediaSession(starting)
  → 播放
```

如果无法可靠判断是正常播完还是外部中断，结束 run 为 `interrupted`，不猜测、不自动下一项。

### 进度

- Runner 在活动播放期间按固定实现间隔查询现有输出状态；该间隔不进入用户设置。
- 活动位置更新当前 MediaSession；start、pause、resume、seek、item end 和 run end 时立即写入。
- MCP/Web 查询活动 run 时返回当前投影及 `observed_at`；不提供 WebSocket 订阅或长 MCP 调用。
- 服务崩溃可能损失最后一个短间隔的进度，这是首版接受的明确限制。
- 重启时把遗留 active run 标为 `interrupted`，绝不自动恢复发声。

续播由调用方完成：先按 `playlist_id` 查询候选记录，再显式调用
`start_playlist(playlist_id, target_id, start_item_id, start_position_seconds,
resumed_from_session_id?)`。旧 item 已移除时返回 `NOT_FOUND`，不自动替换候选。

## 7. 控制边界

| 对象 | 第一阶段控制 |
|---|---|
| OutputTarget | 音量 |
| 普通 MediaSession | 暂停、恢复、停止；能力允许时 seek |
| PlaylistRun | 暂停、恢复、停止、上一项、下一项、选择指定 item；能力允许时 seek 当前 session |

- URL、一次性文件、PCM、AirPlay、DLNA 和 MiPlay 等普通播放没有上下项。
- `pause` 不支持时直接返回 `UNAVAILABLE`，不模拟成 stop。
- `seek` 必须携带已知 `session_id`，避免延迟命令移动了新媒体。
- Playlist 导航携带 `run_id`，音量继续针对 `target_id`。

进度显示只看真实能力：

- position + duration + seek：可拖动进度条；
- position + duration、无 seek：只读进度条；
- 只有 position：只显示已播放时间；
- 均不可靠或实时 PCM：不显示进度条。

## 8. 媒体上传与删除

现有 `play_file` 保留为“一次上传、立即播放、会话结束后清理”。持久文件使用独立流程：

```text
begin_media_upload(filename, content_type, size_bytes)
  → upload_id, upload_url, expires_at, max_bytes

PUT upload_url [raw bytes]
  → 校验大小和真实音频内容
  → 计算 SHA-256，移动到受管理目录
  → 创建或复用 MediaAsset
  → 返回 asset_id
```

`upload_id` 是内存中的短期票据，不进入 SQLite。第一阶段不做分片、断点续传、后台探测或
转码；进程中断后重新上传。文件名和客户端 MIME 只作显示提示，不能决定存储路径或合法性。

存储位置固定为：

```text
<conf-path>/castfabric.sqlite3
<conf-path>/media/blobs/<sha256>
<conf-path>/media/uploads/<upload-id>.part
```

上传失败删除 `.part` 且不创建 asset。SQLite 与文件 rename 无法成为同一事务，因此只做一次
直接清理：数据库插入失败时删除本次新建 blob；不增加文件操作日志或恢复状态机。极端进程
崩溃留下的 orphan blob 不影响关系正确性，可由将来的显式存储检查处理，首版不后台扫描。

删除规则：

- 移除 PlaylistItem 或归档 Playlist 都不删除 MediaAsset；
- asset 仍被有效 item 引用或活动 session 使用时拒绝删除并返回引用；
- 无有效引用且未播放时允许删除 blob，并把 asset 标为 `deleted`；
- 无引用稳定资源只允许预览后显式清理，不自动 GC；
- 丢失、损坏或 URL 失效只标记 `unavailable`，不删除 Playlist 或历史。

## 9. 简单失败原则

系统没有备用资源、自动重连、指数退避、静默跳过或多级补偿。统一规则如下：

| 场景 | 处理 |
|---|---|
| 输入、ID、revision 或 fencing 不正确 | 不改变任何状态，返回错误 |
| 上传中断、超时或格式非法 | 删除临时文件，不创建 asset |
| asset 丢失或 URL 播放失败 | 当前 session 结束；所属 PlaylistRun（如有）也结束为 failed |
| 音箱离线或拒绝命令 | 当前 session 失败；所属 PlaylistRun（如有）结束，不自动换音箱 |
| Playlist item 播放失败 | run 停在该 item 并结束为 failed，不自动跳过 |
| 无法判断自然结束还是外部停止 | run 结束为 interrupted，不猜测下一项 |
| 新播放抢占旧播放 | 旧 session 结束为 preempted；所属 PlaylistRun 同时结束 |
| 服务重启 | 遗留 session/run 结束为 interrupted，不自动发声 |
| 数据库写入失败 | 不开始新的输出动作；活动 runner 停止继续导航 |
| 编辑影响当前媒体 | 返回一个统一 conflict，由调用方选择 keep/reload/stop |

错误契约只保留少量顶层类别：`INVALID_INPUT`、`NOT_FOUND`、`CONFLICT`、`UNAVAILABLE`、
`STORAGE_ERROR`。具体稳定原因放在 `reason`，相关 `run_id/session_id/asset_id` 放在
`details`；不为每个分支建立一个新错误类型。

Web 错误表现也保持一致：当前区域显示一句原因和最多一个主要恢复动作，例如“重试”、
“选择其他音箱”或“下一项”。不创建自动恢复向导。

## 10. MCP、Skill 与 helper

边界采用“完整 MCP 契约 + 薄 Skill + 本地数据面 helper”。

### MCP

MCP 暴露完整、短调用的业务语义：

```text
list/get/create/update/archive playlist
add/update/remove/reorder playlist item
list/get/update/create-url/update-url/delete/play media asset
begin media upload
start/get/control playlist run
get playlist progress
query playback history
```

具体实现可以合并相近 mutation，避免工具数量膨胀，但输入必须是强类型操作，不能接受 SQL、
GraphQL 字符串或任意补丁路径。`start_playlist` 立即返回 run_id，不等待播放结束。

MCP 不读取 Agent 本地路径、不接收 Base64 大文件、不运行 FFmpeg、不保持进度长连接，也不
替用户选择音箱、Playlist、续播记录或冲突处理策略。

### Skill

Skill 只保存影响 Agent 决策的非显然工作流：

- 模糊名称先查询候选，必要时让用户消歧；
- “随机”只选择 `order_mode=random`，具体执行由服务端负责；
- “继续”先查询进度候选，再由 Agent 选择；
- 当前项冲突需要解释影响并取得 keep/reload/stop；
- 本地文件、实时 PCM 和 manifest 导入需要 helper。

Skill 不缓存状态、不轮询、不运行 Playlist、不复制完整 MCP schema。

### helper

```text
play-file        本地文件 → 一次性播放上传
upload-file      本地文件 → 持久 MediaAsset
stream           FFmpeg/stdin → PCM WebSocket
import-playlist  本地 manifest → 一次性创建服务端 Playlist
```

`import-playlist` 不是同步器。导入后 SQLite 是唯一事实源；本地文件后续变化不会自动覆盖。
当前客户端 `playlist --loop` 和 `waitUntilStopped()` 在服务端 Playlist 上线后删除。实时 stream
是唯一长连接例外，因为 helper 正在提供客户端产生的字节，而不是维持服务端业务状态。

## 11. Web 产品面

### 总览

- 保留锁定文案 `不挑协议，投了就播` 和现有声路结构。
- 当前声路显示 Playlist、item、状态和真实进度。
- 普通播放只显示暂停/恢复、停止、音量和能力允许的 seek。
- Playlist 额外显示上一项、下一项和进入列表；不在总览编辑或上传。
- 可显示少量最近续播入口，完整记录进入 Playlist 页面。

### 音响

- 显示该音响当前 run、Playlist、item 和状态。
- 保持 Receiver Suite 与音响启停职责。
- 不在此处维护 Playlist 内容。

### 播放列表

- 一级页面包含“播放列表”和“播放记录”两个视图。
- Playlist 集合显示名称、item 数、总时长、默认模式、活动音响数和更新时间。
- 详情包含 items、上传/选择资源、重排、播放到音响、活动 runs 和最近记录。
- “音频文件”作为次级抽屉或子视图，显示名称、类型、时长、大小、引用数、最近使用和状态。
- 编辑影响当前 item 时才弹一次明确确认；普通新增、重排和非当前删除不阻塞。

### 活动与 AI 接入

- 活动继续显示协议、输出和系统诊断，可链接到关联 run/session。
- AI 接入只更新能力说明、MCP 接入与 Skill 安装，不管理内容。

### 配置

第一阶段不增加轮询周期、SQLite 模式、清理周期、媒体目录或自动重试配置。资源视图可以只读
显示存储位置和占用；容量上限使用实现常量，出现真实用户需求后再决定是否开放配置。

正式 UI 实现前仍需制作断开生产 API 的评审原型，验证桌面、移动、中英、空、加载、降级、
冲突和错误状态。

## 12. 数据迁移与发布边界

- 首次启动创建 SQLite schema 和受管理媒体目录；使用显式 schema version 做顺序迁移。
- `config.json`、音响配置和秘密信息不迁入数据库。
- 新活动写入 SQLite；旧 `activity.jsonl` 不导入、不继续追加，也不自动删除。
- 当前 Skill 本地 Playlist 文件不自动导入；用户或 Agent 可显式运行一次 `import-playlist`。
- ADR 0009/0010 的“无服务端 Playlist、无持久 media ID”边界需要由一份新 ADR 明确取代。
- 上线前不承诺兼容本讨论期间未发布的中间 schema。

## 13. 验收标准

### 数据与运行

- 同一 Playlist 能在两个音箱形成独立 run，进度互不覆盖。
- 关闭 Agent 或 helper 后，服务端 Playlist 继续播放。
- 服务重启不自动发声，但历史进度可按 playlist_id 查询。
- 新播放稳定抢占同音箱旧 run/session；旧控制命令不能影响新 run/session。
- 新增、重排和非当前删除不中断播放；当前项修改只出现一个 conflict。
- 顺序、随机、播完停止和列表循环均只使用实时 Playlist 定义与 MediaSession 历史。

### 资源

- 重复上传不重复占用 blob；失败上传不产生 MediaAsset。
- 被引用或正在播放的资源不能删除；删除无引用资源不破坏历史查询。
- 文件丢失或 URL 失效不会导致 Playlist 被自动删除。

### 简洁性

- SQLite 只有本设计列出的六类业务表；没有 QueueSnapshot、Revision、Checkpoint、UploadJob
  或 PlaybackEvent 表。
- 没有 GraphQL、消息队列、独立 worker、自动重试、备用资源或静默跳过。
- Web API 与 MCP 共享应用服务；Skill/helper 不保存服务端业务状态。
- 所有失败都落入一个明确结束状态和一个稳定原因，不形成多层 fallback 分支。

## 14. 待审阅结论

当前没有必须单独裁决的产品分歧。方案已按“失败即停、显式恢复、少对象、无隐藏 fallback”
统一收口。整体获批后，下一步是先制作信息架构和状态原型，再编写 ADR 与实施计划；在原型
获批前不修改生产 UI、API 或运行时代码。

## 15. 产品工作台评审修订

首轮原型被否决：它按 `Playlist`、`PlaybackRun`、`MediaSession` 等后端对象陈列信息，形成了
数据库管理台，而不是用户整理和播放内容的工作台。以下修订取代第 11 节中含糊的页面表达：

- “播放列表”采用内容工作台：左侧选择 Playlist，右侧直接完成改名、添加内容、重排、删除、
  全部播放和从指定 item 播放。
- “全部播放”是 Playlist 级主动作；每个 item 只有一个清晰的“从此项播放”快捷动作。两者共用
  轻量选音响弹窗，不把 Playlist 绑定到某台音响。
- 选音响弹窗展示在线/离线和当前播放。目标已有声音时，提交前明确说明新播放会替换当前播放，
  但不引入新的确认向导。
- 播放记录只是历史事实：时间、Playlist/item、音响、持续时间和结束原因。记录行不得提供继续、
  重播或其他播放动作。
- 可恢复进度仍是服务端能力，但 Web 入口属于 Playlist 详情的上下文提示；用户从该 Playlist
  发起播放时选择“从头”或“从上次位置”，不得把“继续”塞进播放记录。
- 播放记录是 Playlist 页面内的次级视图，不进入主导航。
- 总览继续以声路为主，回答“现在什么内容通过什么入口投到了哪台音响”；不展示 run、session、
  fencing 或“控制边界”等实现术语。
- 音响页以发现、就绪、启停、命名和当前声音为主；不复制 Playlist 编辑功能。
- 音频文件只在“添加内容”和次级资源管理中出现，不与 Playlist 集合争夺首页主层级。

完整用户任务、音频资源元数据、搜索筛选、编辑态与入口职责记录在
[`2026-09-04-castfabric-media-playlists-product-audit.md`](2026-09-04-castfabric-media-playlists-product-audit.md)
中。关键路径线框图 `castfabric-server-playlists-product-flow-v3.html` 已获批，作为生产功能与
交互边界；视觉实现继续复用现有控制台语言，不把线框图的演示数据或评审控件带入生产。
