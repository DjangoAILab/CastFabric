# CastFabric Runtime v2 技术设计

## 需求与约束

Runtime v2 支持 1–16 台局域网输出音响，每台独立发布虚拟 DLNA、AirPlay、MiPlay；同一
音响一次只接受一个拥有输出的会话，不同音响允许并行。标准 DLNA 不依赖小米账号。

非功能目标：只读 API p95 小于 100ms；扫描异步且不清空旧快照；事件内存上限 500 条、
JSONL 默认 5 MiB × 3；任一入口启动失败不影响其他入口；停止后不得遗留 socket、ffmpeg
或 HTTP stream；API 永不返回凭据、完整媒体 URL query 或完整客户端地址。

## 组件

```text
TargetDiscoveryRegistry ───────────────┐
                                      ▼
Config.targets ─▶ ReceiverSuiteRegistry ─▶ SystemSnapshotProjector ─▶ /api/v1/*
                       │        │
       DLNA/AirPlay/MiPlay      └─▶ MediaSessionCoordinator
                       │                    │
                       ▼                    ▼
                PlaybackTarget       ActivityEventJournal
```

### `TargetDiscoveryRegistry`

串行执行扫描，状态为 `idle/scanning/ready/error`。扫描开始时保留上一份 observation；完成
后原子替换，并记录 `observed_at`。已配置但未出现的目标返回 `online=false`，从未完成扫描
时返回 `online=null`，避免把未知写成离线。

### `ReceiverSuiteRegistry`

维护 `dict[target_id, ReceiverSuite]`。Suite 包含目标只读身份、controller、DLNA renderer、
AirPlay wrapper、MiPlay receiver、入口状态和当前 session id。启停通过 suite lifecycle
执行；共享 DLNA server 支持增删 renderer。启动顺序 DLNA → AirPlay → MiPlay，某一步失败
只记录该入口错误并继续。

### `MediaSessionCoordinator`

每目标一个 `asyncio.Lock`。`begin()` 若已有会话则记录 `session.preempted` 并请求旧 ingress
停止；`transition()` 只接受当前 session id，旧回调不会污染新会话；`end()` 清除 owner。
来源字段包含 `value/provenance/confidence`，缺失永远返回 null。

### `ActivityEventJournal`

事件由 session/output 边界主动发出。写入前调用 redactor：媒体 URL 仅保留 scheme、host、
path 类型摘要；客户端地址哈希或截断；details 使用字段白名单。JSONL 写失败只影响持久化，
内存事件和播放链路继续工作。

## API v1

| Method | Path | 责任 |
|---|---|---|
| GET | `/api/v1/system` | 安全系统快照和聚合计数 |
| GET | `/api/v1/targets` | 持久化目标 + 最近 observation + suite 摘要 |
| POST | `/api/v1/targets/scan` | 发起/等待一次扫描，409 表示已有扫描 |
| PATCH | `/api/v1/targets/{id}` | name、receiver_alias、enabled 白名单修改 |
| GET | `/api/v1/suites` | 每目标三入口状态、端口和当前会话引用 |
| GET | `/api/v1/sessions` | 当前/近期会话，默认只返回 active |
| GET | `/api/v1/events` | target/protocol/outcome/limit/cursor 过滤 |
| GET | `/api/v1/events/{id}` | 单条脱敏事件详情 |
| GET | `/api/v1/settings` | 控制台允许读取的白名单配置 |
| PATCH | `/api/v1/settings` | 分区白名单更新，返回 restart_required |
| GET | `/api/v1/diagnostics/export` | 脱敏诊断包 |

错误体固定为 `{"error":{"code":"...","message_key":"...","details":{}}}`。旧 API 在
迁移发布中继续存在，但生产 v6 只调用 v1。

## 配置迁移

`OutputTargetConfig` 新增 `receiver_alias`，缺失时动态使用
`format_device_name(prefix, target.name)`。读取旧 `default_target_id` 只确保对应目标已启用；
保存新配置不再改变它。旧 API 必须继续能读取原值用于回滚，但 v1 不返回该字段。

## 失败模式与恢复

| 故障 | 行为 |
|---|---|
| 扫描超时 | 保留旧 observation，状态 error，已配置入口继续工作 |
| 目标离线 | suite 保持发布，output health degraded，会话失败写 reason code |
| 某 MiPlay 端口冲突 | 该 target 的 MiPlay unavailable，DLNA/AirPlay 正常 |
| 事件文件不可写 | 内存事件继续，system snapshot 标 observability degraded |
| 旧会话迟到回调 | coordinator 按 session id 丢弃 |
| 小米认证失效 | extension degraded，不改变 core health |
| 动态停用失败 | 恢复 config.enabled 和原 suite，返回 typed error |
| SOAP Play 成功但实体 DMR 未拉流 | 5 秒后 `OUTPUT_PULL_TIMEOUT`，回滚播放并关闭临时流 |

## 验证门槛

- 两目标离线集成测试同时启动六个入口，端口/UDN/名称不冲突。
- 注入第二个 MiPlay 端口冲突，只影响对应 ingress。
- 100 次启停后无增长的 task/socket/zeroconf 实例。
- 事件 URL/query、Cookie、客户端地址脱敏反例测试。
- 旧配置冷启动、升级、回滚和再次升级测试。
- v6 UI schema/fixture 与 API 响应契约测试一一对应。
- 两个 fake DMR 接收真实 SOAP 并分别 GET 自己的 WAV/PCM，控制成功但不 GET 的反例必须失败。
