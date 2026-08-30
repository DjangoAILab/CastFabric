# CastFabric 家庭音频控制台参考研究

## 研究目的

修正控制台原型 v1 的两个问题：

1. 已确认的 slogan 虽然还在页头，却被另一句巨型状态文案抢走主视觉，重新产生了
   “为了像首页而写一句大话”的感觉；
2. 为避免装饰性动画，原型把有用的图形也一并删掉，退化成通用卡片列表，失去声音
   路径和多房间关系本可以带来的直观性。

本研究不寻找一张可照抄的页面，而是分别学习多房间音频、播放路径、家庭设备总览、
基础设施拓扑和设备接管。

## 案例矩阵

### Roon：Zone 与 Signal Path

来源：

- [Roon Zone 文档](https://help.roonlabs.com/portal/en/kb/articles/zone)
- [Roon Signal Path 文档](https://help.roonlabs.com/portal/en/kb/articles/signal-path)

Roon 把每个房间/输出定义为独立 Zone，并让当前 Zone 在播放器固定位置持续可见；
Signal Path 则把原本不可见的音频处理过程画成可展开路径，并用颜色表达质量等级。

**适合借鉴：** 音响是稳定的一等对象；路径图只有在解释真实链路时出现；总览显示
“在哪播”，详情显示“怎么到达”。

**不照搬：** CastFabric 不是音乐库和播放器，不需要专辑封面、队列或长期占据页面的
播放控制条。

### Sonos：多房间系统总览与重设计教训

来源：

- [Sonos 2024 重设计说明](https://investors.sonos.com/news-and-events/investor-news/latest-news/2024/Sonos-Unveils-Completely-Reimagined-Sonos-App-Bringing-Services-Content-and-System-Controls-to-One-Customizable-Home-Screen/default.aspx)
- [Sonos 2026 导航调整报道](https://www.whathifi.com/speakers/wireless-speakers/the-sonos-app-is-getting-a-major-refresh-this-week-heres-whats-new)
- [Sonos CEO 对重设计问题的复盘](https://www.techradar.com/audio/multi-room/sonos-ceo-tom-conrad-interview-app-changes)

2024 方案试图把内容、搜索和全屋控制集中到一个可定制首页，并把系统控制放进上滑层；
实际使用暴露出隐藏手势、基础能力缺失和导航不符合用户习惯的问题。2026 的调整重新
采用 Home / System / Search 三个直白入口，并强化播放器列表与音量控制。

**适合借鉴：** 多音响系统必须让“全部播放器/音响”有固定、可见的位置；视觉重构不
能掩盖基础状态和管理动作。

**必须避免：** 把系统控制藏在手势中；为了新首页删减旧能力；一次同时替换架构、
导航和功能。

### Home Assistant：以房间组织家庭设备

来源：

- [Home Assistant Dashboard](https://www.home-assistant.io/dashboards/)
- [Home Assistant Area Card](https://www.home-assistant.io/dashboards/area/)

Home Assistant 把首页定义为“打开后立刻知道家里正在发生什么”的视图，并允许 Area
Card 使用房间图片、图标或紧凑模式，把同一空间里的状态和控制归在一起。

**适合借鉴：** 用房间而不是协议组织首页；每个房间可拥有图形身份；异常和活跃状态
覆盖在空间图上，比三个协议卡片更符合家庭用户心智。

**不照搬：** 不开放任意卡片搭建器，也不让用户自己编排首页；CastFabric 的对象和
任务更少，应保持强默认结构。

### UniFi：拓扑只在关系真实时有价值

来源：[UniFi 产品介绍](https://help.ui.com/hc/en-us/articles/360012192813-Introduction-to-UniFi)

UniFi 用实时仪表盘和可视拓扑表达网关、交换机、接入点与终端之间的真实层级。

**适合借鉴：** 当图形能回答“输入来自哪里、经过 CastFabric、最终到哪台音响”时，
路径线和节点是有价值的信息图。

**必须避免：** CastFabric 没有网络交换层级，不能为了看起来专业而伪造复杂拓扑。
首页只画一层输入和一层音响；转码、HTTP 拉流等细节放到会话详情。

### Spotify Connect：设备接管动作足够简单

来源：[Spotify Connect Basics](https://developer.spotify.com/documentation/commercial-hardware/implementation/guides/connect-basics)

Connect 的核心交互是一件事：在设备列表选择音响，播放即转移，手机继续作为遥控器。

**适合借鉴：** CastFabric 的接收端状态必须和发送端看到的设备名对应；“正在由谁播放”
和音量变化要及时反馈。

**不照搬：** CastFabric 不是发送端，因此首页不应再造一个设备选择器。

### Tailscale：设备状态列表与诊断筛选

来源：

- [Tailscale 设备管理](https://tailscale.com/docs/features/access-control/device-management/how-to/set-up)
- [Tailscale 设备筛选](https://tailscale.com/docs/features/access-control/device-management/how-to/filter)

Tailscale 的机器列表以稳定设备身份、在线/最后出现时间和少量标签为核心，详细属性与
操作进入设备详情；规模变大后再提供筛选。

**适合借鉴：** 音响列表必须稳定，不因扫描过程闪空；最近出现时间、状态和筛选属于
活动/管理层，而不是英雄视觉。

## 三个可行方向

### A. Whole-home Sound Map（推荐）

首页中心是一张轻量的“全屋声场图”：不是写实户型，而是三个有空间感的房间切片，
每个房间包含可识别的音响插画、名称和状态。DLNA、AirPlay、MiPlay 作为三个小型输入
符号出现在画面边缘；只有存在会话时，信号线才流向实际播放的房间。

优点是第一眼同时理解“支持什么、有哪些音响、哪台正在播”。它保留之前带图方案的
记忆点，又能自然支持多音响。风险是图形必须适配音响数量变化，因此只在首页展示前
三到四台，其余以 `+N` 进入音响页。

### B. Illustrated Room Gallery

用横向房间画廊代替普通卡片，每个音响拥有一幅抽象房间插画，播放状态通过色彩、
波纹和媒体来源覆盖层表达。

优点是温暖、易懂、扩展数量简单；缺点是无法直观表达协议进入不同音响的路径，容易
退化成智能家居卡片集合。

### C. Signal Path Workbench

首页上半部显示当前会话的大型路径图，下半部显示全部音响；空闲时路径区收缩为系统
健康摘要。

优点是诊断能力强，最贴近 Roon；缺点是没有播放时缺少视觉中心，而且会让 CastFabric
看起来像工程工具。

## 推荐组合

采用 **A 作为首页 + C 作为会话详情**。首页的图回答“整个家里现在怎样”；点击正在
播放的音响后，详情图回答“这一路声音怎样到达”。房间管理、配置和活动仍在二级页面。

## 文案与版式修正

- 唯一品牌 slogan 固定为：`不挑协议，投了就播`。
- 不再额外制造巨型主标题。slogan 采用一行、中等字号，和声场图组成同一个视觉整体。
- `全屋声路正常`、`1 台需要处理` 等只作为紧凑状态，不使用广告式排版。
- 首页的“图”承担主视觉；音响列表、最近活动承担数据与管理，两者不互相冒充。
- 图形里的协议名称是能力图例，不是三个并列功能卖点。

## 下一版原型验收

1. 不看说明文字也能指出有几台音响、哪台在播放、从哪个协议进入；
2. slogan 不与第二句巨型文案竞争；
3. 图形在一台、三台和六台音响时仍有明确扩展规则；
4. 空闲、播放、部分离线三种状态下，图形变化对应真实数据；
5. 移动端把声场图改为纵向房间带，不缩成无法辨认的小图；
6. 连接配置、音响管理和活动记录仍保持二级层级；
7. 每项设计决策都能回指本研究中的案例或明确的产品约束。

