# CastFabric AI 接入页实现契约

## UI Vocabulary

- `primary navigation item`：现有主导航新增“AI 接入 / AI Access”。
- `service status card`：只读展示内嵌 MCP 状态、同源 endpoint 与“单端口”事实。
- `tablist / tab / tabpanel`：Codex、Claude Code、通用 MCP 三种客户端接入命令。
- `read-only code block`：展示由 `location.origin + "/mcp"` 生成的命令。
- `copy button`：复制命令或静默验证提示词。
- `polite live region`：播报复制成功或失败，不移动键盘焦点。
- `capability strip`：管理、文件播放、实时 PCM 三组已实现能力。
- `Skill install card`：说明本地文件、FFmpeg 与客户端播放列表由 Skill 处理。

映射为原生 HTML `nav/button/section/code`，tab 使用 `role=tablist/tab/tabpanel`、
`aria-selected` 与 roving `tabindex`。不引入框架或组件库。

## Style Brief 与 tokens

沿用控制台已确认的温暖、明亮、编辑式视觉：`--canvas #f6f1e8`、
`--surface #fffdf9`、`--ink #202421`、珊瑚信号色 `--signal #f35f45`、健康绿
`--healthy #2f8064`。AI 页面不使用紫色渐变或聊天机器人图标。主卡圆角 24px，内部卡
16px；间距使用 8/12/16/24；代码区使用等宽字体、深墨绿色底与暖白文字。动效仅有
240ms 淡入和复制状态反馈，并遵守 `prefers-reduced-motion`。

## State + Interaction Matrix

| 状态 | 表现 | 操作 |
|---|---|---|
| loading | 状态显示“正在确认 MCP”；同源 endpoint 仍可预览 | 等待 `/api/v1/system` |
| ready | 绿色状态、真实同源 `/mcp`、命令可复制 | tab、复制命令、复制提示词 |
| unavailable | 警告色；非 HTTP 页面不生成 endpoint 或命令 | HTTP 同源地址仍可手动检查 |
| copy success | Toast 与 live region 显示“已复制 / Copied” | 焦点留在原按钮 |
| copy error | 代码保持可选择，Toast 给出手动复制建议 | 用户可手动复制 |

鼠标、触屏均使用不小于 40px 的按钮命中区。Tab 支持点击、左右方向键、Home/End，
并使用 roving `tabindex`。复制后焦点留在原按钮。桌面使用 5/7 两栏并在一个 viewport 内优先展示；小于 980px
重排为单列并允许页面纵向滚动；代码块只横向滚动，不撑破容器。中英文必须完整切换。

## 失败模式

- `location.origin` 为 `file://`：显示不可用，不生成安装命令。
- Clipboard API 被拒绝：显示失败状态，代码文本仍可选择。
- 长 hostname/IPv6：endpoint 与代码区横向滚动或断行，不覆盖按钮。
- MCP 与 Web 分端口：契约测试禁止任何额外 MCP 端口字段或硬编码开发 IP。
- 安装后误出声：验证提示词明确只调用 `list_outputs`，不得调用播放工具。

## DesignQM evidence

- **D1 视觉体系**：完全复用控制台既有 canvas/surface/ink/signal/healthy tokens；代码区是唯一深色功能面，未引入紫色 AI 套路。证据：`ai-access-desktop-zh.png`、`ai-access-desktop-en.png`。
- **D2 布局构图**：桌面为 `.82fr / 1.18fr` 两栏，标题、端点、能力与安装步骤形成明确层级；1440×900 下两张主卡底边均为 892px，保持在 900px viewport 内。
- **D3 适配性**：1440px 与 390px 实测均无横向溢出；390px 下改为单列，三个客户端 tab 的 `clientWidth` 与 `scrollWidth` 均为 330px。证据：`ai-access-mobile-en.png`。
- **D4 交互完整性**：实现 loading/ready/unavailable、Clipboard API 失败回退、live region、40px 命中区、roving tabindex、方向键与 Home/End；样式表保留 `prefers-reduced-motion`，浏览器控制台无错误。
- **D5 文案规范**：中英文切换实测，英文 AI 页面可见文本 CJK 计数为 0；验证提示词明确只调用 `list_outputs`、不得播放声音；可信局域网边界明确展示。
- **D6 代码质量**：AI 运行时逻辑集中在 `renderAI/aiEndpoint/aiCommand/copyAIText`；`tests/test_console_contract.py` 以 7 个契约测试约束单端口、能力真实性、双语、键盘和响应式；`node --check` 与 `git diff --check` 通过。
