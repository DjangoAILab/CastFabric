# ADR-0002：局域网投送发现与小米云认证解耦

## 状态

Accepted

## 背景

OpenXiaoCast 在局域网中发布虚拟 DLNA MediaRenderer、AirPlay 接收器和
MiPlay 接收器，再通过小米 MiNA 云接口命令实体音箱拉取网关提供的音频 URL。
此前启动顺序把“小米云登录成功”作为发布这些入口的前置条件。因此
`micoapi` token 过期、登录风控或小米云短时不可达时，SSDP 和 mDNS 也会被
停止，手机端看到的设备随之消失。

已选择音箱的 `did`、`device_id`、名称、硬件型号和稳定 UDN 已保存在本地
`config.json`。发布局域网服务本身不需要在线刷新这些字段。

在目标 M01 的 `192.168.133.132:1958` 上实测发现了实体音箱原生发布的
`MediaRenderer:1`，其 UDN 与缓存的 Xiaomi `device_id` 一致，并支持标准
AVTransport 和 RenderingControl SOAP 动作。OpenXiaoCast 的虚拟 Renderer
仍有统一命名、媒体代理和承接 AirPlay/MiPlay 的价值，但不必再把实体控制
固定到 MiNA 云接口。

## 决策

- 只要存在已选择且含 `device_id` 的本地音箱配置，就从缓存创建控制器并发布
  DLNA、AirPlay 和 MiPlay 入口，不再要求小米云认证先成功。
- 用缓存的 `device_id` 匹配实体 MediaRenderer 的 SSDP USN，保存其 description
  URL，并优先通过本地 AVTransport/RenderingControl 完成播放、暂停、停止、
  音量和状态读取；本地通道不可用时再回退到 MiNA 云控制。
- Web 分别展示局域网发现、小米云控制和实体音箱本地控制状态。
- 后台认证恢复只刷新凭据和设备元数据，不停止或重建正在工作的 SSDP、HTTP
  和 mDNS 服务。
- 云认证失败不再通过重启进程恢复，避免投送入口周期性消失。
- Cookie 模式只使用 `userId`、`passToken` 和稳定 `deviceId` 换取 micoapi
  token；被拒绝时不再提交空账号和空密码到 `serviceLoginAuth2`。
- 登录请求使用稳定的米家客户端 User-Agent，避免旧依赖每次随机身份带来的
  会话不一致和额外风控变量。

## 后果

### 正面

- 小米 token 过期或云端短时故障时，手机仍能稳定发现投送设备；目标音箱原生
  DLNA 在线时，播放和音量控制也可继续工作。
- 恢复认证不再打断 SSDP/mDNS 广播和已有局域网 HTTP 服务。
- 用户能区分“设备发现正常”和“实体音箱云控制正常”两种健康状态。
- Cookie 续签失败时减少一条注定失败的空凭据请求。

### 负面

- 不提供原生 DLNA 或与网关跨广播域的音箱，在云认证失效期间仍只能保持入口
  可见，不能实际开始播放。
- 如果本地从未成功保存过 `device_id`，仍需要一次有效登录完成设备选择和缓存。

### 中性

- 播放列表并不由 OpenXiaoCast 同步；失效期间缺失的是小米云设备信息刷新和
  MiNA 控制能力。
- 当前本地控制不需要小米 LAN token；不同音箱型号仍需逐台验证原生 DMR 能力。

## 备选方案

### 保持云认证为启动前置条件

实现最简单，但任何认证问题都会扩大为全部协议不可发现，不符合局域网网关的
可用性目标。

### 仅保留 DLNA，关闭 AirPlay 和 MiPlay

改动较小，但三种入口使用同一份缓存映射和同一个实体音箱控制通道，没有理由
让发现层表现不一致。

### 使用局域网 miIO token

可能覆盖不提供原生 DLNA 的型号，但需要额外发现 IP、提取并安全保存设备
token，而且各型号是否支持 `player_play_url` 仍需验证。保留为后续补充通道。

## 参考

- [UPnP MediaRenderer 设备架构](https://openconnectivity.org/developer/specifications/upnp-resources/upnp/mediarenderer2/)
- [MiService 当前认证实现](https://github.com/Yonsm/MiService/blob/main/miservice/miaccount.py)
- [MiService micoapi 授权讨论](https://github.com/yihong0618/MiService/issues/61)
- [xiaomusic Cookie 过期实践讨论](https://github.com/hanxi/xiaomusic/issues/688)
