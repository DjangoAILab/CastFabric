# ADR-0003：采用 CastFabric 品牌与端口—适配器核心

## 状态

Accepted

## 背景

项目源自 MiAir，随后加入了 AirPlay 和 MiPlay 输入，但当前运行模型仍以“小米
账号中的音箱”为中心：`mi_did` 决定启动目标，`SpeakerController` 同时承担本地
DLNA 和小米 MiNA 云控制，应用编排器也把全部协议统称为“DLNA 服务”。这使一个
本应公开、通用的 DLNA 输出通道仍受小米设备元数据和认证状态影响，也使新增其他
局域网投放协议时容易继续把厂商逻辑写进核心。

产品目标已经变化为：把 DLNA、AirPlay、MiPlay 和未来输入接入统一媒体会话，再
输出到标准 DLNA MediaRenderer；小米云只为没有标准本地控制能力的设备提供可选
扩展。用户选择保留 CastFabric 自己发布的统一虚拟 DLNA 入口，即使实体音箱也会
发布自己的原生 DLNA 设备。

## 决策

- 项目品牌锁定为 **CastFabric**。默认设备名称前缀为 `CastFabric`，用户可以修改。
- Python 包 `miair`、旧 CLI `miair`/`openxiaocast`、旧配置字段和旧容器数据目录在
  迁移期保留兼容；新的主 CLI 为 `castfabric`。
- 核心采用端口—适配器结构：输入适配器只负责接收协议并产生媒体/控制事件；输出
  适配器实现统一的播放目标接口；会话层负责生命周期、抢占、状态和诊断。
- 标准 DLNA 输出是内置核心能力，发现和控制不依赖任何厂商账号。小米 MiNA 云控制
  移入可选输出适配器，只能作为显式配置的补充或回退路径。
- CastFabric 为每台已启用的输出音响发布独立的虚拟 DLNA MediaRenderer、AirPlay
  和 MiPlay 接收器组；不存在全局唯一的所选输出。详细模型见 ADR-0004。
- 迁移采用逐层替换，不一次性重命名 Python 包或配置目录，避免破坏现有 Home Server
  部署和用户的 `config.json`。

## 后果

### 正面

- 任何实现标准 AVTransport/RenderingControl 的局域网音箱都可以成为输出目标。
- 小米 token 过期不会再影响核心发现、设备选择、虚拟入口或本地播放控制。
- 新协议只需实现输入或输出接口，不需要修改厂商认证和主编排流程。
- 品牌、设备列表名称、Docker 镜像和发布文档具有一致定位。

### 负面

- 迁移期会同时存在 `castfabric` 与 `miair` 命名，代码要维护明确的兼容边界。
- 原生 DLNA 设备与 CastFabric 虚拟 DLNA 可能同时出现在手机列表中，这是已接受的
  产品选择，需要通过名称前缀减少误选。
- 会话仲裁和输出能力差异需要新增测试，不能只依赖单一小米音箱真机验证。

### 中性

- AirPlay/MiPlay 到普通 DLNA 音箱仍需由音箱通过 HTTP 拉取实时音频；端到端延迟受
  输入端缓冲、转码、HTTP 缓冲和音箱播放器共同影响，改架构不会自动消除延迟。
- 不支持 HTTP 实时流或相关音频格式的 DLNA 设备仍需兼容配置或后续转码策略。

## 备选方案

### 继续以小米账号设备为核心

短期改动最少，但标准 DLNA 能力仍会被厂商认证和设备列表绑架，不符合项目的新定位。

### 删除所有小米支持

核心最干净，但会立即丢失不提供原生 DLNA 的旧型号兼容能力。选择把它降为可选扩展，
而不是在第一阶段删除。

### 一次性把 `miair` 包和配置全部重命名

最终目录更整齐，但会破坏现有安装、镜像入口和持久化卷，且把品牌迁移与架构迁移的
故障混在一起，因此拒绝。

## 参考

- [ADR-0002：局域网投送发现与小米云认证解耦](0002-decouple-lan-discovery-from-xiaomi-cloud-auth.md)
- [CastFabric 系统设计](../architecture/castfabric-system-design.md)
- [CastFabric 重构实施计划](../plans/2026-08-29-castfabric-refactor.md)
- [ADR-0004：每个输出音响拥有独立接收器组](0004-one-receiver-suite-per-output.md)
