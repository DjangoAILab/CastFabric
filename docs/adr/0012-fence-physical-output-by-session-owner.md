# ADR-0012：以目标会话所有权隔离多协议物理输出命令

## 状态

Accepted and implemented locally on 2026-09-07.

## 背景

ADR-0004 规定同一 Receiver Suite 的 DLNA、AirPlay、MiPlay 与 MCP 输入互斥，不同输出可并行。
原实现只有 MCP 和 MiPlay 的部分路径接入 `MediaSessionCoordinator`，物理音箱控制仍分散在
DLNA renderer、AirPlay wrapper、MiPlay live sink、PCM stream 与 `PlaybackService`。因此“会话
已被新协议抢占”和“旧协议的异步清理仍能控制音箱”可以同时成立，造成新播放被旧 `stop`、
AirPlay 自动续播反抢、状态串写和命令乱序。

另外，MiPlay 在 TCP accept 时就占用唯一发送端并创建产品会话。端口探针、半开连接或握手失败
既会误报“正在推送”，也会在连接存活期间拒绝真正的手机发送端。

### 先理解四个对象

- **output target**：一台真实音箱，例如卧室小爱音箱。
- **Receiver Suite**：围绕这台音箱暴露的一组入口，包括 DLNA、AirPlay、MiPlay；MCP 也能向它投播。
- **session owner**：当前被允许控制这台物理音箱的那一次播放会话，不是某个协议永久拥有音箱。
- **physical command lane**：该音箱的 `play/pause/stop/seek/volume` 串行队列。它只约束同一音箱，
  不会把客厅和卧室排进同一个全局队列。

### 旧实现中一次故障是怎样发生的

```text
空 TCP 探针连到 8899
        │
        ├─ 旧实现立即创建 MiPlay session，并显示“正在推送”
        ├─ 探针不发送 Open/媒体，连接却长期占用唯一发送端槽位
        └─ 真正的小米手机此时连接会被拒绝

稍后 MCP 开始播放 ──> 成为页面上的新 session
旧 MiPlay 连接关闭 ──> 迟到的 end/stop 清 session 或停止物理音箱
```

这里有两套互相脱节的状态：`MediaSessionCoordinator` 认为 MCP 已经接管，但 MiPlay/AirPlay/DLNA
仍各自保留 controller 引用，可以继续对音箱下命令。仅修正页面状态不能解决声音被旧回调停止。

### 本决策要满足的要求

- 同一音箱在任一时刻只有一个会话可以改变物理播放状态。
- 新会话接管后，旧协议仍可以释放自己的 socket、decoder 和 HTTP stream，但不能碰音箱。
- 不同音箱保持真正并行，不能引入全局锁。
- 不能改变已验证的音频编码、PCM 字节、HTTP 拉流格式和实体 DMR pull-confirmation 边界。
- 不把端口监听成功、mDNS 自扫描或模拟器成功表述为 MIUI 真机兼容。

## 决策

1. 每个 output target 只有一条物理命令通道。URL 播放、PCM 创建/关闭、DLNA、AirPlay 及目标级
   pause/resume/stop/seek/volume 共享该 target 的异步 operation lock；不同 target 使用不同锁。
2. `MediaSessionCoordinator.current(target_id)` 是唯一输出 owner。每次物理停止、续播、Seek、
   切歌或发送端音量变更前必须再次验证 session ID；不能证明所有权时 fail closed。
3. MiPlay 的候选 TCP 连接不构成产品会话，也不占活动发送端。只有通过协议并产生合法 `Open`
   后才原子 claim；未完成握手的连接受绝对超时限制。
4. AirPlay 在实际 play callback、DLNA 在 `Play` 动作时创建会话。成功物理命令后转为 playing；
   拒绝或异常结束为 failed。旧协议的迟到 end 只能结束自己的 session，不能清除新的 suite owner。
5. 目标级 pause/resume/stop 操作当前 owner，不按调用入口协议做特殊判断。显式停用目标会停止
   playlist/PCM/各接收器、物理输出和残留会话。
6. 会话抢占与其所属活动 playlist run 在同一 SQLite 事务内结束，避免 active run 孤儿状态。
7. `IngressState.READY` 只表示服务已绑定和发布，不代表某个 MIUI/固件版本已经完成真机互操作。

## 同协议内部策略

- 两个 MiPlay 发送端同时完成 Open：先完成 claim 的会话获胜，另一个以协议错误结束。
- 两个 AirPlay RTSP 客户端：首个进入 FairPlay/ANNOUNCE/SETUP 的连接 claim 服务端共享状态，
  另一个得到 RTSP 453；连接 token 同时 fence play/stop/volume 回调。两个 DLNA control point 的
  物理命令串行，后完成合法 play 的会话采用 last accepted play wins。DLNA 的 `SetAVTransportURI` 本身没有可靠控制端身份，
  因而无法承诺事务式的“URI + Play”跨请求隔离。
- 不同 target：独立锁、独立 session owner、独立 ingress runtime，可真实并行，不做全局排队。

## 后果

- 旧输入的 close、stop、音量或 AirPlay 自动续播不能破坏新 owner 的输出。
- 控制台不再因纯 TCP 探针产生 MiPlay 活动会话；诊断仍可看到候选 control connection 数量。
- 同 target 的并发命令增加少量排队延迟，换取确定的物理命令顺序。
- 进程内 fencing 不能代替真机协议验证，也不能阻止音箱自身按固件策略中断播放。

## 对声音推送链路的影响

正常声音数据路径没有改写：

```text
MiPlay:  WFD/RTP/MPEG-TS ─> FFmpeg decode ─> PCM ─> 临时 HTTP WAV ─> 实体 DMR 拉流
AirPlay: RAOP/RTP        ─> 原解码/重采样路径 ─> 临时 HTTP WAV ─> 实体 DMR 拉流
DLNA:    媒体 URL        ─> 原 proxy/seek URL ──────────────────> 实体 DMR 拉流
MCP:     URL/file/PCM    ─> 原 PlaybackService/live sink ──────> 实体 DMR 拉流
```

没有调整 FFmpeg 参数、采样率、声道、sample width、WAV header、HTTP mode、队列长度、实体音箱
`play_type` 或 5 秒 pull-confirmation 门槛。新增逻辑位于控制面：在下发物理命令前排队并校验 owner。

正常单发送端时锁没有竞争，只增加一次内存锁与 ID 比较，不增加预缓冲，也不改变音频字节。只有同一
音箱真的发生并发时，后到命令才会等待前一个控制命令完成；PCM 建流最坏会受既有 5 秒实体拉流
确认窗口约束。其目的正是避免两个 `play_url` 或旧 `stop` 交错。不同音箱完全不互相等待。

可观察到的行为变化是有意的：被抢占的旧音源可能仍短暂发送网络音频，CastFabric 会清理它自己的
decoder/stream，但不会再让它停止或重夺物理音箱；新的 owner 继续播放。

## 方案比较

### 方案 A：每个协议自己加锁

能阻止两个 MiPlay 相互冲突，但不能阻止 MiPlay 与 AirPlay/MCP 交错，继续存在跨协议竞态，因此拒绝。

### 方案 B：检测到并发时停止所有协议和音箱

实现简单，但会产生明显断音，也会让不同音箱错误地互相影响；启动失败时还可能停止用户原本独立
播放的内容，因此拒绝。

### 方案 C：每目标命令通道 + session owner fencing（采用）

范围与 Receiver Suite 一致；既能串行物理命令，又允许旧会话无害地做本地资源清理。代价是所有
协议适配器都必须携带 session ID，并在每个异步回调处检查所有权。

## 失败与回滚语义

| 场景 | 行为 |
|---|---|
| MiPlay TCP 连接但无 Open | 15 秒内关闭；不创建产品 session、不抢音箱 |
| 同目标两个 MiPlay Open | 第一个成功 claim，后一个失败退出 |
| 同目标两个 AirPlay stateful client | 第一个 claim，后一个收到 RTSP 453 |
| 旧会话迟到 stop/volume/resume | owner 校验失败，只清本地资源，不操作音箱 |
| 新 play 被实体音箱拒绝或未拉流 | 新 session failed；只有仍持有 owner 时才回滚物理输出 |
| playlist 被其他协议接管 | run 与 session 在同一事务内标记 preempted |
| 正常 shutdown/停用目标 | 停接收器、停止物理输出、结束残留 session |
| receiver 启动中途失败 | 只回滚已创建的服务/socket，不擅自停止音箱原有播放 |

## 发布前真机门槛

本地测试通过后仍不能直接部署并声称兼容。发布候选至少要验证：

1. 小米手机能在系统投屏面板发现设备，并完成 8899/Open，而不是只有服务端自扫描。
2. MiPlay、AirPlay、DLNA、MCP 依次接管同一音箱，旧连接关闭不会停止新声音。
3. 两个不同输出同时播放，各自 stop/volume 不影响另一台。
4. 双 AirPlay sender 时第二台的系统 UI 能合理处理 RTSP 453，第一台声音不被破坏。
5. 对比变更前后的首声时间、断音和实体 DMR GET；任何听感结论必须由真机试听记录支持。

## 验证

- 空 TCP 探针不创建 session，且不能阻塞同时到来的合法 MiPlay sender。
- 同 target 两个 MCP play 的物理命令不重叠；不同 target 仍独立。
- 被抢占的 MiPlay sink、AirPlay wrapper 与 DLNA renderer 的迟到 stop 不调用物理 controller；
  旧 AirPlay client token 的 stop/volume callback 也不能控制新 client。
- 旧 MiPlay/AirPlay/DLNA end 不清除新 session；playlist session 被抢占时 run 同时结束。
- 全量 Python tests、直接音频 Seek 脚本和离线 MiPlay WFD/PCM self-test 通过。

## 参考

- [ADR-0004：每个输出音响拥有独立接收器组](0004-one-receiver-suite-per-output.md)
- [ADR-0006：通过 Suite Registry 演进运行时](0006-evolve-runtime-through-suite-registry.md)
- [ADR-0007：以实体 DMR 拉流作为输出建立边界](0007-verify-physical-output-pull.md)
- [MiPlayForWindows protocol research](https://github.com/SUlTlUS/MiPlayForWindows/blob/main/docs/miplay-research.md)
- [Observed MI Connect mDNS record](https://github.com/MetaCubeX/mihomo/issues/257)
