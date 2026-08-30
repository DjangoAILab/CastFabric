# CastFabric 发送来源与媒体信息可观测性研究

## 研究目的

首页希望解释“声音从哪里来、经过什么协议、正在投到哪台音响”。其中协议和目标音响
属于 CastFabric 自己掌握的事实；发送 App、发送设备和歌曲信息则依赖不同协议是否提供。
本研究用于防止原型把“网易云音乐”等理想字段误写成已有能力。

## 现有实现审计

### MiPlay

`LegacyReceiverSession` 已处理三个相关命令：

- `SetLocalDeviceInfo`：读取 `sourceName` 并保存在会话对象中；
- `SetPlaySource`：只验证 JSON 对象，未保存 `ref_channel/ref_content/ref_function`；
- `SetMediaInfo`：只验证 JSON 对象，未保存歌曲、歌手、专辑和来源设备。

`MiPlayReceiver.diagnostics()` 当前只暴露 peer IP、认证、RTSP、媒体帧和错误，未把
`sourceName` 带入 `last_session`。离线 POC 证明设备名被保留，而 App 和媒体字段没有
进入会话状态：

```text
source_name_retained: Wang Android
play_source_payload_retained: false
media_info_retained: false
```

社区逆向资料表明，当前 MIUI 的 `SetPlaySource.ref_content` 可以映射
`music_wangyiyun`、`music_qq` 等常见 App；`SetMediaInfo` 还可携带标题、歌手、专辑、
封面地址和 `mSourceName`。这些字段是**条件性协议能力**，不是每次会话都保证存在。

来源：

- [MiPlay source fields](https://github.com/SUlTlUS/MiPlayForWindows/blob/main/docs/miplay-mi13p-source-fields.md)
- [MiPlay source identity boundary](https://github.com/SUlTlUS/MiPlayForWindows/blob/main/docs/miplay-source-identity-context-boundary.md)
- [MiPlay SetMediaInfo codec](https://github.com/SUlTlUS/openMiPlay/blob/main/src/OpenMiPlay/MiPlaySetMediaInfoPayloadCodec.cs)

上述项目没有明确开源许可证，本研究只记录外部可观察的字段语义，不复制其代码。

### AirPlay

现有接收器读取 `X-Apple-Device-Name`、User-Agent 或 SDP `i=` 字段，因此通常可以显示
发送设备名。AirPlay 音轨元数据可通过 `SET_PARAMETER` 的 DMAP 数据发送；
Shairport Sync 可输出歌手、专辑、标题和封面，但明确限定为“来源提供时”。当前
CastFabric 的 `SET_PARAMETER` 只处理音量，未连接 DMAP 元数据解析。

AirPlay 是系统级音频路由。发送设备名和歌曲信息不等于发送 App 身份；不能因为设备
正在播放某首歌就断言来源是 Apple Music、网易云或 QQ 音乐。

来源：

- [Shairport Sync](https://github.com/mikebrady/shairport-sync)
- [Shairport metadata reader](https://github.com/mikebrady/shairport-sync-metadata-reader/blob/master/README.md)
- [Unofficial AirPlay metadata reference](https://openairplay.github.io/airplay-spec/audio/metadata.html)

### DLNA

`SetAVTransportURI` 标准允许控制端附带 `CurrentURIMetaData`，其 DIDL-Lite 内容可以
包含标题、作者等媒体信息。CastFabric 已原样保存该字段，但目前只解析时长。

现有 Web UI 通过媒体 URL 域名猜测网易云、QQ 音乐和酷狗。该结果只能算提示：CDN、
本地代理、签名 URL 和 App 版本变化都会让域名失真；UPnP AV 也没有规定一个通用的
“控制 App 名称”字段。

来源：

- [UPnP AVTransport specification](https://openconnectivity.org/wp-content/uploads/2015/11/UPnP-av-AVTransport-Service.pdf)
- [UPnP MediaRenderer resources](https://openconnectivity.org/developer/specifications/upnp-resources/upnp/mediaserver4-and-mediarenderer3/)

## 统一可靠性模型

| 层级 | 字段 | 可靠性 | 首页规则 |
|---|---|---|---|
| L0 | 目标音响、接收协议、会话状态 | 必有 | 始终显示 |
| L1 | 发送设备名 | 条件性 | 有值显示；否则显示“发送设备” |
| L2 | 标题、歌手、专辑、封面 | 条件性 | 逐字段增强，不保留上一会话旧值 |
| L3 | 发送 App | MiPlay 条件性；DLNA 仅启发式；AirPlay 不可靠 | 只有协议明确提供时显示；URL 猜测必须标记为推测 |

任何会话字段都应携带 `value`、`source` 和 `confidence`。UI 不用向普通用户展示置信度，
但渲染逻辑必须据此选择真实文案。

## 投入评估与决策

1. **立即采用，无生产改动：** 首页 v4 默认只依赖 L0，使用 L1/L2 的可选插槽。
2. **后续小型增强，值得做：** 保存 MiPlay `sourceName/ref_content/SetMediaInfo`，接入统一
   会话模型和 API；成本低、首页收益明显，但必须用当前真机验证字段是否稳定出现。
3. **后续中型增强，可择期：** 解析 DLNA DIDL-Lite 与 AirPlay DMAP。价值主要是歌曲
   信息，不是识别 App。
4. **不投入：** 维护一张 CDN 域名到 App 的“可靠识别表”，或通过音频指纹反推 App。

因此原型不得默认写“网易云音乐”。评审演示可切换到“元数据完整”状态，用于验证增强
后的排版，但必须同时验收“只有协议”和“只有设备名”两种降级状态。
