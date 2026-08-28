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

需要明确的是：当前 DLNA 入口是 OpenXiaoCast 模拟的渲染器，并不代表实体
小爱音箱原生提供了可直接调用的 DLNA Renderer。现有播放、暂停和音量控制
最终仍通过 MiNA 云接口发送给实体音箱。

## 决策

- 只要存在已选择且含 `device_id` 的本地音箱配置，就从缓存创建控制器并发布
  DLNA、AirPlay 和 MiPlay 入口，不再要求小米云认证先成功。
- 小米云认证状态只决定实体音箱控制是否可用。失效时 Web 状态显示为“局域网
  设备已发布、云控制暂不可用”。
- 后台认证恢复只刷新凭据和设备元数据，不停止或重建正在工作的 SSDP、HTTP
  和 mDNS 服务。
- 云认证失败不再通过重启进程恢复，避免投送入口周期性消失。
- Cookie 模式只使用 `userId`、`passToken` 和稳定 `deviceId` 换取 micoapi
  token；被拒绝时不再提交空账号和空密码到 `serviceLoginAuth2`。
- 登录请求使用稳定的米家客户端 User-Agent，避免旧依赖每次随机身份带来的
  会话不一致和额外风控变量。

## 后果

### 正面

- 小米 token 过期或云端短时故障时，手机仍能稳定发现投送设备。
- 恢复认证不再打断 SSDP/mDNS 广播和已有局域网 HTTP 服务。
- 用户能区分“设备发现正常”和“实体音箱云控制正常”两种健康状态。
- Cookie 续签失败时减少一条注定失败的空凭据请求。

### 负面

- 云认证失效期间，设备虽然可见，但当前实现仍不能让实体音箱开始播放或改变
  音量；客户端会得到控制失败。
- 如果本地从未成功保存过 `device_id`，仍需要一次有效登录完成设备选择和缓存。

### 中性

- 播放列表并不由 OpenXiaoCast 同步；失效期间缺失的是小米云设备信息刷新和
  MiNA 控制能力。
- 真正完全离线播放需要另行验证目标型号是否支持局域网 miIO
  `player_play_url`，并安全保存实体设备的 LAN token。这是后续独立能力，不把
  它与公开的 DLNA 发现协议混为一谈。

## 备选方案

### 保持云认证为启动前置条件

实现最简单，但任何认证问题都会扩大为全部协议不可发现，不符合局域网网关的
可用性目标。

### 仅保留 DLNA，关闭 AirPlay 和 MiPlay

改动较小，但三种入口使用同一份缓存映射和同一个实体音箱控制通道，没有理由
让发现层表现不一致。

### 直接控制实体音箱的本地 DLNA 服务

只有在目标音箱确实实现标准 MediaRenderer 时才成立。当前 M01 链路的实体
控制来自 MiNA，不应在未验证设备能力前假设存在该服务。

## 参考

- [UPnP MediaRenderer 设备架构](https://openconnectivity.org/developer/specifications/upnp-resources/upnp/mediarenderer2/)
- [MiService 当前认证实现](https://github.com/Yonsm/MiService/blob/main/miservice/miaccount.py)
- [MiService micoapi 授权讨论](https://github.com/yihong0618/MiService/issues/61)
- [xiaomusic Cookie 过期实践讨论](https://github.com/hanxi/xiaomusic/issues/688)
