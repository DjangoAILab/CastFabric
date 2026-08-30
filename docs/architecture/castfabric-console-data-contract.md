# CastFabric 控制台数据契约

## 目的

本契约把产品页面需要的数据映射到协议接收器、会话层、输出适配器、发现服务和配置层。
它是产品原型与 P3 API 设计之间的检查点，不代表当前 API 已经实现全部对象。

机器可读字段登记表位于
[`castfabric-console-fields.json`](../design/contracts/castfabric-console-fields.json)，
原型校验器位于
[`validate_console_prototype.py`](../prototypes/validate_console_prototype.py)。

## 领域对象

### `OutputTarget`

```json
{
  "id": "uuid:physical-renderer-udn",
  "kind": "dlna",
  "name": "客厅音箱",
  "location_host": "192.168.133.132",
  "enabled": true,
  "discovery": {"state": "online", "observed_at": "2026-08-30T12:00:00+08:00"},
  "capabilities": ["play", "pause", "stop", "volume", "status"]
}
```

`id/kind/name/location/enabled` 已存在于 `OutputTargetConfig`。`location_host` 由服务端解析
description URL 并丢弃路径与查询参数。`observed_at` 和标准化 capabilities 需要在 P3
补充，不能由浏览器自行猜测。

### `ReceiverSuite`

```json
{
  "target_id": "uuid:physical-renderer-udn",
  "enabled": true,
  "health": "healthy",
  "ingress": {
    "dlna": {"state": "ready"},
    "airplay": {"state": "ready"},
    "miplay": {"state": "ready"}
  },
  "current_session_id": "session-01"
}
```

它是 ADR-0004 的目标对象。当前 DLNA renderer 和 AirPlay 实例可按音响枚举；MiPlay 仍是
映射到首个目标的全局实例，因此 `ingress.miplay` 在生产实现前不得伪造成每音响状态。

### `MediaSession`

```json
{
  "id": "session-01",
  "target_id": "uuid:physical-renderer-udn",
  "protocol": "miplay",
  "state": "playing",
  "source": {
    "device_name": "Android 设备",
    "app_name": null,
    "provenance": "protocol",
    "confidence": "device"
  },
  "media": {"format": "PCM 44.1 kHz / 2 ch"},
  "started_at": "2026-08-30T11:58:05+08:00"
}
```

会话必须属于一台 target 和一个协议。来源字段逐级增强，缺失时置空，不能复用上一会话。
当前各协议状态分散在 renderer、AirPlay server 和 MiPlay diagnostics，需要会话层统一。

### `ActivityEvent`

```json
{
  "id": "event-01",
  "occurred_at": "2026-08-30T12:01:09+08:00",
  "session_id": "session-01",
  "target_id": "uuid:physical-renderer-udn",
  "protocol": "miplay",
  "type": "session.started",
  "outcome": "success",
  "reason_code": null,
  "summary_key": "activity.session_started",
  "details": {"media_format": "PCM 44.1 kHz / 2 ch"}
}
```

事件由会话与适配器边界主动发出。首版使用内存环形缓冲承载实时查询，并写入脱敏、轮转
JSONL 供最近活动和诊断导出使用；不引入数据库。UI 文案由 `summary_key` 本地化，不能把
服务端日志句子直接展示给用户。

### `SystemSnapshot`

包含版本、绑定地址、发现状态、音响/会话统计、入口聚合健康和可选扩展状态。系统健康
由 Receiver Suite 集合计算，不把小米认证失败升级为核心不可用。

## 数据流

```text
SSDP scan ───────────────▶ OutputTarget registry ───────▶ Speakers page
                                    │
                                    ▼
DLNA / AirPlay / MiPlay ─▶ ReceiverSuite ─▶ MediaSession ─▶ Home snapshot
                                    │              │
Output adapter status ──────────────┘              └──────▶ ActivityEvent journal

Config file ─▶ sanitized settings API ─▶ Connections dialog
Event journal + diagnostics ─▶ redaction ─▶ Activity detail / export
```

## API 目标边界

| 接口 | 责任 | 当前状态 |
|---|---|---|
| `GET /api/system` | `SystemSnapshot` | 由现有 status/setting 迁移 |
| `GET /api/targets` | 输出集合和发现快照 | 当前散落在 `target_list` 与 speakers |
| `POST /api/targets/scan` | 触发扫描，保留旧集合直到新快照完成 | 当前通过 setting query 隐式触发 |
| `PATCH /api/targets/{id}` | 独立启停、名称/别名 | 当前只有批量 target_ids 与旧 rename |
| `GET /api/suites` | 每音响三入口健康 | 未实现 |
| `GET /api/sessions` | 当前/近期媒体会话 | 未实现 |
| `GET /api/events` | 结构化活动查询与过滤 | 未实现 |
| `GET /api/diagnostics/export` | 服务端脱敏诊断包 | 未实现 |

## 审查门槛

1. 新原型字段先进入机器契约，再进入 HTML。
2. `planned` 字段必须指定 owner、fallback 和隐私级别。
3. `forbidden` 字段不能出现在 DOM；端到端延迟和 App 身份默认属于这一限制。
4. UI 验证必须覆盖缺失字段、空集合、扫描中、单入口降级和事件历史为空。
5. P3 API 设计逐项关闭 planned 缺口；未关闭前不授权生产 UI 连接这些字段。
