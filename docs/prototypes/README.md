# CastFabric 原型索引

| 原型 | 状态 | 说明 |
|---|---|---|
| [`castfabric-console.html`](castfabric-console.html) | Rejected v1 / 仅供对照 | 多音响数据模型正确，但视觉退化为通用卡片；slogan 被巨型状态文案抢占，缺少有解释力的全屋图形。不得直接转为生产 UI。 |
| [`castfabric-console-v2.html`](castfabric-console-v2.html) | Superseded v2 / 图形参考 | 房间插画与 Signal Path 方向有效，但三个导航仍是页内锚点，首页随音响数量纵向增长，英文模式不完整。不得直接转为生产 UI。 |
| [`castfabric-console-v3.html`](castfabric-console-v3.html) | Superseded v3 / 信息架构参考 | 验证了总览、音响、活动三个独立页面；视觉主题已由 v4 取代，不得直接转为生产 UI。 |
| [`castfabric-home-v4.html`](castfabric-home-v4.html) | Superseded v4 / 主题参考 | 暖色主题有效，但单会话大卡、中央 CF 节点与固定高度无法支持多端点和常见桌面视口。 |
| [`castfabric-home-v5.html`](castfabric-home-v5.html) | Review v5 / 仅首页 | 固定三轨交换台；多发送端、多音响保持等重，1280×720 起桌面无滚动，移动端转为纵向会话卡。 |
| [`castfabric-console-v6.html`](castfabric-console-v6.html) | Review v6 / 完整产品原型 | 保留已批准首页，补齐音响管理、详情编辑、结构化活动、事件详情和分区连接配置；所有动态字段通过机器数据契约检查。 |
| [`castfabric-server-playlists-review.html`](castfabric-server-playlists-review.html) | Rejected / 仅供对照 | 首轮 Playlist 原型按后端对象陈列信息，播放记录混入续播动作，且视觉偏离既有控制台；不得进入生产。 |
| [`castfabric-server-playlists-review-v2.html`](castfabric-server-playlists-review-v2.html) | Superseded / 内容工作台探索 | 以整理与播放内容为中心验证方向，已由 v3 的完整关键路径取代。完全使用静态演示数据。 |
| [`castfabric-server-playlists-product-flow-v3.html`](castfabric-server-playlists-product-flow-v3.html) | Accepted 2026-09-05 / 功能线框图 | 已确认 Playlist 编辑、资源搜索与元数据、只读播放记录和统一播放弹窗。它是生产功能边界，不是可直接复制的最终视觉稿。 |
| [`castfabric-landing-v1.html`](castfabric-landing-v1.html) | Review v1 / GitHub Pages | 面向家庭服务器与自托管用户的 Warm Signal Editorial 官网原型；与生产控制台和 API 完全隔离。 |

既有控制台以 v6 为视觉与全局信息架构参考；服务端 Playlist 关键路径以获批 v3 为功能参考。新增字段或动作必须先登记到
[控制台字段契约](../design/contracts/castfabric-console-fields.json)，并通过
[`validate_console_prototype.py`](validate_console_prototype.py)；交互、国际化和响应式回归使用
[`verify_console_prototype.cjs`](verify_console_prototype.cjs)。
