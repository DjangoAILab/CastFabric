# CastFabric Landing Page AI 增量契约

## 目的

在不改变已确认的暖色、本地优先视觉方向下，让首屏准确表达 CastFabric 已经同时服务
手机、电脑与 AI Agent，并避免把未来规划写成已经支持。

## 信息与视觉结构

- 首屏标题继续使用“不挑协议，投了就播”。
- 左侧输入列表按等权条目展示 Android / MiPlay、Apple / AirPlay、DLNA 控制端和
  AI Agent / MCP；AI 不成为压倒原有投放能力的营销装饰。
- 中央 CastFabric 仍是每台音响独立的 Receiver Suite / Playback Target，不出现含义
  不明的缩写。
- 右侧只展示已实现的标准 DLNA 本地输出和默认关闭的 Xiaomi MiNA 兼容输出。
- 首屏必须明确 URL、本地文件和实时 PCM 是 AI 已实现的音频入口；TTS、媒体库与服务端
  播放列表不列为能力。
- GitHub、GHCR、Pages 与部署命令统一指向 `DjangoAILab/CastFabric`。

## 状态、响应式与输入方式

- 桌面 `1440 × 900` 下 hero 不超过一屏且无横向滚动。
- 移动端允许纵向滚动，四种输入和两种输出不得丢失或横向溢出。
- 中英文切换后，英文可见区域不得残留中文；技术专名 MCP、DLNA、AirPlay、MiPlay
  保持原文。
- 复制部署命令必须有成功反馈；所有按钮可通过键盘访问并有可见焦点。
- `prefers-reduced-motion` 下关闭路径脉冲与入场位移，不影响信息阅读。

## DesignQM 验收

- D1 结构：输入、Fabric、输出的方向和权重清楚。
- D2 视觉：沿用暖色信号主题、字号与间距系统，不增加新的视觉语言。
- D3 响应式：桌面单屏、移动端无横向溢出。
- D4 交互：语言与复制状态可见、键盘可操作。
- D5 无障碍：语义标题、区域标签、焦点与减弱动效完整。
- D6 真实性：只写已通过自动化与 Home Server 实机验证的能力。
