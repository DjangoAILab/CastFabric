# CastFabric 系统设计

## 目标与边界

CastFabric 是面向局域网音频设备的开源多协议投放层。它接收 DLNA、AirPlay、
MiPlay 和未来自定义 PCM 输入，将同一套播放、暂停、停止和音量语义路由到一个
已配置的输出目标。

首个稳定版本聚焦单机、单局域网和少量音箱，不引入数据库、消息队列或微服务。
标准 DLNA 是必装输出；小米云是可选扩展，不属于系统可用性的前置条件。

## 功能需求

- 自动发现局域网中的 UPnP MediaRenderer，并保存稳定的目标标识与 description URL。
- 允许用户同时启用一个或多个输出音响，并为每台启用的音响发布独立的 CastFabric
  虚拟 DLNA、AirPlay 和 MiPlay 接收器组。
- 音响启停彼此独立，不设置全局唯一的“当前输出”或“默认音响”。
- 所有入口共享统一的名称前缀，默认 `CastFabric`，可在配置中修改。
- 输入会话能够开始、写入、暂停、停止、调节音量并暴露诊断状态。
- 小米账号未配置、token 过期或云端不可用时，标准 DLNA 链路完整工作。
- 旧 `mi_did`、`speakers`、`miplay_name` 配置可以无损迁移并继续启动。

## 非功能需求

- **发现稳定性：** SSDP/mDNS 不得因可选输出适配器失败而停止。
- **故障隔离：** 单个输入或输出失败不得清空其他已注册入口。
- **资源边界：** 实时 PCM 队列有上限；断连后关闭 socket、HTTP server 和解码进程。
- **隐私安全：** Web API 永不返回明文密码、passToken 或完整敏感 Cookie；日志不打印
  凭据和完整协议密钥。
- **可维护性：** 核心接口不导入 `miservice`；厂商依赖只能存在于扩展适配器。
- **兼容性：** 一个发布周期内保留旧 CLI、配置字段、镜像迁移说明和旧 UDN。
- **可验证性：** 无手机、无音箱、无小米账号时可完成协议和路由离线测试。

## 高层架构

```text
 DLNA Renderer      AirPlay Receiver      MiPlay Receiver      future PCM
       │                    │                    │                  │
       └──────────── input adapters ────────────┴──────────────────┘
                                │
                 Receiver Suite / MediaSession
             per-output lifecycle · ownership · diagnostics
                                │
                       PlaybackTarget port
                                │
              ┌─────────────────┴─────────────────┐
              │                                   │
       DLNA output adapter                optional extensions
   SSDP discovery + AVTransport        Xiaomi MiNA / future targets
              │                                   │
              └──────────── physical renderer ────┘
```

## 核心组件

### `PlaybackTarget`

面向输入层的最小异步接口：

```python
class PlaybackTarget(Protocol):
    id: str
    name: str

    async def play_url(self, url: str, *, play_type: int = 2) -> bool: ...
    async def pause(self) -> bool: ...
    async def stop(self) -> bool: ...
    async def set_volume(self, volume: int) -> bool: ...
    async def get_volume(self) -> int: ...
    async def get_status(self) -> PlaybackStatus: ...
```

`play_type` 暂时保留为兼容参数，但只有小米扩展解释它；标准 DLNA 适配器忽略它。

### `DLNATargetDiscovery`

主动发送 MediaRenderer M-SEARCH，按 UDN 合并响应，读取 device description 和服务
URL。发现结果是短期快照；用户选中的目标把 UDN、friendly name 和 location 缓存到
配置。缓存 location 失效时重新发现，而不是要求云端刷新。

### `ReceiverSuite`

每个已启用的输出音响拥有独立的接收器组和媒体会话。接收器组维护自己的目标、入口
实例、当前会话所有者和诊断状态。同一音响内保持“后到输入可以接管”，不同音响间
互不抢占并允许并行播放。协议适配器不能直接引用其他音响的会话。

### 输入适配器

- 虚拟 DLNA：接受外部媒体 URL并直接交给输出目标，保持 DLNA 直通的低延迟优势。
- AirPlay：解码后由有界 HTTP 实时流交给输出目标拉取。
- MiPlay：完成协议协商、AAC 解码为 PCM，再复用同一实时流输出。
- 自定义 PCM：未来仅实现会话和 PCM 写入接口。

### 小米扩展

小米 MiNA 控制保留在独立适配器中，可用于没有原生 DMR 的型号，或作为用户显式启用
的回退。核心启动、局域网目标发现和标准 DLNA 播放不调用认证模块。

## 配置与兼容迁移

新配置逐步引入：

```json
{
  "device_name_prefix": "CastFabric",
  "targets": {
    "uuid:physical-renderer-udn": {
      "kind": "dlna",
      "name": "客厅音箱",
      "location": "http://192.168.133.132:1958/...",
      "enabled": true,
      "receiver_alias": "CastFabric · 客厅音箱"
    }
  },
  "extensions": {
    "xiaomi": {"enabled": false}
  }
}
```

迁移顺序：先读取新字段；没有新目标时从旧 `mi_did/speakers` 构造兼容目标并启用；
旧的单一默认目标字段只作为迁移提示，不继续形成互斥选择关系；旧
`miplay_name=OpenXiaoCast` 视为未自定义并迁移成 `CastFabric`；用户明确设置的旧名称
保持不变。保存时暂不删除旧字段，直到迁移发布完成并有真实部署回滚记录。

## 失败模式

| 故障 | 影响 | 处理 |
|---|---|---|
| SSDP 多播受限 | 无法发现新目标 | 使用缓存 location；Web 显示发现降级 |
| 目标 location 变化 | 首次 SOAP 请求失败 | 以 UDN 重新发现并重试一次 |
| DLNA 目标离线 | 当前播放失败 | 会话进入 error；入口继续发布 |
| 小米 token 过期 | 小米扩展不可用 | 不影响标准 DLNA 和所有入口发现 |
| AirPlay/MiPlay 解码退出 | 当前实时流停止 | 清理会话和子进程，保留其他服务 |
| 同一音响的两个输入同时接管 | 前一流被停止 | 该音响的会话串行切换并记录接管原因 |
| 不同音响同时播放 | 无冲突 | 各 Receiver Suite 独立维护会话和输出 |
| 配置迁移异常 | 启动失败风险 | 原文件原子保存；兼容字段只增不删 |

## 验证与发布门槛

1. 单元测试覆盖目标接口、发现去重、配置迁移和故障回退。
2. 离线集成测试覆盖虚拟 DLNA/AirPlay/MiPlay 到 fake DLNA target。
3. Docker 构建、健康检查、冷启动、旧配置挂载和回滚镜像验证通过。
4. Home Server 上为每台启用音响同时发现实体 DMR 和独立的 `CastFabric · <音响>`。
5. DLNA 直通、AirPlay、MiPlay 分别完成播放/暂停/音量回归；认证失效测试不影响核心。
