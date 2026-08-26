# OpenXiaoCast

OpenXiaoCast 是面向小爱音箱的多协议局域网投送网关。它保留 MiAir 的
DLNA 与 AirPlay 能力，并新增实验性的妙播（MiPlay）接收链路，让手机发现
OpenXiaoCast 后，音频经过统一的实时流通道送到已配置的小米音箱。

> 妙播的离线完整链路已经通过自动化验证；K60/M01 真机兼容性仍需按
> [真机认证清单](docs/testing/miplay-real-device-checklist.md)完成最终确认。

## 当前能力

- DLNA 音频渲染器
- AirPlay 音频接收
- 妙播设备发现、控制协商、反向 WFD/RTSP 和 AAC 媒体接收（实验性）
- 妙播 AAC → 48 kHz 双声道 PCM → HTTP WAV → 小米音箱
- Web 配置、状态诊断与无需真机的妙播链路自测
- amd64/arm64 Docker 镜像构建和 GHCR 发布流水线

## Docker 部署

局域网发现依赖 mDNS，推荐在 Linux 主机上使用 host 网络：

```bash
git clone https://github.com/wangerzi/MiAir.git OpenXiaoCast
cd OpenXiaoCast
docker compose up -d
```

管理页面为 `http://宿主机IP:8300`。首次启动会在 `./conf` 生成配置文件；
在 Web 页面填写小米账号并选择目标音箱。妙播默认名称为 `OpenXiaoCast`，
控制端口为 `8899`。

已有部署在仓库改名之前仍可继续使用兼容镜像名
`ghcr.io/wangerzi/miair:latest`。Docker Desktop 使用 host 网络时，需先确认
当前版本已启用 host networking；否则建议直接在 Linux/OpenWrt 主机部署。

## 本地开发与诊断

需要 Python 3.10+ 和 FFmpeg：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
openxiaocast --conf-path conf
```

无需手机或音箱即可运行完整的 TCP 控制、RTSP、RTP/MPEG-TS、解码链路：

```bash
openxiaocast-miplay self-test --duration 0.35
```

扫描局域网中的妙播接收端：

```bash
openxiaocast-miplay scan --timeout 5
```

向另一台 OpenXiaoCast 接收端推送测试音（只用于诊断）：

```bash
openxiaocast-miplay simulate --target 192.168.1.20 --duration 1
```

## 交付状态

实现阶段、验收门槛和失败回退策略维护在
[OpenXiaoCast 路线图](docs/roadmap/2026-08-26-openxiaocast-roadmap.md)。协议研究来源与
独立实现边界见[研究说明](docs/research/miplay-protocol-sources.md)。

## 兼容与致谢

为兼容现有安装，Python 包名与 `miair` 命令暂时保留。项目延续并感谢
[MiAir](https://github.com/KiriChen-Wind/MiAir)、
[XiaoMusic](https://github.com/hanxi/xiaomusic)、
[AirPlay2 Receiver](https://github.com/openairplay/airplay2-receiver) 和
[Macast](https://github.com/xfangfang/Macast) 的既有工作。妙播部分没有直接引入
许可证不明确的第三方实现代码。
