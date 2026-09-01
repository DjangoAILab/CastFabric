# ADR-0009：通过薄 MCP 适配层暴露 Agent 音频能力

## 状态

Accepted

## 背景

CastFabric 已经拥有局域网输出音响发现、按目标启停 Receiver Suite、URL 播放、实时
PCM 输出以及暂停、停止、音量和状态查询能力。AI Agent 需要使用这些能力，但不应因此
在 CastFabric 中再建设 TTS、播放列表、队列、媒体库或另一套播放状态机。

MCP 的 Streamable HTTP 负责工具消息传输，不作为持续音频数据通道。URL、有限文件和
实时 PCM 的数据生命周期也不同，不能伪装成同一种 JSON 调用。

## 决策

1. 在现有 aiohttp 进程的同一监听端口挂载 `/mcp` Streamable HTTP 端点。它位于应用
   服务与运行时对象之上，不直接调用 DLNA、MiNA、AirPlay 或 MiPlay 的协议实现。
2. 所有管理、播放和控制命令都使用现有规范化 `target_id` 指向唯一输出音响；不增加
   平行的 `speaker_id`。
3. MCP 暴露三组原子工具：
   - 管理：系统状态、列出输出、主动扫描、更新输出；
   - 播放：URL、有限文件、实时 PCM；
   - 控制：播放状态、暂停、停止、音量。
4. URL 直接复用 `PlaybackTarget.play_url()`，不增加代理或转码。
5. `play_file` 通过 MCP 创建有大小与时效限制的一次性上传事务，返回同源的不可枚举
   上传地址；Skill 上传原始文件字节后，CastFabric 保存临时文件并复用
   `PlaybackTarget.play_url()`。不通过 JSON-RPC 传 Base64，不建立持久资产库。
6. 实时入口固定接收 PCM `s16le / 48 kHz / 双声道`。MCP 工具只创建会话并返回
   WebSocket 写入地址；二进制 PCM 帧经现有 `CastFabricLiveAudioSink.write()` 进入输出。
7. 配套发布 `castfabric` Agent Skill。Skill 中的 Node.js helper 负责读取和上传本地
   文件、调用 MCP、使用 FFmpeg 把文件/URL/stdin 转为标准 PCM，以及在客户端进程中
   进行顺序或循环播放。
8. 播放列表不进入 CastFabric 服务端，不新增队列、恢复、上一首或下一首语义。
9. 控制台新增只读的“AI 接入”页面，提供 MCP 地址、客户端安装命令、可复制安装提示词
   和 Skill 安装入口；本阶段不增加新的产品配置项。

## 后果

### 正面

- MCP、Skill 和现有手机投放共享同一个输出目标与播放实现。
- Home Server 仍只有一个 CastFabric 进程、容器和监听端口；MCP 只是现有服务的路由。
- AI 能力完整覆盖当前管理和播放能力，同时避免为 AI 重写核心逻辑。
- Node helper 可以解决 Agent 不擅长处理二进制文件、FFmpeg 和长时间编排的问题。
- 后续增加新的输出适配器时，MCP 和 Skill 无需修改协议实现。

### 负面

- Agent 本地文件需要由 Skill 完成一次 MCP 建单与 HTTP 上传，不能只靠一个 JSON-RPC
  消息传完。
- 实时 PCM 仍受实体 DLNA 音箱 HTTP 预读影响，不改善现有约四秒实时桥接延迟。
- 播放列表依赖 Node helper 进程存活，不是服务器持久队列。
- 第一版不接受编码后的实时 MP3/AAC；需要由 helper 的 FFmpeg 预先解码。

### 中性

- WebSocket 是实时音频数据面，MCP 是管理与控制面。
- 文件上传、PCM WebSocket、控制台 API 和 `/mcp` 共用现有 Web 端口。
- 临时文件和实时会话必须在播放结束、连接断开或服务停止时清理。
- MCP 调用产生的媒体会话以 `mcp` 作为输入协议记录，继续进入现有会话和活动日志。

## 未采用方案

### 在 CastFabric 内加入 TTS、播放列表和策略中心

这些不是当前已有能力，会扩大产品边界并重复 Agent 及 Skill 已能完成的编排。

### 通过 MCP JSON-RPC 持续发送 PCM 分片

会把控制协议当成媒体数据协议，产生 Base64 开销、消息尺寸和背压问题。

### 在 Agent 本地运行 stdio MCP sidecar

可以直接读取 Agent 本地路径，但会增加客户端安装和生命周期管理，并重复 CastFabric
已经拥有的长期服务边界。

### 在 Home Server 单独部署 MCP 服务

会增加进程、端口、健康检查和反向代理配置，违背家庭服务器自托管的简洁性要求。

### 为 Skill 另建一套控制 API

会造成 MCP 与脚本行为分叉。Skill 必须调用同一 MCP 工具；只有文件和 PCM 字节使用
相应的数据通道。

## 相关文档

- [CastFabric MCP 与 Agent Skill 设计](../plans/2026-09-01-castfabric-mcp-agent-skill-design.md)
- [CastFabric 系统设计](../architecture/castfabric-system-design.md)
- [ADR-0007：验证实体输出拉流](0007-verify-physical-output-pull.md)
