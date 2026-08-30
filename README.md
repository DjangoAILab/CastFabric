<p align="center"><img src="docs/assets/castfabric-mark.svg" width="104" alt="CastFabric 标志"></p>
<h1 align="center">CastFabric</h1>
<p align="center"><strong>不挑协议，投了就播。</strong></p>
<p align="center">面向局域网音响的开源多协议投放层：一台音响，一组独立的 DLNA、AirPlay 与妙播入口。</p>

<p align="center">
  <a href="https://github.com/wangerzi/CastFabric/actions/workflows/test.yml"><img alt="测试状态" src="https://github.com/wangerzi/CastFabric/actions/workflows/test.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/wangerzi/CastFabric/releases"><img alt="GitHub 发布" src="https://img.shields.io/github/v/release/wangerzi/CastFabric?include_prereleases&sort=semver"></a>
  <a href="https://github.com/wangerzi/CastFabric/pkgs/container/castfabric"><img alt="GHCR 镜像" src="https://img.shields.io/badge/GHCR-amd64%20%7C%20arm64-1f2523"></a>
  <a href="LICENSE"><img alt="MIT 许可证" src="https://img.shields.io/badge/license-MIT-cb7a18"></a>
</p>
<p align="center">简体中文 · <a href="README.en.md">English</a></p>

![CastFabric 控制台总览](docs/assets/console-overview.png)

CastFabric 把手机和电脑发来的 DLNA、AirPlay、妙播（MiPlay）音频，统一送到支持标准
UPnP/DLNA MediaRenderer 的局域网音响。标准声路完全不依赖小米账号；小米云只保留为
显式启用的兼容扩展。

默认情况下，每台已启用音响会对应一组 `CastFabric · <音响名称>` 接收入口。不同音响
可以并行播放，同一音响内的协议会话由独立 Receiver Suite 协调，不存在“全局默认音响”。

## 为什么是 CastFabric

- **多协议、同一出口**：虚拟 DLNA、AirPlay、妙播最终都落到标准 DLNA 输出适配器。
- **多音响、彼此隔离**：每台输出音响拥有独立 Receiver Suite、会话、端口和活动记录。
- **不绑定厂商账号**：DLNA 扫描、发现与播放不受小米 token 或公网状态影响。
- **保留原生直投**：实体音响自己的 DLNA 仍然存在，追求最低延迟时可以直接选择它。
- **成功必须可验证**：控制命令成功后，还要确认实体音响真的拉取 HTTP 音频流，才记录
  输出已建立；“接受了命令但没有声音”会得到明确错误码。
- **不猜测产品数据**：控制台不根据 URL 猜发送 App，也不把解码耗时冒充端到端听感延迟。
- **默认保护隐私**：事件与诊断包会移除 URL 查询参数、凭据、完整 IPv4/IPv6 地址。

## 声路模型

```text
手机 / 电脑
  ├─ DLNA ───────┐
  ├─ AirPlay ────┼─▶ Receiver Suite（每台音响独立）─▶ DLNA 输出 ─▶ 实体音响
  └─ 妙播 ───────┘

音响 A：DLNA + AirPlay + MiPlay ─▶ 输出 A
音响 B：DLNA + AirPlay + MiPlay ─▶ 输出 B
```

妙播当前声路为 AAC → 48 kHz 双声道 PCM → HTTP WAV/L16 → 实体 DLNA DMR。妙播接收端
基于公开资料和抓包行为独立实现，随 `0.10` 版本以预发布功能提供。

## Docker 快速部署

SSDP 和 mDNS 依赖局域网组播，推荐在 Linux Home Server 上使用 host 网络：

```bash
git clone https://github.com/wangerzi/CastFabric.git
cd CastFabric
docker compose pull
docker compose up -d
```

打开 `http://宿主机IP:8300`，进入「连接配置」扫描并启用输出音响。标准 DLNA 音响不需要
登录小米账号。配置保存在 `./conf`。

多网卡或自动 IP 选择不正确时，在 `.env` 中指定局域网地址：

```dotenv
CASTFABRIC_HOSTNAME=192.168.1.10
CASTFABRIC_CONFIG_DIR=./conf
```

| 用途 | 默认端口 |
|---|---:|
| Web 控制台 | `8300/tcp` |
| 虚拟 DLNA 与媒体服务 | `8200/tcp` |
| 妙播控制起始端口 | `8899/tcp` |
| SSDP / mDNS | host 网络中的 `1900/udp`、`5353/udp` |

也可以使用仓库中的非破坏式管理脚本：

```bash
./deploy.sh local       # 从当前源码构建
./deploy.sh pull        # 拉取已发布镜像
./manage.sh status
./manage.sh logs -f
```

## 控制台

- **总览**：在单屏内展示当前声路、可确认的发送端信息、协议与输出音响；多声路最多展示
  三条，其余汇总，不因音响数量增加而破坏布局。
- **音响**：管理多台输出音响、接收入口名称、启停状态和每协议健康。
- **活动**：查看结构化会话与失败原因；诊断信息经过服务端脱敏。

连接、播放偏好、端口和可选扩展集中在二级「连接配置」面板；界面支持中英文切换。

<p align="center"><img src="docs/assets/console-mobile.png" width="360" alt="CastFabric 移动端控制台"></p>

## 本地开发与验证

需要 Python 3.10+ 和 FFmpeg：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
castfabric --conf-path conf
```

```bash
python -m pytest -q
castfabric-miplay self-test --duration 0.35
castfabric-miplay scan --timeout 5
castfabric-miplay simulate --target 192.168.1.20 --duration 1
```

当前发布门槛同时覆盖：单元/集成测试、双实体 DMR 协议 POC、旧配置迁移与回滚读取、
诊断隐私、Docker 冷启动、镜像内 wire self-test，以及 amd64/arm64 GHCR 构建。

## 迁移、架构与协议资料

- [MiAir / OpenXiaoCast 迁移与回滚](docs/migration/miair-to-castfabric.md)
- [Runtime v2 架构](docs/architecture/castfabric-runtime-v2-design.md)
- [每输出音响独立 Receiver Suite](docs/adr/0004-one-receiver-suite-per-output.md)
- [实体 DMR 拉流验证边界](docs/adr/0007-verify-physical-output-pull.md)
- [控制台数据契约](docs/architecture/castfabric-console-data-contract.md)
- [妙播协议研究与独立实现边界](docs/research/miplay-protocol-sources.md)
- [Home Server 验收清单](docs/testing/castfabric-home-server-checklist.md)

## 兼容与开源

项目使用 [MIT License](LICENSE)。迁移期继续提供 `miair`、`openxiaocast`、
`openxiaocast-miplay` 命令，以及 `miair` Python 包；已有 `config.json`、配置卷和虚拟设备
UDN 不会被主动删除或重新生成。

CastFabric 延续并感谢 [MiAir](https://github.com/KiriChen-Wind/MiAir)、
[XiaoMusic](https://github.com/hanxi/xiaomusic)、
[AirPlay2 Receiver](https://github.com/openairplay/airplay2-receiver) 和
[Macast](https://github.com/xfangfang/Macast) 的既有工作。妙播部分没有直接引入许可证不明确的
第三方实现代码。
