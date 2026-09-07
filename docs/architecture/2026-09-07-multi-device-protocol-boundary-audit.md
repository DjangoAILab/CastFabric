# CastFabric 多设备、多协议边界审查（2026-09-07）

## 结论

原有产品模型“每个输出一个 Receiver Suite，同目标互斥、异目标并行”是正确方向，但实现只覆盖了
部分 MCP/MiPlay 状态，没有把物理 controller 也放在同一所有权边界内。本轮已把 DLNA、AirPlay、
MiPlay、MCP URL/PCM 统一到 target-scoped session owner 与 command lane，并修复观察到的虚假
MiPlay 会话。

Home Server 的只读日志与 API 显示，多次 MiPlay 记录仅有 `session.started`，约十分钟后结束，期间
没有 `media_started`、`output_started` 或 `pcm_forwarded`。这与旧代码在 TCP accept 时立即创建
session、且没有握手读取超时完全一致。当前线上时刻实际 owner 是 paused MCP playlist，不是 MiPlay；
本轮没有修改服务器配置、播放状态或部署。

## 已修复问题

| 严重度 | 边界断点 | 修正 |
|---|---|---|
| P1 | TCP 探针被记录为 MiPlay 推送 | session 起点后移到合法 Open；增加绝对握手超时 |
| P1 | 空探针占住唯一发送端并拒绝真手机 | 只在 Open 时原子 claim；候选连接可并存且受超时限制 |
| P1 | 旧 MiPlay end 清掉已接管的 MCP session | end/映射/suite 清理都按原 session ID fencing |
| P1 | 旧 PCM/MiPlay close 无条件 stop 新输出 | live sink 在 stop/回滚前验证 output owner |
| P1 | AirPlay 被抢占后自动续播重新夺回输出 | AirPlay play/stop/resume/volume 接入 owner fence |
| P1 | 双 AirPlay 客户端共享 decoder，旧断开可停止新连接 | 首个协议握手 claim；RTSP 453 拒绝并发；回调携带连接 token |
| P1 | DLNA 完全绕过会话协调器 | DLNA Play 到 stop/seek/track/volume 接入 owner fence |
| P1 | 同目标 MCP play 可并发下发，旧命令可能后完成 | 每目标 operation lock 串行化全部物理命令 |
| P1 | playlist session 被其他协议抢占后 run 仍 active | run 与 session 在同一 SQLite 事务内 preempt |
| P2 | 目标 stop 只更新 MCP，会留下其他协议的假 playing | pause/resume/stop 改为作用于当前 target owner |
| P2 | 停用 suite 可能留下播放和 session | 停接收器后强制物理 idle 并结束残留 owner |
| P2 | shared server 部分启动失败只清引用、可能泄漏端口 | 启动异常执行实际 teardown 后再允许重试 |
| P1 | AirPlay 单目标冲突会注销共享 Zeroconf 上全部目标 | 删除全局注销补偿；每个 wrapper 只注销自身 ServiceInfo |
| P2 | AirPlay 从 asyncio loop 调同步 Zeroconf stop 触发阻塞错误 | unregister/close 移到工作线程执行 |
| P2 | MiPlay 启动失败时 cleanup 异常中断后续目标 | cleanup 独立捕获并保留 ingress 失败状态 |
| P2 | 多个 MiPlay receiver 使用同一个 `idHash` | 按稳定 target UUID 派生，重启稳定且设备间不同 |
| P3 | failed journal 丢失持久层 error code | `session.failed.reason_code` 保留稳定错误码 |

## 现在的并发语义

```text
target A: DLNA ─┐
          AirPlay ├─> target-A command lock ─> current session owner fence ─> speaker A
          MiPlay ┤
          MCP ───┘

target B: DLNA / AirPlay / MiPlay / MCP
          └────────> target-B command lock ─> independent owner ─> speaker B
```

- 同目标：合法的新 play 抢占旧 session；旧 callback 可以清自己的资源，但不能再改物理输出。
- 异目标：无共享 playback lock，可并行。
- 同一协议多发送端：MiPlay first valid Open wins；AirPlay first stateful handshake wins；DLNA 的合法
  play 按最后接受者接管。
- `command accepted`、`renderer pulled stream`、`PCM forwarded`、`audible` 是四个不同事实，不能合并。

## 手机找不到 MiPlay：已经证明与尚未证明的部分

已经证明：Home Server 能发布并自解析 `_mi-connect._udp`，端口 8899 在容器内可达；历史上也有一次
真实 Android control/media 链路进入服务。此次“网站显示在推送”本身由会话起点错误造成，不能反推
手机发现成功。

尚未证明：当前 MIUI 版本是否接受 CastFabric 的 TXT/`appsData`/安全握手组合。现有 scan 使用与
生产相同的自有 encoder/decoder，是循环验证；离线 simulator 也只证明本项目两端彼此兼容。公开的
真实广播样本含 `commonData`，且多设备必须有独立身份；本轮已修复这两个确定项，但没有根据未证实
推断改写私有 app-5 payload。`MiPlayForWindows` 的研究也明确提醒，早期把 payload 字节直接解释为
控制端口的结论证据不足。

下一次真机门槛应同时采集：手机的 mDNS query、CastFabric response、是否建立 8899 TCP、第一条
control frame、安全协商分支和 Open。只有这样才能区分“广播未被接收”“MIUI 过滤设备”“安全版本
不兼容”和“媒体链路失败”。在该门槛通过前，`ready` 只能解释为 receiver runtime ready。

参考：

- [MiPlayForWindows 当前协议研究](https://github.com/SUlTlUS/MiPlayForWindows/blob/main/docs/miplay-research.md)
- [MiPlay app-data 容器解析实现](https://github.com/SUlTlUS/MiPlayForWindows/blob/main/src/DLNACast.Core/MiPlay/MiPlayMdnsAppData.cs)
- [真实 MI Connect mDNS 报文样本](https://github.com/MetaCubeX/mihomo/issues/257)

## 仍然保留的边界与风险

1. **MIUI 发现/安全握手兼容性（P1，需真机）**：不能由服务自扫描或模拟器关闭。
2. **同目标双 AirPlay 真机接入（P2，需设备）**：共享状态现已 first claimant wins，并拒绝第二
   个客户端；仍需两台真实 sender 验证 RTSP 453 的系统 UI 行为与切换体验。
3. **DLNA `SetAVTransportURI` + `Play` 非事务（P2，协议限制）**：SOAP 请求没有可靠的控制端
   session ID；两个 control point 交错时采用 last accepted state，而非来源隔离。
4. **多实体音箱真并行（P1，需设备）**：fake DMR 已验证独立拉流，但当前 Home Server 只有一个
   实体目标，不能声称两台真实固件同时通过。
5. **每目标一个 MiPlay Zeroconf 实例（P3）**：功能正确但规模化资源成本偏高；目标数增大后应
   改为共享 Zeroconf、独立 ServiceInfo。

## 验证记录

- `.venv/bin/python -m pytest -q`：245 passed。
- `.venv/bin/python tests/test_audio_seek.py`：全部通过，包含真实 ffmpeg FLAC seek。
- `.venv/bin/python -m miair.miplay.probe self-test --duration 0.25`：passed；RTSP ready、5 media
  frames、53248 PCM bytes、非静音 peak 2968。
- Home Server 检查为只读；没有部署、重启、播放、停止或改音量。
