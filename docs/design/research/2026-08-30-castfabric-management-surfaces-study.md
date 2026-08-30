# CastFabric 音响管理、活动与配置界面研究

## 研究范围

首页已经确定为固定三轨的实时摘要。本研究只解决三个管理面：完整音响集合、可诊断的
结构化活动、不会挤占首页的连接配置。

## 参考产品

### Sonos System view：输出是同级系统对象

Sonos System view 同时展示系统内全部输出和活跃内容；产品设置则进入独立的 System
Settings。输出选择不会暗中移动当前播放内容，说明“浏览/选择对象”和“改变会话”必须
有清楚边界。

**借鉴：** 音响页使用稳定的同级列表；进入详情才编辑名称和系统属性；启停必须写清
影响范围。

**避免：** CastFabric 不控制音乐内容、不做房间分组或播放队列，不复制播放器控件。

来源：[Sonos App guide](https://www.sonos.com/en-us/guides/sonosapp)

### Home Assistant Devices & Services：物理设备与能力状态分层

Home Assistant 把 device 视为物理或逻辑单元，把数据点和控制能力拆成 entities，并在
Devices & Services 下集中管理。这个分层适合 CastFabric 的 OutputTarget 与 Receiver
Suite，但 CastFabric 对象更少，不需要暴露通用实体系统。

**借鉴：** 音响详情先展示稳定身份，再展示三种入口和输出能力；异常修复提供明确入口。

**避免：** 不把 DLNA/AirPlay/MiPlay 拆成用户需要逐个管理的大量“实体”。

来源：

- [Home Assistant entities and domains](https://www.home-assistant.io/docs/configuration/entities_domains/)
- [Home Assistant device architecture](https://github.com/home-assistant/developers.home-assistant/blob/master/docs/architecture/devices-and-services.md)

### UniFi System Logs：产品事件必须结构化并可展开

UniFi 将活动按严重度、时间、分类、类型和事件过滤，点击单条记录再查看诊断上下文；
原始设备日志和支持包属于更深层的高级诊断。

**借鉴：** 活动页展示面向用户的结构化事件，支持音响/协议/结果过滤，技术细节按条展开。

**避免：** 不把 `miair.log` 逐行搬进页面，也不在默认列表暴露 IP、URI 或堆栈。

来源：[UniFi System Logs](https://help.ui.com/hc/en-us/articles/33349041044119-UniFi-System-Logs-SIEM-Integration)

### Home Assistant Repairs：异常必须能解释下一步

Repairs dashboard 只收集需要用户介入的问题，并让每个问题给出修复入口或说明。

**借鉴：** “需留意”必须包含影响、仍可用能力和下一步，不能只显示黄色圆点。

来源：[Home Assistant Repairs](https://www.home-assistant.io/integrations/repairs/)

### 负面案例：Sonos 2024 首页重做

新首页把系统任务藏入手势和多层导航，说明视觉重构不能牺牲已有管理能力。CastFabric
继续保留显式的“音响”“活动”“连接配置”入口，不把管理动作藏到首页图形中。

来源：[Sonos 2024 redesign](https://investors.sonos.com/news-and-events/investor-news/latest-news/2024/Sonos-Unveils-Completely-Reimagined-Sonos-App-Bringing-Services-Content-and-System-Controls-to-One-Customizable-Home-Screen/default.aspx)

## 音响页比较方案

1. **房间插画网格：** 温暖直观，但七台以上会变成长卡片墙，状态比较效率低。
2. **传统数据表：** 容量和比较最好，但品牌感弱，移动端退化明显。
3. **设备注册表（选定）：** 等高音响行 + 三入口状态带 + 独立启停；详情用侧边抽屉。

选定方案在桌面保持紧凑的横向比较，在移动端自然变为设备卡，又不会把所有编辑字段
放进列表。

## 活动页比较方案

1. 原始日志查看器：信息多但不稳定、不安全，否决。
2. 泛化消息流：易读但缺少 session/target/protocol 关联，否决。
3. 结构化事件时间线（选定）：摘要、结果、音响、协议和时间常驻，技术细节展开。

## 连接配置比较方案

1. 独立设置首页：空间充分，但会新增第四个主导航并弱化“配置是辅助任务”的层级。
2. 一个长表单弹窗：实现简单，但发现、命名、网络和扩展混在一起。
3. 分区配置对话框（选定）：左侧分区导航，右侧只显示当前任务；移动端改为全屏抽屉。
