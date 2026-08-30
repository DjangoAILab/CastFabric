# CastFabric 单屏总览与三页面导航研究

## 问题

Whole-home Sound Map v2 解决了“缺少图形”和“多音响独立”的表达问题，但仍把完整音响
集合、当前播放和近期活动放在同一长页面。音响增加后，户型式画布会持续变长或变密，
无法保证 PC 端单屏完成状态浏览；导航虽然出现了总览、音响、活动，实际仍是页内锚点。

## 参考与结论

### Apple Home：总览显示摘要，不复制完整设备库

来源：

- [Apple Home 产品页](https://www.apple.com/home-app/)
- [iPhone Home overview](https://support.apple.com/en-al/guide/iphone/iph22d98bbca/ios)

Home 页顶部使用 Lights、Security、Climate 等类别摘要；完整设备仍按房间和类别进入。
摄像头也只显示有限数量，其余通过横向浏览访问。

**CastFabric 借鉴：** 首页只展示活跃会话、需要处理的异常和聚合数量；全部空闲音响
不逐台占据首屏。

### Home Assistant：摘要、收藏与区域分层

来源：

- [Home Assistant 2026.1 Home dashboard](https://www.home-assistant.io/blog/2026/01/07/release-20261/)
- [Home Assistant Dashboard](https://www.home-assistant.io/dashboards/)

新版 Home dashboard 把 summary cards 放在顶部，其后才是收藏和区域。首页回答“现在
发生什么”，区域页承担设备组织。

**CastFabric 借鉴：** 首页保持强默认结构，不开放瀑布流自定义；音响与活动分别拥有
稳定入口。

### BluOS：Players 是明确的设备管理任务

来源：

- [BluOS Players tab](https://support.bluos.net/hc/en-us/articles/17720275122327-Navigating-the-Players-tab-screen-in-BluOS-4-0)
- [BluOS Player grouping](https://support1.bluesound.com/hc/en-us/articles/14553451784855-Grouping-Bluesound-Players)

BluOS 把播放器列表、分组、音量和设置集中在 Players tab；播放内容和设备管理没有被
强塞在同一首页。

**CastFabric 借鉴：** 音响页承载启停、别名、入口健康、实体 DLNA、最后出现时间和
详情入口；活动页不出现设备管理开关。

### IBM Carbon overview：聚合优先，集合设容量上限

来源：[IBM Storage Insights Overview dashboard](https://www.ibm.com/docs/en/storage-insights?topic=overview-dashboard-carbon)

Overview 显示系统级聚合；资源集合默认只显示五项，更多内容通过展开或独立页面访问，
异常按严重程度优先。

**CastFabric 借鉴：** 实时声场最多展示三条活跃会话和一个异常摘要；其余聚合为数量，
不通过缩小节点强塞进画面。

### Endel：环境动效必须传递可读变化

来源：

- [Endel 产品页](https://endel.io/)
- [Endel Visualization 指南](https://endel.zendesk.com/hc/en-us/articles/360014628319-User-Guide)

Endel 的生成式视觉随声音状态变化；用户可通过流动方向快速判断能量上升或下降。

**CastFabric 借鉴：** 首页声场采用低频流线。方向表示输入到输出，速度表示播放/暂停，
密度只反映活跃会话数量；没有播放时停止定向流动，仅保留呼吸。

### Progressive disclosure：重要状态常驻，细节按需出现

来源：[Microsoft Progressive Disclosure](https://learn.microsoft.com/en-us/windows/win32/uxguide/ctrl-progressive-disclosure-controls)

重要安全状态始终可见，附加信息和操作按需展开。

**CastFabric 借鉴：** 首页常驻整体健康和当前会话；Signal Path、端口、设备地址和协议
诊断进入详情。

## 决策

采用三个真正独立的产品页面，而不是页内锚点：

1. **总览 `/`：** 单屏实时声场；低交互，只显示整体健康、最多三条活跃会话、异常
   摘要和音响聚合数量。
2. **音响 `/speakers`：** 完整输出设备管理；列表或固定网格可滚动，承担所有启停和
   配置动作。
3. **活动 `/activity`：** 独立事件时间线；只承担查看、筛选和诊断，不出现音响开关。

原型使用同一 HTML 内的三 page state 模拟路由，正式实现阶段再决定 history routing
或 hash routing。

## 首页固定容量规则

- 0 条活跃会话：中央声场缓慢呼吸，显示“已就绪 N 台”。
- 1 条活跃会话：突出一条完整输入—音响路径。
- 2–3 条活跃会话：并列三条独立流线，避免节点重叠。
- 超过 3 条：第三条位置显示“另有 N 路正在播放”，点击进入音响页筛选活跃状态。
- 异常只显示最高严重度和数量；详细异常进入音响或活动页。
- 页面主体必须在 1440×900 的浏览器视口内完整显示，默认不产生纵向滚动。

## 动效约束

- 播放：粒子沿真实输入—输出方向移动，周期 2.4–4 秒。
- 暂停：粒子停止，路径保留。
- 空闲：取消方向性，只保留 6–8 秒的低频呼吸。
- 故障：不闪烁、不抖动，使用静态断点和解释文案。
- `prefers-reduced-motion`：移除循环运动，保留状态颜色和线型。
- 动效是状态的冗余表达，任何结论都不能只依赖动画或颜色。

## 国际化完整性门槛

- 所有用户可见字符串来自中英字典，包括 aria-label、按钮、状态、房间默认名和原型
  演示控件；品牌、协议、IP、采样率等不翻译。
- 英文模式下自动扫描可见文本，除用户设备原始名称外不得出现中文字符。
- 中文模式和英文模式分别在桌面与移动视口截图验收。

