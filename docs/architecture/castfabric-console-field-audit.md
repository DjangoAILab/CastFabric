# CastFabric 控制台字段实现审计

## 审计结论

本审计最初以 `be67337` 的运行代码为证据，逐项核对 v6 原型需要的字段。结论不是“页面能否
拼出一个值”，而是该值是否有稳定语义、明确所有者和可靠降级。

- 18 项可直接读取现有配置或安全 API。
- 4 项可由现有、可信对象无歧义投影，但仍需集中到新的 read model。
- 31 项必须由目标注册表、Receiver Suite、MediaSession 或 ActivityEvent 新增。
- 2 项禁止猜测：发送 App 名称和端到端听感延迟。

## Runtime v2 关闭状态（2026-08-30）

生产控制台接入 `/api/v1` 后，机器合同现为 47 项 current、5 项 derived、1 项 planned、
2 项 forbidden；10 个产品动作全部有 current owner。唯一仍为 planned 的
`system.interface` 没有被伪造：控制台按合同 fallback 只显示服务绑定的局域网地址。

生产 HTML 已删除固定音响、会话和活动样例。来源设备名只有协议明确提供才显示，否则固定
回退为“发送设备 / 协议未提供设备名称”；来源 App 和端到端听感延迟仍保持 forbidden，
未进入 API、控制台或诊断包。

本轮复核把 `system.discovery.state`、`session.protocol` 和 `session.state` 从“可推导”
收紧为“规划”。旧代码虽然各处有局部状态，但没有稳定的扫描生命周期，也无法把多个
协议状态无歧义归并为每音响唯一会话。

## 当前代码证据

| 产品域 | 当前证据 | 能直接承诺的语义 | 缺口 |
|---|---|---|---|
| 系统 | `miair/web/api.py` 的 `/api/status`、`Config` | 版本、绑定地址、端口、基础配置 | 无统一健康快照和独立发现生命周期 |
| 输出目标 | `OutputTargetConfig`、`LocalDLNAClient.discover` | id、kind、name、location、enabled、一次扫描是否出现 | 无 `observed_at`、标准能力集和独立别名 |
| 虚拟 DLNA | `CastFabric.renderers` | 每目标 renderer 是否创建、transport state | 运行对象仍按 UDN 分散，无 suite 投影 |
| AirPlay | `AirPlayManager.speaker_airplays` | 每目标 server、playing、client_name | 没有统一 session id、事件和结果原因 |
| MiPlay | `CastFabric.miplay_receiver` | 单个全局 receiver 的诊断 | 只映射首个 controller，不能冒充每音响状态 |
| 活动 | 文本日志和局部 diagnostics | 只适合诊断 | 没有结构化、可查询、可本地化的产品事件 |
| 扩展 | `_extension_auth_status`、脱敏 helper | 小米扩展开关和安全认证状态 | 不得升级为核心系统健康 |

## 字段分组

### 当前可读

`system.version`、`system.hostname`、`system.receiver_prefix`、三类端口、客户端语言、
小米扩展开关/认证状态、`target.id/name/kind/enabled`、播放默认值和续播设置。

这些字段仍必须经新的安全 API 投影；生产 UI 不直接读取旧 `/api/setting` 的大对象，避免
把迁移字段、Cookie 占位值和厂商配置重新带回主流程。

### 可信投影

- `target.location_host`：服务端解析 description URL，只返回 host，删除 path/query。
- `target.online`：只表示“最近一次完成扫描是否出现”，不能写成持续在线。
- `suite.ingress.dlna`：由 renderer 是否注册和启动结果投影。
- `suite.ingress.airplay`：由每目标 AirPlay 实例启动结果投影。
- 目标数量：由 OutputTarget registry 计算。
- 当前协议局部来源信息：只在协议显式提供时进入 normalizer。

### 必须新增

- `TargetDiscoveryRegistry`：扫描 `idle/scanning/ready/error`、完成时间、保留上一快照。
- `ReceiverSuiteRegistry`：每目标启停、三入口状态、单入口错误和端口。
- `MediaSessionCoordinator`：每目标唯一活跃会话、协议、状态、来源 provenance。
- `ActivityEventJournal`：结构化事件、原因码、脱敏详情和有界历史。
- `SystemSnapshotProjector`：目标/入口/会话计数和总体健康。

### 禁止字段

- `session.source.app_name`：只有协议明确提供且记录 provenance 时未来才可重新评估；不能
  从 URL、User-Agent 或音频内容猜测。
- `session.end_to_end_latency`：解码首帧、首 PCM 或 `play_url` 返回时间都不是用户听到
  声音的时间。没有同步发送端和声学探针时不进入 UI。

## 动作审计

| 动作 | 当前能力 | 目标语义 |
|---|---|---|
| 扫描 | `/api/setting?need_device_list=true` 隐式触发 | `POST /api/targets/scan`，保留旧快照直到完成 |
| 独立启停 | 旧接口批量写 `target_ids` 并重启进程 | `PATCH /api/targets/{id}`，只改变该 suite；失败回滚 |
| 编辑名称/别名 | 仅旧 DID rename | 通用 target patch；别名与物理 friendly name 分离 |
| 活动筛选/详情 | 无 | journal 查询，不解析文本日志 |
| 保存连接配置 | `/api/setting` 全量保存并重启 | 分区白名单 patch，明确 `restart_required` |
| 导出诊断 | 无 | 服务端脱敏后生成，不向浏览器暴露原始 Cookie/URL |

## 实现门槛

1. 生产页面接字段前，登记表的对应项必须从 `planned` 改为 `current/derived`，并补测试证据。
2. 新 API 的 JSON schema 测试必须证明缺失值走 fallback，不复用上一会话数据。
3. 多音响测试必须至少包含两个 enabled target，证明启停、端口、会话和失败互不串线。
4. 旧 `default_target_id` 只可在兼容 API/迁移测试出现，不进入新领域对象或 v6 UI。
5. 所有 diagnostics/details 先脱敏再进入事件；测试使用包含 query token 的 URL 做反证。
