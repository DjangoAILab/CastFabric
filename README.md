# CastFabric

CastFabric 是面向局域网音频设备的开源多协议投放层。它把 DLNA、AirPlay、
妙播（MiPlay）和未来的自定义音频输入，统一路由到支持标准 DLNA
MediaRenderer 的音箱；小米云只是可选兼容扩展，不再是发现和播放的前置条件。

默认情况下，手机会看到 `CastFabric · <音箱名称>`。这个前缀可以在 Web 页面修改。
实体音箱自己的原生 DLNA 设备可能同时出现，这是为了保留低延迟直投和 CastFabric
统一入口两种选择。

## 当前能力

- 扫描并选择任意标准 UPnP/DLNA MediaRenderer，无需厂商账号。
- 发布统一的虚拟 DLNA 音频渲染器。
- 接收 AirPlay 音频并通过目标音箱的本地 DLNA 通道播放。
- 接收妙播发现、控制、反向 WFD/RTSP 和 AAC 媒体流（实验性）。
- 妙播 AAC → 48 kHz 双声道 PCM → HTTP WAV/L16 → DLNA 输出目标。
- 旧 MiAir 配置自动迁移，本地 DLNA 优先，小米 MiNA 云作为可选回退。
- 无手机、无音箱、无小米账号的离线协议自测。
- amd64/arm64 Docker 镜像测试与 GHCR 发布流水线。

## Docker 部署

SSDP 和 mDNS 依赖局域网组播，推荐在 Linux 主机上使用 host 网络：

```bash
git clone https://github.com/wangerzi/CastFabric.git
cd CastFabric
docker compose up -d
```

打开 `http://宿主机IP:8300`，从“DLNA 输出目标”中选择音箱即可。标准 DLNA
链路不要求登录小米账号。配置保存在 `./conf`，默认端口如下：

- Web：`8300/tcp`
- 虚拟 DLNA/媒体服务：`8200/tcp`
- 妙播控制：`8899/tcp`
- SSDP：`1900/udp`（host 网络）
- mDNS：`5353/udp`（host 网络）

多网卡或自动 IP 选择不正确时，在 `.env` 中设置：

```dotenv
CASTFABRIC_HOSTNAME=192.168.133.5
```

也可以使用仓库中的非破坏式部署脚本：

```bash
./deploy.sh local       # 从当前源码构建
./deploy.sh pull        # 拉取已发布镜像
./manage.sh status
./manage.sh logs -f
```

## 本地开发与诊断

需要 Python 3.10+ 和 FFmpeg：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
castfabric --conf-path conf
```

运行完整测试和妙播离线链路：

```bash
python -m pytest -q
castfabric-miplay self-test --duration 0.35
```

扫描妙播接收端或向测试接收端发送诊断音：

```bash
castfabric-miplay scan --timeout 5
castfabric-miplay simulate --target 192.168.1.20 --duration 1
```

## 架构与实施状态

- [架构决策：CastFabric 与端口—适配器核心](docs/adr/0003-adopt-castfabric-and-port-adapter-core.md)
- [系统设计](docs/architecture/castfabric-system-design.md)
- [阶段实施计划](docs/plans/2026-08-29-castfabric-refactor.md)
- [MiAir/OpenXiaoCast 迁移说明](docs/migration/miair-to-castfabric.md)
- [妙播真机验证清单](docs/testing/miplay-real-device-checklist.md)
- [妙播协议研究与独立实现边界](docs/research/miplay-protocol-sources.md)

## 兼容与开源

项目使用 MIT 许可证。迁移期继续提供 `miair`、`openxiaocast`、
`openxiaocast-miplay` 命令，以及 `miair` Python 包；已有 `config.json`、配置卷和
虚拟设备 UDN 不会被主动删除或重新生成。

CastFabric 延续并感谢 [MiAir](https://github.com/KiriChen-Wind/MiAir)、
[XiaoMusic](https://github.com/hanxi/xiaomusic)、
[AirPlay2 Receiver](https://github.com/openairplay/airplay2-receiver) 和
[Macast](https://github.com/xfangfang/Macast) 的既有工作。妙播部分没有直接引入
许可证不明确的第三方实现代码。
