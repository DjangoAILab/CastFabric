# ADR-0008：实体 DLNA 控制地址必须支持运行时漂移

## 状态

Accepted and implemented。

## 背景

部分实体 MediaRenderer（已在小爱音箱 HD 上复现）会在设备重启后保留 UDN 与 IP，
但重新选择随机 HTTP 控制端口。CastFabric 过去只在进程启动时创建
`LocalDLNAClient`；控制台“重新发现”只更新 observation，不更新正在运行的客户端。
因此入口仍可被发现，AirPlay 与 MiPlay 也能接受输入，但 DLNA、AirPlay、MiPlay
最终都会把 `play_url` 发往过期端口。

2026-08-30 的现场证据中，持久化地址为 `192.168.133.132:1269`，音箱当前通过
SSDP 宣告 `192.168.133.132:2026`。三条协议的失败最终均收敛为同一输出适配器的
`ClientConnectorError`。

## 决策

1. `LocalDLNAClient` 持有稳定 UDN、出接口和一把端点刷新锁。
2. SOAP 遇到连接失败或连接超时时，按 UDN 重新执行一次 SSDP 发现，重新读取设备描述，
   原子替换完整 service map，并只重试原命令一次。
3. 并发命令若同时命中过期端口，只允许一个请求执行发现；其他请求复用已更新的地址。
4. 正常命令不在播放前强制扫描，避免给每次控制增加固定发现延迟。
5. 控制台主动扫描同时更新 observation、运行中的客户端和持久化 target location。
6. 后台每 60 秒刷新一次物理输出 observation 与端点，降低首次失败时才恢复的概率。
7. 新地址持久化失败不得破坏已经恢复的当前播放命令。

## 后果

- 实体音箱重启或 DLNA HTTP 端口漂移不再要求重启 CastFabric。
- DLNA、AirPlay 与 MiPlay 共享输出适配器，因此一次修复覆盖三种入口。
- 仅在真实连接失败时增加一次最多约 1.5 秒的 SSDP 恢复；正常控制路径没有额外扫描。
- 如果设备不再宣告原 UDN，命令仍会明确失败，不会错误绑定到另一台同名音箱。

## 验证

- 单元反例：旧端口连接失败后发现新端口，原 SOAP 命令只重试一次并成功。
- 并发反例：两个命令同时命中旧端口，只执行一次 SSDP 发现。
- Runtime 测试：一次主动扫描同时更新 live client 和持久化 location。
- Home Server POC：故意以失效的 `1269` 创建客户端，实际恢复到 `2026` 并读取物理音箱音量。
- 完整链路：虚拟 DLNA 接受 SOAP，物理 DMR 拉取 192,044 字节 WAV；MiPlay 产生
  `output_started` 与 `pcm_forwarded`，无 `output_failed`。

## 参考

- [ADR-0004：每输出音响独立 Receiver Suite](0004-one-receiver-suite-per-output.md)
- [ADR-0007：以实体 DMR 拉流作为输出建立边界](0007-verify-physical-output-pull.md)
