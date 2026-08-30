# ADR-0007：以实体 DMR 拉流作为输出建立边界

## 状态

Accepted and implemented。

## 背景

MiPlay 和 AirPlay 输入经 CastFabric 解码为 PCM 后，由实体 DLNA MediaRenderer 主动拉取
本机 HTTP 音频流。UPnP 的 `SetAVTransportURI` 与 `Play` 返回成功，只表示实体音响接受了
控制命令；音响仍可能因为地址不可达、固件拒绝媒体格式或内部状态异常而不发起 HTTP GET。
旧实现把 SOAP 成功立即记录为 `output_started`，因此会出现控制台显示成功但实际无声。

## 决策

1. `AudioStreamServer` 为每次 streaming session 暴露一次实际 GET 拉流确认。
2. `CastFabricLiveAudioSink.start()` 只有在控制命令成功且实体 DMR 开始消费 HTTP 端点后，
   才发出 `output_started`。
3. 控制成功但 5 秒内没有拉流时，发出 `output_failed`，原因码为
   `OUTPUT_PULL_TIMEOUT`，回滚实体播放命令并关闭临时 HTTP server。
4. `pcm_forwarded` 仍只表示第一批解码 PCM 已写入输出 server；它不冒充用户实际听到声音。
5. MP3 模式只有在实体 GET 且 ffmpeg 成功启动后才确认输出建立。

## 后果

- 活动日志可以区分“控制命令被接受”和“实体音响真正开始取流”。
- 输出建立最多增加一次 DMR 拉流握手等待；正常 DMR 会在 `Play` 后立即 GET，不增加音频缓冲。
- 仅凭服务端仍无法测量扬声器实际发声时刻，因此产品不展示伪造的端到端延迟。

## 验证

- 单元反例：控制器返回成功但从不 GET，必须得到 `OUTPUT_PULL_TIMEOUT` 且执行回滚。
- 协议 POC：两个 fake UPnP DMR 分别接收真实 SOAP 命令、拉取两个不同 HTTP URL，验证各自
  收到正确 WAV/PCM，URL、负载和生命周期互不串流。

## 参考

- [ADR-0004：每输出音响独立 Receiver Suite](0004-one-receiver-suite-per-output.md)
- [ADR-0005：控制台可观测数据契约](0005-console-observability-contract.md)

