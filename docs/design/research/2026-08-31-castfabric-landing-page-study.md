# CastFabric 自托管 Landing Page 案例研究

日期：2026-08-31  
范围：面向家庭服务器、自托管和 homelab 用户的开源项目官网；研究信息层级、首屏承诺、
能力证明、安装入口和动效语法，不复制其他产品的品牌视觉。

## 研究问题

1. 如何让第一次访问的人在十秒内理解 CastFabric 不是播放器？
2. 如何同时服务“先看效果”和“马上部署”的自托管用户？
3. 如何用动效解释多协议、多音响，而不是制造装饰性拓扑？
4. README 已经很完整时，Landing Page 还应该承担什么？

## 1. Home Assistant：先讲本地价值，再给生态证明

来源：[Home Assistant](https://www.home-assistant.io/)

观察：

- 首屏先用一句面向人的承诺说明产品，再提供 Get started、Demo 和 integrations 等不同深度入口。
- “Local control and privacy”不是藏在技术规格中，而是产品身份的一部分。
- 实际产品界面、集成数量、社区和发布记录逐层提供可信度，用户不必先读完整文档。

CastFabric 应借鉴：

- 首屏先说“不挑协议，投了就播”，再解释本地、多协议和标准 DLNA 输出。
- 第一行动面向已经理解自托管的人，直接提供 Docker 部署；第二行动进入 GitHub。
- 用真实控制台截图和已验证协议代替抽象承诺。

CastFabric 应避免：

- 不能借用大型生态的数量叙事。CastFabric 当前强项是声路清晰、无需云账号和可验证输出。

## 2. Music Assistant：把来源、处理与播放器说清楚

来源：

- [Music Assistant](https://www.music-assistant.io/)
- [Installation](https://www.music-assistant.io/installation/)

观察：

- 产品直接区分 music sources、providers 和 players，让复杂媒体体系可以被逐层理解。
- 安装与网络约束是主要导航，不把自托管用户必须知道的信息埋在营销文案后面。
- 文档用真实术语，但每个术语都有具体职责。

CastFabric 应借鉴：

- 用“发送设备 → 接收协议 → CastFabric → 输出音响”解释边界。
- 把 Docker、host network、控制台地址做成一条连续的三步路径。
- 明确 CastFabric 不管理音乐库、不提供内容，也不替代音响原生 DLNA。

CastFabric 应避免：

- 不使用专辑、歌曲或内容服务作为主视觉；CastFabric 无法稳定获得这些元数据，也不是媒体库。

## 3. Tailscale：把基础设施复杂性转换成简单结果

来源：

- [Tailscale](https://tailscale.com/)
- [Tailscale company narrative](https://tailscale.com/company)

观察：

- 复杂网络能力被表达成“设备自然连在一起”的结果，而不是要求访客先理解底层协议。
- 动态连接图只有在说明设备关系时才有效；行动入口与结果承诺始终比拓扑更重要。
- 开发者入口、文档和产品入口分层明确。

CastFabric 应借鉴：

- 把三种协议画成路径节点，不做三张孤立功能卡。
- 多台音响作为独立输出同时存在；交换台不是中央英雄图标。
- 技术细节在声路解释和架构段落展开，首屏保留一句人话和一条可复制命令。

CastFabric 应避免：

- 不复制企业客户墙、商业套餐比较或大规模网络叙事，自托管家庭音频才是当前范围。

## 4. Sonos 2024：漂亮首页不能隐藏系统任务

来源：[Sonos redesign announcement](https://investors.sonos.com/news-and-events/investor-news/latest-news/2024/Sonos-Unveils-Completely-Reimagined-Sonos-App-Bringing-Services-Content-and-System-Controls-to-One-Customizable-Home-Screen/default.aspx)

失败教训：Sonos 的重设计强调统一、可定制和视觉化首页，但基础控制、可发现路径与稳定性
问题引发了明显反弹。对于系统产品，动效、内容和个性化不能替代“现在能不能用”“下一步
做什么”和“出了问题去哪里看”。

CastFabric 的约束：

- Landing Page 的动画只解释架构，不模拟不存在的实时系统状态。
- Docker 安装、支持协议、输出要求和延迟边界必须可见。
- 官网不替代控制台；“打开控制台”不作为公网 CTA，因为自托管实例没有统一公开地址。

## 5. GitHub Pages 官方发布路径

来源：

- [Configuring a publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

结论：正式实现使用 GitHub 官方 `configure-pages`、`upload-pages-artifact` 与
`deploy-pages` Actions，不维护 `gh-pages` 分支，也不把构建产物提交到 `main`。网站保持
纯静态、无追踪脚本、无服务端数据依赖。

## 比较过的视觉方向

### A. Warm Signal Editorial（选定）

暖纸画布、深墨文字、珊瑚信号；首屏是有方向的声路交换台。与控制台一致，又能承载更
宽松的编辑式排版。最适合“家庭温度 + 基础设施可信度”。

### B. Technical Signal Map

网格、端口、协议与拓扑更突出，工程感强，但容易退化成技术文档首页，并把自托管新用户
挡在术语之外。

### C. Music Atmosphere

使用唱片、频谱与沉浸渐变，第一眼更像音乐产品，但会误导用户期待播放队列、专辑封面和
内容推荐，与 CastFabric 的真实数据和产品定位冲突。

## 设计结论

- 目标访客：拥有 NAS、迷你主机、树莓派或其他 Home Server 的自托管用户。
- 首要动作：复制 Docker 部署命令并进入快速部署段落。
- 第二动作：查看 GitHub、Release 和技术文档。
- 唯一首屏主图：协议不同但声音抵达多台音响的本地声路。
- 可信度来源：真实控制台截图、三协议、无需小米账号、双架构镜像、明确延迟边界。
- 不使用第三方追踪、外部字体或虚构的实时设备数据。
