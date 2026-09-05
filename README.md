<p align="center"><img src="docs/assets/castfabric-mark.svg" width="104" alt="CastFabric 标志"></p>
<h1 align="center">CastFabric</h1>
<p align="center"><strong>不挑协议，投了就播。</strong></p>
<p align="center">让手机、电脑与 AI Agent 共用一套局域网音响能力：DLNA、AirPlay、妙播与 MCP。</p>

<p align="center">
  <a href="https://github.com/DjangoAILab/CastFabric/actions/workflows/test.yml"><img alt="测试状态" src="https://github.com/DjangoAILab/CastFabric/actions/workflows/test.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/DjangoAILab/CastFabric/releases"><img alt="GitHub 发布" src="https://img.shields.io/github/v/release/DjangoAILab/CastFabric?include_prereleases&sort=semver"></a>
  <a href="https://github.com/DjangoAILab/CastFabric/pkgs/container/castfabric"><img alt="GHCR 镜像" src="https://img.shields.io/badge/GHCR-amd64%20%7C%20arm64-1f2523"></a>
  <a href="LICENSE"><img alt="MIT 许可证" src="https://img.shields.io/badge/license-MIT-cb7a18"></a>
</p>
<p align="center">简体中文 · <a href="README.en.md">English</a></p>

![CastFabric 控制台总览](docs/assets/console-overview.png)

CastFabric 把手机、电脑和 AI Agent 发来的音频，统一送到局域网音响。手机继续使用
DLNA、AirPlay、妙播（MiPlay）；AI 通过内嵌 MCP 播放 URL、本地文件或实时 PCM，也可以管理
持久音频资源和由服务端持续执行的播放列表。
核心输出面向标准 UPnP/DLNA MediaRenderer，完全不依赖小米账号；小米云只保留为显式
启用的旧设备兼容扩展。

默认情况下，每台已启用音响会对应一组 `CastFabric · <音响名称>` 接收入口。不同音响
可以并行播放，同一音响内的协议会话由独立 Receiver Suite 协调，不存在“全局默认音响”。

## 为什么是 CastFabric

- **多协议、同一出口**：虚拟 DLNA、AirPlay、妙播最终都落到标准 DLNA 输出适配器。
- **多音响、彼此隔离**：每台输出音响拥有独立 Receiver Suite、会话、端口和活动记录。
- **不绑定厂商账号**：DLNA 扫描、发现与播放不受小米 token 或公网状态影响。
- **让 AI 直接找到音响**：同一服务的 `/mcp` 暴露发现、管理、播放与控制，无需部署
  sidecar、第二个容器或额外端口。
- **保留原生直投**：实体音响自己的 DLNA 仍然存在，追求最低延迟时可以直接选择它。
- **成功必须可验证**：控制命令成功后，还要确认实体音响真的拉取 HTTP 音频流，才记录
  输出已建立；“接受了命令但没有声音”会得到明确错误码。
- **不猜测产品数据**：控制台不根据 URL 猜发送 App，也不把解码耗时冒充端到端听感延迟。
- **默认保护隐私**：事件与诊断包会移除 URL 查询参数、凭据、完整 IPv4/IPv6 地址。

## 声路模型

```text
手机 / 电脑 ── DLNA / AirPlay / 妙播 ──┐
                                      ├─▶ Receiver Suite（每台音响独立）─▶ DLNA 输出 ─▶ 实体音响
AI Agent ── MCP：URL / 文件 / 实时 PCM ┘

音响 A：DLNA + AirPlay + MiPlay + MCP ─▶ 输出 A
音响 B：DLNA + AirPlay + MiPlay + MCP ─▶ 输出 B
```

妙播当前声路为 AAC → 48 kHz 双声道 PCM → HTTP WAV/L16 → 实体 DLNA DMR。妙播接收端
基于公开资料和抓包行为独立实现，随 `0.10` 版本以预发布功能提供。

## AI 与 MCP

CastFabric `0.11` 在现有 Web 服务上直接提供 Streamable HTTP MCP：控制台地址若为
`http://192.168.1.10:8300`，MCP 地址就是 `http://192.168.1.10:8300/mcp`。它复用同一套
`target_id`、播放状态机和输出适配器，并非另一套播放服务。

当前提供 32 个短调用工具：

- 管理：系统状态、列出音响、扫描音响、启用/停用或重命名音响；
- 播放：HTTP(S) URL、Agent 本地文件、`s16le / 48 kHz / 双声道` 实时 PCM；
- 内容：持久音频上传与元数据、外部 URL 资源、播放列表定义、显式续播候选和只读历史；
- 控制：查询状态、暂停、继续、停止、绝对秒定位、上一项、下一项、指定项和音量。

仓库中的 [CastFabric Agent Skill](skills/castfabric/SKILL.md) 进一步封装了文件上传、FFmpeg
实时转码、持久文件上传和一次性的 Playlist manifest 导入。播放列表启动后完全由 CastFabric
服务端推进，helper 退出不会中断。会话 ID 只作为防止误控新会话的并发条件，不是素材 ID。
CastFabric **不内置 TTS、通用媒体库或播放队列**；失败会记录原因并停止，不会自动跳过、
重试或换音箱。

> 当前 MCP 面向可信局域网，尚未提供公网认证。不要把 `/mcp` 直接暴露到互联网。

### 延迟边界

- **原生 DLNA 直投**：在当前测试音箱上通常低于 1 秒，适合优先考虑响应速度的场景。
- **AirPlay / 妙播实时桥接**：在当前测试音箱上听感约 4 秒。CastFabric 的 MiPlay 解码首帧
  只需约 3–4 ms，音箱开始拉流并收到首批 PCM 约需 0.1 秒；剩余等待最符合实体 DMR 对
  实时 HTTP 流进行固件预读的行为，无法由 CastFabric 通过标准 DLNA 控制指令关闭。

这不是所有音响都固定为 4 秒，但在新增原生或低延迟输出适配器之前，不承诺视频口型同步。
需要最低延迟时，请直接选择实体音响的 DLNA 入口。测试证据、已排除方案与后续 POC 见
[实时桥接延迟边界](docs/architecture/live-bridge-latency.md)。

## Docker 快速部署

SSDP 和 mDNS 依赖局域网组播，推荐在 Linux Home Server 上使用 host 网络：

```bash
git clone https://github.com/DjangoAILab/CastFabric.git
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
- **播放列表**：在内容工作台管理可复用音频、播放列表和只读播放记录；可以全部播放或从
  明确的一项开始，并在小弹窗中选择音响。
- **活动**：查看结构化会话与失败原因；诊断信息经过服务端脱敏。
- **AI 接入**：复制当前实例的 MCP 地址、客户端配置与验证提示词；不会新增独立服务端口。

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

当前发布门槛同时覆盖：单元/集成测试、Agent Skill 测试、MCP 冷启动、真实音响文件与
PCM 拉流、双实体 DMR 协议 POC、旧配置迁移与回滚读取、诊断隐私，以及 amd64/arm64
GHCR 构建。

## 迁移、架构与协议资料

- [MiAir / OpenXiaoCast 迁移与回滚](docs/migration/miair-to-castfabric.md)
- [Runtime v2 架构](docs/architecture/castfabric-runtime-v2-design.md)
- [每输出音响独立 Receiver Suite](docs/adr/0004-one-receiver-suite-per-output.md)
- [实体 DMR 拉流验证边界](docs/adr/0007-verify-physical-output-pull.md)
- [AirPlay / 妙播实时桥接延迟边界](docs/architecture/live-bridge-latency.md)
- [控制台数据契约](docs/architecture/castfabric-console-data-contract.md)
- [妙播协议研究与独立实现边界](docs/research/miplay-protocol-sources.md)
- [Home Server 验收清单](docs/testing/castfabric-home-server-checklist.md)
- [MCP 与 Agent Skill 设计](docs/plans/2026-09-01-castfabric-mcp-agent-skill-design.md)
- [服务端播放列表架构决策](docs/adr/0011-persist-media-assets-and-run-server-playlists.md)

## 兼容与开源

项目使用 [MIT License](LICENSE)。迁移期继续提供 `miair`、`openxiaocast`、
`openxiaocast-miplay` 命令，以及 `miair` Python 包；已有 `config.json`、配置卷和虚拟设备
UDN 不会被主动删除或重新生成。

CastFabric 延续并感谢 [MiAir](https://github.com/KiriChen-Wind/MiAir)、
[XiaoMusic](https://github.com/hanxi/xiaomusic)、
[AirPlay2 Receiver](https://github.com/openairplay/airplay2-receiver) 和
[Macast](https://github.com/xfangfang/Macast) 的既有工作。妙播部分没有直接引入许可证不明确的
第三方实现代码。
