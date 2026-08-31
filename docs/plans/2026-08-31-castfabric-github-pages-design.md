# CastFabric GitHub Pages Landing Page 设计

## 状态

视觉方向已确认，进入独立原型评审。本文授权修改 `docs/prototypes/` 中的静态原型，不授权
启用 GitHub Pages、修改生产控制台或发布官网。

## 目标

为家庭服务器和自托管用户建立一个中英文开源项目官网。访客应在十秒内理解：

1. CastFabric 接收 DLNA、AirPlay 和妙播，并输出到标准 DLNA MediaRenderer；
2. 核心链路运行在用户自己的 Home Server，不依赖云端或小米账号；旧小米音箱另有
   默认关闭、需要账号的 MiNA 兼容输出；
3. 每台音响拥有独立接收入口，多台音响可以同时存在；
4. 最快的开始方式是 Docker；完整代码、Release 和架构在 GitHub。

锁定文案：**不挑协议，投了就播。**  
英文自然表达：**Cast freely. It just plays.**

## 视觉概念：Warm Signal Editorial

官网延续生产控制台的暖白、深墨、珊瑚和苔绿，但拥有更大的留白、更强的编辑式标题和更
慢的叙事节奏。视觉记忆点不是 `CF` 标志或音频频谱，而是一个清晰的本地声路交换台：

```text
手机 / 电脑 → DLNA · AirPlay · MiPlay → CastFabric → 标准 DLNA 音响
                                                   └→ 可选 Xiaomi MiNA 兼容输出
```

交换台内输入、协议和输出保持视觉平衡。CastFabric 只是路径中的路由层，不使用高权重
中央圆球。动画粒子只能沿有效方向移动；空闲路径保持静止；Reduced Motion 完全关闭循环。

## 页面结构

### 1. Header

- 品牌标志和 CastFabric；
- 锚点：能力、原理、部署；
- 中英文切换；
- GitHub 链接。

移动端收敛为品牌、语言和 GitHub，不增加汉堡菜单。

### 2. Hero

左侧：slogan、定位说明、局域网/每音响独立/双架构三个短标签、主次 CTA 和公开 GHCR
镜像入口。
右侧：能力矩阵明确分开“发送设备与接收协议”“每音响独立 Receiver Suite”“当前输出
协议与设备”。标准 DLNA 是本地核心输出；Xiaomi MiNA 是已实现但默认关闭、需要账号的
旧 MiAir 兼容输出。未来能力只标注 `PlaybackTarget` 扩展边界，不列出未实现协议。

### 3. Proof strip

四项可验证事实：三种已实现接收协议、标准 DLNA 核心输出、Xiaomi MiNA 可选输出、
`PlaybackTarget` 扩展边界。数字和状态只使用仓库可以证明的事实。

### 4. Product proof

使用真实 `console-overview.png`，旁边解释首页、音响管理和活动诊断。移动端补充真实
`console-mobile.png`，不重新绘制假的 Dashboard。

### 5. How it works

三步说明：发现标准 DMR → 为每台音响发布独立入口 → 验证实体音响真正拉流。协议细节可
读但不压过结果。

### 6. Docker deployment

展示可直接执行的 Linux `docker run`，从公开 GHCR 拉取 amd64/arm64 镜像，使用 host
network 并把配置绑定到宿主机目录。命令支持复制，链接到 README 的 Compose、多网卡和
完整网络说明。Hero 不再展示缺少 Compose 文件前提的 `docker compose up -d`。

### 7. Honest boundary

标题直接写“两条声路，两种延迟”。原生 DLNA 在当前测试音箱通常低于一秒；AirPlay /
MiPlay 实时桥接约四秒，不适合要求音画同步的视频。链接到完整延迟证据。

### 8. Open-source footer

MIT、GitHub、Release、架构、中文/English。没有 newsletter、登录、Cookie banner 或分析
脚本。

## 设计系统

```text
canvas          #F6F1E8
surface         #FFFDF8
ink             #202421
muted           #6F746E
signal          #F35F45
signal-deep     #B94634
signal-soft     #FDE3D9
healthy         #2F8064
line            #D8D3CA
display         Baskerville / Songti SC / Noto Serif CJK SC
body            Avenir Next / PingFang SC / Microsoft YaHei
radius          12 / 18 / 28 / pill
shadow          warm, low-contrast, never neon
```

字体只使用设备本地字体栈，避免中国网络下外部字体阻塞。

## 国际化与真实性

- 中文默认，语言切换即时生效并保存到 `localStorage`；原型允许重置。
- English 模式不残留可见中文；协议、CastFabric、Docker 和设备原始名称不翻译。
- 不推断来源 App、歌曲、在线人数或安装量。
- 官网示意图使用 `Route preview / 协议路径示意`，避免被理解为实时数据。
- 外部链接均指向 `wangerzi/CastFabric` 的真实页面。

## 响应式与无障碍

- 桌面 Hero 在 1440×900 内完整表达主要信息，不要求首屏看完整个长页。
- 右侧交换台在移动端变成三条纵向路径，不缩成难以阅读的小拓扑。
- 交互目标至少 44×44 px；键盘可操作语言、复制命令和所有链接。
- `:focus-visible` 明确；颜色不是唯一状态信号；正文满足 WCAG AA。
- `prefers-reduced-motion: reduce` 关闭粒子、漂浮和滚动行为。

## 原型与验证范围

原型文件：`docs/prototypes/castfabric-landing-v1.html`，完全静态且不连接生产 API。

必须验证：

1. 1440×900 Hero 无横向溢出，主 CTA、GHCR 和完整能力矩阵可见；
2. 390×844 无横向溢出，导航和能力矩阵自然纵向排列；
3. 中英文模式没有混合可见文案；
4. 复制按钮成功、失败降级与键盘路径可用；
5. Reduced Motion 下不存在循环动画；
6. 全页真实链接、图片和锚点存在；
7. 浏览器控制台没有错误。

## 正式实现边界

用户接受原型后才进入正式实现。届时：

- 建立独立静态站点源目录和官方 GitHub Pages Actions；
- 生成与品牌一致的 Open Graph 图；
- 替换根目录旧 MiAir `preview.png`；
- 更新已过期的 P5 路线状态；
- 构建、链接检查、Lighthouse/可访问性检查通过后再启用 Pages。
