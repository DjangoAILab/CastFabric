# 顶栏与弹窗小范围修订研究

日期：2026-09-06。状态：用户已认可推荐 A 方向并授权实现（“看起来可以，按照这个方向实现吧”）。

## 范围与约束

修复新建播放列表的位置，统一 README/GitHub 与控制台的项目标志，补充开源入口，整理语言与连接配置。保留已认可的信息架构、暖色视觉及「不挑协议，投了就播」，不增加内容管理层级，不把 GitHub 的 Octocat 当作 CastFabric 的项目标志。

## 参考与交互观察

以下是官方文档的交互观察，不将宣传页当成可用性测试。

1. [Audiobookshelf 播放列表](https://audiobookshelf.org/docs/documentation/libraries/common-content/playlists/)（直接类别）：播放列表围绕内容组织、排序与播放；借用内容区主操作和系统工具分层。不要把库权限、分享等复杂能力带进本次修订。与本项目现有内容工作台直接相关。
2. [GitHub Primer Button](https://primer.style/product/components/button/) 与 [Tooltip](https://primer.style/brand/components/Tooltip/)（相邻开发工具）：可见文字降低图标猜测成本，纯图标需可访问名称与提示。借用轻量次级按钮及一致命中区域；避免用三个互不一致的胶囊按钮争夺注意力。语言显示当前值，而不是只显示切换后的语言。
3. [IBM Carbon Modal](https://carbondesignsystem.com/components/modal/usage/)（相邻企业控制台）：长内容只滚动正文，头尾固定；表单首字段获得焦点，焦点留在弹窗内；无效提交保留弹窗并给出行内错误。借用这些行为，不照搬其全宽按钮与品牌样式。对本次弹窗错位及小屏可达性有直接帮助。
4. 负面案例：[Sonos 2024 应用更新致歉](https://en.community.sonos.com/product-updates/update-on-the-sonos-app-from-patrick-spence-6900501)、[官方更新说明](https://www.sonos.com/en/blog/update-on-the-sonos-app)。发布新视觉不代表保住用户依赖的既有工作流。这里的规避方式是验证创建、关闭、语言切换、连接入口及窄屏操作，而不是只验截图。更详细的同类研究见 2026-09-04 的媒体播放列表研究。

## 两种方向（已向用户说明，尚未选定）

- **A，推荐：可读工具组。** 桌面展示「开源项目」「简体中文 ▾」「连接配置」及 SVG；小屏独立一行，保留文字。可发现性高，代价是比纯图标多占横向空间。
- **B：极简图标组。** 三个同尺寸图标控件，保留可访问标签与提示；小屏仍可用。视觉安静，但语言当前值和连接配置更依赖学习，不推荐作为默认。

两者均复用 `docs/assets/castfabric-mark.svg`，而非生成新的近似品牌图。动作图标使用 SVG，避免栅格图在小尺寸下模糊；GitHub 标记取自 MIT 授权的 Primer Octicons。

## 原型与验收

原型：`docs/prototypes/castfabric-header-dialog-review-2026-09-06.html`，仅本地模拟，无生产 API。

验收覆盖：桌面/移动端、中英、空/加载/服务降级/错误；对话框始终处于视口安全范围，正文可滚动且底部操作可见；键盘焦点、Escape、关闭后焦点恢复；更改语言不破坏 SVG；工具入口不因屏幕变窄而消失。原型中的工具区不会被带进生产 UI。

已定位生产根因：`.overlay.open` 仅 `display:block`，`.content-dialog` 没有居中布局；不能直接更改所有 overlay，以免破坏已有右侧抽屉。

后续只有在本原型获批后才修改生产文件；完成回归、内容检查、合并、推送、发布及 Home Server 静默分层验收后交付。当前不需要重新验证声学输出。

## 原型浏览器验证记录

本地 Chrome，1440×900、390×844、390×500：

- 桌面弹窗 `x=420, y≈175, width=600`，水平/垂直居中；390×844 时四边均保留安全距离。
- 390×500 时弹窗位于 `y=16..484`，正文内部滚动，底部操作始终可达；无横向溢出。
- 空名称提交保持弹窗并显示行内错误；首次焦点在名称，最后控件 Tab 回到弹窗首控件；Escape 关闭后焦点回到新建按钮。
- 中英语言切换后 SVG 完整保留；A/B 可切换；正常、空、加载、服务降级、错误状态均无桌面横向溢出；移动中英顶栏入口均可见。
- 页面无 JavaScript 错误。该结果仅适用于独立原型，不等于生产修复完成。

截图：[桌面 A](2026-09-06-header-dialog/desktop-a.png)、[桌面弹窗](2026-09-06-header-dialog/dialog-desktop.png)、[移动 A](2026-09-06-header-dialog/mobile-a.png)、[移动弹窗](2026-09-06-header-dialog/dialog-mobile.png)。
