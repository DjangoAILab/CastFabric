# AirPlay / MiPlay 实时桥接延迟边界

状态：`v0.11.0-alpha.1` 发布基线
测试环境：Home Server `192.168.133.5`，同一局域网内的小爱音箱 HD 作为标准 UPnP/DLNA
MediaRenderer  
结论：约 4 秒是当前“实时输入 → DLNA HTTP pull 输出”组合的设备相关体验边界，不是
MiPlay 解码器中尚未清除的 4 秒等待。

## 1. 三条声路并不等价

```text
原生 DLNA：手机 ──有限媒体 URL──▶ 实体 DMR

AirPlay：手机 ──RAOP──▶ CastFabric ──实时 PCM/HTTP──▶ 实体 DMR
MiPlay：手机 ──RTP/MPEG-TS/AAC──▶ CastFabric ──实时 PCM/HTTP──▶ 实体 DMR
```

原生 DLNA 把原始媒体 URL 交给实体音箱。它通常具有确定的长度、Range、时长和压缩格式，
音箱固件可以走正常的文件播放策略。AirPlay 和 MiPlay 必须先由 CastFabric 接收并解码，
再把尚未结束、无法提前知道真实长度的 PCM 作为 HTTP WAV/L16 实时流交给同一台音箱。

## 2. 已验证事实

2026-08-30 的真机和 Home Server 日志给出以下边界。手机侧听感不是同步仪器测量，因此只
记录约数，不暴露为控制台的“端到端延迟”字段。

| 观测 | 结果 | 能说明什么 |
|---|---:|---|
| MiPlay 首个 MPEG-TS 输入到首个解码 PCM | 约 3–4 ms | FFmpeg 探测不再贡献数秒等待 |
| 建立输出、实体 DMR 发起 HTTP GET 并收到首批 PCM | 约 0.1 s | CastFabric 内部输出启动不是 4 秒瓶颈 |
| Android MiPlay 到可听声音 | 约 4 s | 端到端仍存在设备侧不可见等待 |
| iOS/macOS AirPlay 到可听声音 | 约 4 s | 与 MiPlay 相同的下游边界占主导 |
| 手机原生 DLNA 到实体 DMR | 小于 1 s | 有限媒体 URL 会走不同的固件缓冲策略 |

已经完成且没有带来可感知改善的对照包括：

- WAV 与标准大端序 L16；
- close-delimited、虚拟 `Content-Length` 与初始 Range 响应；
- 小米兼容扩展中的不同 `play_type`；
- FFmpeg probe/analyze 参数、PCM 队列和小包发送优化；
- AirPlay 与 MiPlay 使用同一实体输出的交叉对照。

这些实验覆盖了解码、封装和 HTTP framing。如果继续只调整这些参数，预期收益是毫秒到
数百毫秒，无法解释或消除约 4 秒。

## 3. 为什么最可能是实体 DMR 预读

UPnP Forum 的 AV Architecture 把 HTTP GET 归类为 asynchronous pull：这类传输没有实时
保证，MediaRenderer 通常使用 read-ahead buffer 吸收可检测的延迟和抖动；相对地，
isochronous push 才允许接收端立即渲染而不使用预读。CastFabric 当前输出正是前一种模式，
而标准 `AVTransport` / `RenderingControl` 没有“关闭固件预读”动作。

成熟 AirPlay 接收器 Shairport Sync 还记录了另一个独立事实：经典 AirPlay 通常协商约
2–2.25 秒的播放延迟；AirPlay 2 buffered audio 可低至约 0.5 秒。CastFabric 当前发布的是
AirPlay 1 / RAOP 接收端。不过两种 CastFabric 实时入口在同一音箱上听感几乎一致，说明
共同的 DMR 实时 HTTP 输出仍是首要边界；AirPlay 的协议调度可能与音箱预读重合，不能把
两者简单相加。

参考：

- [UPnP AV Architecture 2.0（UPnP Forum）](https://upnp.org/specs/av/UPnP-av-AVArchitecture-v2.pdf)
- [Shairport Sync README（经典 AirPlay 延迟与 pipe 后端边界）](https://github.com/mikebrady/shairport-sync)
- [Shairport Sync AirPlay 2 notes](https://github.com/mikebrady/shairport-sync/blob/master/AIRPLAY2.md)

## 4. 可行方向与优先级

### A. 新增原生或 isochronous 输出适配器（优先级最高）

绕开“PCM → DLNA HTTP pull”，直接使用目标音箱支持的低延迟本地/厂商协议，最有机会从
根本上降低延迟。它需要目标设备真实支持且协议可实现；当前测试音箱不支持原生妙播，
因此不能在 `0.10` 中直接落地。

### B. 有限滚动片段 POC（只做实验）

把实时 PCM 切为很短、确定长度的片段，尝试诱导固件使用文件播放策略。潜在代价是片段
切换爆音、间隙、频繁 `SetAVTransportURI`、控制语义丢失，且音箱仍可能对每段重新预读。
在真机证明收益和连续性之前，不作为默认声路。

### C. AirPlay 2 输入（独立增强）

AirPlay 2 buffered audio 能降低 AirPlay 输入端的协议延迟，但实现、配对和兼容成本显著，
并且不会解决 MiPlay，也不会绕过当前实体 DMR 的输出预读。只有在输出边界被改善后，
它才可能显著改善总体验。

### D. 继续微调现有队列（不作为主线）

保留回归防护，避免重新引入 FFmpeg 五秒探测或超大 PCM 队列；不再把它作为解决约 4 秒
听感延迟的主要方向。

## 5. 产品承诺

- README 明示原生 DLNA 是最低延迟路径。
- AirPlay / MiPlay 定位为本地音频兼容桥接，保证播放与控制，不承诺视频口型同步。
- 控制台只展示可测的链路状态，不虚构“端到端听感延迟”。
- 后续低延迟工作以独立 POC 和真机 AB 数据为准；未证明前不改变默认稳定声路。
