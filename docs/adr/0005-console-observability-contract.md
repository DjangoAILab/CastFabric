# ADR-0005：控制台只展示具有来源与降级规则的数据

## 状态

Accepted for product design；运行时数据模型和 API 尚未实现。

## 背景

CastFabric 控制台需要展示多台输出音响、每台音响的 Receiver Suite、当前媒体会话和
近期活动。当前实现已经能提供配置目标、一次 SSDP 扫描快照、DLNA transport state、
AirPlay 活跃状态和全局 MiPlay 诊断，但还没有统一的 `ReceiverSuite`、`MediaSession`
或结构化活动事件 API。

如果原型直接把日志文本、媒体 URL 猜测或全局 MiPlay 状态拼成完整产品数据，后续实现
会被迫维持错误语义；如果原型只展示现有旧 API，又会违背已经接受的每音响独立
Receiver Suite 模型。

## 决策

1. 产品数据以 `OutputTarget`、`ReceiverSuite`、`MediaSession`、`ActivityEvent` 和
   `SystemSnapshot` 五类对象组织；旧的 `default_target_id` 只用于迁移，不进入产品 UI。
2. 每个 UI 字段必须登记为以下四类之一：
   - `current`：现有 API 或运行对象可以直接提供；
   - `derived`：可以从现有可信字段无歧义推导；
   - `planned`：目标架构可实现，但必须列出采集责任方和缺失时的 UI 降级；
   - `forbidden`：无法可靠取得或会误导用户，原型和生产 UI 均不得使用。
3. 原型 DOM 使用 `data-field` 和 `data-action` 绑定机器可读字段登记表；校验脚本拒绝
   未登记字段、未指定实现责任方的 planned 字段和任何 forbidden 字段。
4. 结构化活动事件由会话层产生，文本日志只是诊断附件，不能反向解析成产品事件。
5. 发送 App 名称只有协议明确提供且带来源说明时才可展示；URL 域名猜测和音频内容
   指纹均不得作为可靠 App 身份。
6. “延迟”只有存在定义清晰的测量起止点时才展示。解码首帧耗时不能冒充用户听到声音
   的端到端延迟。
7. 秘密、完整 Cookie、媒体 URL 查询参数和完整客户端 IP 不进入产品事件；诊断导出前
   必须经过服务端脱敏。

## 后果

### 正面

- 原型可以面向已接受的目标架构设计，同时明确区分现有能力和 P3 实现缺口。
- 产品字段、API 设计和协议采集责任可以自动核对，减少视觉稿反向绑架架构的风险。
- 来源缺失、协议降级和重启后历史为空都有明确的 UI 表达。

### 负面

- 活动页和每音响 MiPlay 健康在进入生产前必须新增会话/事件模型，不能直接复用旧 API。
- 新增 UI 字段时必须同步更新契约与验证，原型制作成本略有增加。

### 中性

- 原型仍使用固定演示数据，但演示字段必须通过契约检查；`planned` 不等于已经实现。

## 备选方案

### 只展示当前 API

会保留全局 MiPlay、默认目标和旧 speaker 结构，直接违背 ADR-0004，拒绝。

### 原型先画完整功能，实施时再删

无法区分可实现增强和纯视觉想象，风险最高，拒绝。

### 从文本日志生成活动记录

日志文案不是稳定接口，缺少 session/target 关联和隐私边界，拒绝。

## 参考

- [ADR-0003：CastFabric 端口—适配器核心](0003-adopt-castfabric-and-port-adapter-core.md)
- [ADR-0004：每输出音响独立 Receiver Suite](0004-one-receiver-suite-per-output.md)
- [控制台数据契约](../architecture/castfabric-console-data-contract.md)
