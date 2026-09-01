# CastFabric MCP 与 Agent Skill 设计

## 目标

在不重写播放逻辑、不引入 TTS、媒体库或服务器播放列表的前提下，把 CastFabric 当前
已经具备的输出音响管理、URL 播放、文件播放、实时 PCM 和播放控制能力完整暴露给
AI Agent。

交付由三部分构成：

1. CastFabric 内的薄 MCP 适配层；
2. 帮助 Agent 处理本地文件、FFmpeg、实时输入和播放列表的 CastFabric Skill；
3. 控制台内只读的 AI 接入向导。

## 范围

### 包含

- 查询系统状态；
- 列出已配置和扫描发现的输出音响；
- 主动扫描局域网 DLNA 输出；
- 加入、启用、停用和重命名输出音响；
- 按 `target_id` 播放 URL、有限文件或实时 PCM；
- 查询状态、暂停、停止和设置音量；
- Node.js helper 的文件、实时源、顺序播放和循环播放；
- Codex、Claude Code 和通用 MCP 客户端的复制接入内容。

### 不包含

- TTS Provider 或文字转语音；
- CastFabric 服务端播放列表、队列或媒体库；
- 恢复播放、上一首、下一首和多房间同步；
- 新的 OAuth、权限中心或播放策略配置；
- 为 URL 或文件新增自动转码能力；
- 改善实体音箱固件导致的实时流预读延迟。

## 领域对象

### OutputTarget

`OutputTarget` 是管理、播放和控制的唯一核心对象。所有公开接口沿用当前
`normalize_target_id()` 生成的 `target_id`，不创建第二套 ID。

```json
{
  "target_id": "uuid:01234567-89ab-cdef-0123-456789abcdef",
  "kind": "dlna",
  "name": "客厅音箱",
  "receiver_alias": "CastFabric · 客厅音箱",
  "configured": true,
  "enabled": true,
  "online": true,
  "observed_at": "2026-09-01T20:00:00+08:00",
  "capabilities": ["AVTransport", "RenderingControl"],
  "suite_health": "healthy"
}
```

字段语义：

- `configured=false`：本次或最近一次扫描发现，但尚未写入 CastFabric 配置；
- `configured=true, enabled=false`：已经保存，但不发布 Receiver Suite；
- `configured=true, enabled=true`：为该目标发布 CastFabric 接收入口；
- `online=null`：尚未完成过扫描，不能推断是否在线；
- `online=true/false`：最近一次完整扫描中存在/不存在；
- `capabilities`：扫描实际观察到的服务，不推断音箱未声明的能力。

现有 `/api/v1/targets` 需要显式补充 `configured`，其他字段继续复用当前数据契约。

### PlaybackSource

播放来源是区分明确的联合类型，而不是泛化的“媒体对象”。

```text
UrlSource       = { type: "url", url }
FileSource      = { type: "file", filename, mime_type, data_base64 }
PcmStreamSource = { type: "pcm_stream", sample_format, sample_rate, channels }
```

MCP 为三种来源保留独立工具，以获得更简单、对 Agent 更明确的输入 Schema；Skill 的
播放列表格式复用相同的 `type` 判别语义。

### MediaSession

MCP 播放继续使用现有 `MediaSessionCoordinator`，而不是引入 Operation 模型。最小会话
字段为：

```json
{
  "session_id": "...",
  "target_id": "uuid:...",
  "protocol": "mcp",
  "state": "starting",
  "media": {"format": "audio/mpeg"},
  "started_at": "..."
}
```

状态沿用 `starting / playing / paused / stopped / failed`。文件和 PCM 输出仍以实体音箱
实际请求 CastFabric HTTP 地址作为可验证的输出边界；直接 URL 只能报告控制命令和
音箱自身的传输状态，不伪造拉流证据。

## MCP 工具契约

### 管理工具

#### `get_system_status`

无参数。返回当前 `/api/v1/system` 的公开、脱敏字段。

#### `list_outputs`

无参数。返回 `OutputTarget[]` 和当前 discovery 状态。结果包含已配置目标与最近一次
扫描发现但未配置的目标。

#### `scan_outputs`

无参数。复用现有原子扫描：扫描期间不清空旧列表；成功后一次性替换 observation
快照。扫描正在进行时返回现有 `DISCOVERY_BUSY`。

#### `update_output`

```json
{
  "target_id": "uuid:...",
  "name": "可选",
  "receiver_alias": "可选",
  "enabled": true
}
```

只允许现有 PATCH 已支持的字段。对扫描发现但尚未配置的目标，第一次更新会创建配置；
没有发现记录的未知 ID 返回 `TARGET_NOT_FOUND`。第一版不提供删除。

### 播放工具

#### `play_url`

```json
{"target_id": "uuid:...", "url": "https://example/audio.mp3"}
```

直接调用目标的 `play_url()`；CastFabric 不代理、不下载、不转码 URL。

#### `play_file`

```json
{
  "target_id": "uuid:...",
  "filename": "notice.mp3",
  "mime_type": "audio/mpeg",
  "data_base64": "..."
}
```

数据只写入临时播放文件，并通过不可枚举的临时 HTTP 路径交给现有 `play_url()`。
会话结束、失败、超时或服务关闭后删除。文件大小采用实现常量限制，不增加产品配置项。

#### `open_pcm_stream`

```json
{
  "target_id": "uuid:...",
  "sample_format": "s16le",
  "sample_rate": 48000,
  "channels": 2
}
```

第一版只接受上述固定格式；不接受编码 MP3/AAC 流。成功时返回：

```json
{
  "session_id": "...",
  "stream_id": "...",
  "upload_url": "ws://castfabric-host/audio/streams/...",
  "format": {
    "sample_format": "s16le",
    "sample_rate": 48000,
    "channels": 2
  }
}
```

WebSocket 每个 binary frame 都是连续 PCM 字节。text frame、格式不匹配、目标断开或
第二个 writer 必须失败。WebSocket 正常关闭结束会话；`stop` 可从控制面主动关闭。
队列和背压继续沿用现有有界 `CastFabricLiveAudioSink` 行为。

### 控制工具

#### `get_playback_status`

参数为 `target_id`，复用 `PlaybackTarget.get_status()`，返回规范化 `state` 和 `volume`。

#### `pause`

参数为 `target_id`，复用当前 pause 语义。部分实体音箱会把 pause 退化为 stop，MCP 不
声称能够恢复。

#### `stop`

参数为 `target_id`，停止当前输出；如果目标拥有 MCP PCM 会话，同时关闭写入连接。

#### `set_volume`

参数为 `target_id` 和 `volume`，范围沿用当前 `0..100` 归一化。

### 返回和错误

普通成功不引入异步 Operation：

```json
{"ok": true, "target_id": "uuid:...", "state": "playing"}
```

工具错误保留稳定错误码并附可读说明：

```json
{
  "ok": false,
  "error": {"code": "TARGET_OFFLINE", "message": "输出音响当前不可达"}
}
```

MCP transport/schema 错误与业务工具错误分开；业务错误作为 tool error 返回，使 Agent
能够修正目标 ID、重新扫描或选择其他输出。

## CastFabric Agent Skill

### 结构

```text
skills/castfabric/
├── SKILL.md
├── agents/openai.yaml
├── scripts/
│   └── castfabric.mjs
└── references/
    └── playlist-schema.md
```

Skill 保持自动可发现。`SKILL.md` 只描述选择输出、选择 URL/文件/实时 PCM 路径、停止
顺序以及错误处理。Node helper 承担确定性的文件和进程工作。

### helper 命令面

```text
castfabric.mjs outputs list|scan
castfabric.mjs play-url --target <id> <url>
castfabric.mjs play-file --target <id> <path>
castfabric.mjs stream --target <id> --input <path-or-url>
castfabric.mjs stream --target <id> --stdin
castfabric.mjs playlist --target <id> <playlist.json> [--loop]
castfabric.mjs status|pause|stop|volume --target <id> [value]
```

- 普通文件优先 `play-file`，不为了“实时”而走 PCM；
- 连续生成的音频、stdin 或必须按实时速度消费的来源使用 `stream`；
- `stream` 检查 FFmpeg，使用 `-re`（文件/URL）、`pcm_s16le`、48 kHz、双声道输出到
  stdout，再把 stdout 块写入 `open_pcm_stream` 返回的 WebSocket；
- helper 使用 MCP 客户端调用原子工具，不复制 CastFabric 业务规则；
- Ctrl-C/SIGTERM 先关闭数据连接，再调用 `stop`，最后退出 FFmpeg；
- 播放列表状态只存在于 helper 进程；停止循环时先停止 runner，再停止音响。

### 播放列表格式

```json
{
  "version": 1,
  "items": [
    {"type": "file", "path": "./01.mp3", "title": "第一段"},
    {"type": "url", "url": "https://example/02.mp3", "title": "第二段"}
  ]
}
```

数组顺序就是播放顺序。是否循环由 CLI `--loop` 决定，使同一列表可以一次播放或循环。
helper 等待目标从 playing/paused 回到 stopped 后进入下一项。外部停止列表时必须终止
runner，避免 stopped 被解释为自然播完。

## AI 接入页面

### UI Vocabulary 与信息架构

- 一级导航项：`AI 接入 / AI Access`；
- `service status card`：MCP 运行状态与 endpoint；
- `client tabs`：Codex、Claude Code、通用 MCP；
- `read-only code block` + `copy button`：安装命令；
- `copy prompt button`：生成供 Agent 执行的安装提示词；
- `skill install card`：Skill 作用、安装入口和 FFmpeg 条件；
- `verification callout`：安装后只调用 `list_outputs`，不自动出声。

页面不是设置表单，不提供 MCP 端口、TTS、播放策略或权限配置。

### 状态与交互

| 状态 | 表现 |
|---|---|
| loading | endpoint 和命令使用 skeleton，不展示半成品地址 |
| ready | 显示局域网可访问 endpoint 与复制操作 |
| unavailable | 说明 MCP 未启动并提供本地诊断信息，不生成错误命令 |
| copy success | 按钮短暂显示“已复制”，通过 polite live region 通知 |
| copy failure | 保留原内容，显示可选择文本和明确错误 |

复制按钮使用原生 `button`、可访问名称和键盘焦点；client tabs 使用正确 tablist/tab/
tabpanel 语义。桌面为两栏接入信息，移动端改为单列并允许代码块横向滚动。所有文案提供
完整中英文映射，复用现有温暖明亮主题 token，不另建 AI 紫色视觉体系。

### 复制提示词

提示词必须使用浏览器当前访问 CastFabric 的可达主机生成 endpoint，不硬编码开发 IP：

```text
请连接我的 CastFabric MCP 服务：<endpoint>。安装完成后调用 list_outputs 验证连接，
只列出音响，不要播放声音。然后安装 CastFabric Skill，以支持本地文件、实时 PCM 和
播放列表。
```

## 验证

### 契约测试

- `target_id` 规范化、未知目标、已发现未配置、已配置未在线；
- 扫描 busy、失败时保留旧 observation、成功后原子替换；
- update 只接受现有字段并验证启停回滚；
- URL 调用只触发一次现有 `play_url()`；
- 文件临时路径不可枚举且在所有结束路径清理；
- PCM WebSocket 拒绝 text frame、第二 writer 和错误格式；
- PCM 写入真实复用 `CastFabricLiveAudioSink`，输出拉流未发生时失败；
- pause/stop/volume 保持现有适配器行为。

### Skill 测试

- Node helper 能列出和扫描输出；
- 文件字节经 Base64 完整抵达临时媒体端点；
- FFmpeg 固定输出 s16le/48 kHz/2ch；
- stdin、文件和 URL 三类实时输入均可停止且无孤儿 FFmpeg；
- 播放列表保持顺序，`--loop` 循环，SIGINT 不启动下一项；
- MCP 错误以非零退出码和简洁 stderr 返回，不打印文件内容或凭据。

### 集成与真机

1. MCP Inspector 验证工具 Schema 和返回；
2. Codex 与 Claude Code 分别安装并调用 `list_outputs`；
3. Agent 主动扫描、选择 `target_id`、启用已发现音响；
4. 真机验证 URL、MP3 文件、FFmpeg 文件实时 PCM 和 stdin PCM；
5. 验证状态、暂停、停止和音量；
6. 控制台接入页按 NameThatUI 实现契约与 DesignQM D1-D6 截图、键盘、移动端和测试证据验收。

## 实施顺序

1. 补齐 `OutputTarget.configured` 与 MCP session protocol 数据契约；
2. 提取供 HTTP API 与 MCP 共用的应用命令入口；
3. 实现管理与控制工具；
4. 实现 URL、临时文件与 PCM WebSocket 三种播放路径；
5. 创建并验证 CastFabric Skill 与 Node helper；
6. 设计、实现并验证 AI 接入页面；
7. 在本地 Agent、MCP Inspector 和 Home Server 真机完成端到端验收；
8. POC 通过后再更新 README、Landing Page、组织仓库和发布口径。
