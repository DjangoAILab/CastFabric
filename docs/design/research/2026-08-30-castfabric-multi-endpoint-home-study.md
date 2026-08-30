# CastFabric 多端点单屏首页研究

## 本轮要修正的问题

v4 把一条会话放大成了整个首页：发送端只有一张卡、输出音响是一张大插画，中央还有
一个比真实信息更醒目的 `CF` 圆形。这个构图在单源、单输出时勉强成立，但无法回答
“同时有多个发送端和多台音响怎么办”，也无法在常见的 1366×768 桌面视口内保持无滚动。

首页需要表达的是一个有上限的实时系统摘要，不是把全部设备铺在画布上：

- 同时展示最多三条活跃会话；
- 每条会话明确关联一个发送端、协议和输出音响；
- 多于三条的会话与空闲音响只显示数量，完整集合进入音响页；
- 单条会话不能因空位而膨胀，多条会话也不能推动页面增长。

## 参考与判断

### Sonos System view：输出集合需要稳定的同级表达

Sonos 把系统中的输出显示为 groups、home theaters、stereo pairs 和 portable products，
System view 同时呈现全部可用输出与活跃内容。它说明多房间系统的设备应该是同级、稳定
尺寸的集合，而不是让当前播放音响独占大半屏幕。

**借鉴：** 输出端采用等高紧凑行；播放、就绪和异常通过状态与文字区分。

**避免：** CastFabric 不是内容控制器，不照搬播放控制、音量和分组操作到首页。

来源：[Sonos App guide — System controls](https://www.sonos.com/en-us/guides/sonosapp)

### Roon Signal Path：路径必须诚实，但不应冒充系统总览

Roon 的 Signal Path 专门解释音频经过哪些处理环节，并明确承认无法识别交给硬件之后的
所有步骤。它适合解释单条会话，却不是多房间首页。

**借鉴：** 一条轨道只表达一条真实会话；协议、状态和目标必须在同一行内可读。

**避免：** 不把每个内部处理步骤都画成节点，不用一个巨型品牌节点抢走端点信息。

来源：[Roon Signal Path](https://help.roonlabs.com/portal/en/kb/articles/signal-path)

### Home Assistant Sections：容量先于自适应堆叠

Home Assistant 的 Sections view 允许预设最大列数，并按 section 组织同类信息；其 Home
dashboard 是其他区域和专题页的入口。这个模型说明总览应有明确容量，完整对象下沉到
各自页面，而不是依赖 Masonry 自动堆满。

**借鉴：** 桌面端固定列与固定行容量；首页只保留关键状态，音响页管理完整设备集合。

**避免：** 不开放自由拖拽和任意卡片布局，以免失去稳定的信息优先级。

来源：

- [Home Assistant Sections](https://www.home-assistant.io/dashboards/sections/)
- [Home Assistant dashboard views](https://www.home-assistant.io/dashboards/views/)

### 负面案例：Sonos 2024 首页重做

Sonos 曾将内容和系统控制聚合进强调可定制的新首页，隐藏基础系统任务后引发明显反弹。
CastFabric 不能因为主视觉更漂亮，就让用户失去“哪个来源正在投到哪台音响”的直观答案。

来源：[Sonos 2024 redesign](https://investors.sonos.com/news-and-events/investor-news/latest-news/2024/Sonos-Unveils-Completely-Reimagined-Sonos-App-Bringing-Services-Content-and-System-Controls-to-One-Customizable-Home-Screen/default.aspx)

## 比较过的三个构图

### A. 放射式中心枢纽

来源和音响环绕 CastFabric 中心分布。单会话有记忆点，但设备增加时交叉线快速增长，
品牌节点会天然成为最大视觉重量。**否决。**

### B. 房间矩阵 + 活跃描边

以房间卡片为主，当前播放仅在卡片上标记。扩展设备容易，但发送来源和协议关系变弱，
更像音响管理页。**保留给音响页，不用于首页。**

### C. 固定三轨交换台（选定）

每条活跃会话占一条横向轨道：左侧发送端、中央协议和路由状态、右侧输出音响。左右端点
使用相同尺寸与层级，CastFabric 仅作为窄的路由带和系统边界。最多展示三轨，其余聚合。

这个方案既能表达因果关系，又能在一条或多条会话时保持相同高度和视觉平衡。

## v5 桌面容量规则

- 页面在 `100dvh` 内布局，桌面 `body` 禁止滚动；最低验收视口为 1280×720。
- 页头、品牌语句、摘要和交换台都使用弹性高度；不再设置会把内容撑出视口的固定
  `min-height`。
- 交换台固定三轨。演示数据包含三条不同状态，验证多源、多协议、多输出。
- 左右端点列同宽；中央路由列只占必要宽度，不出现 `CF` 大字或圆形徽章。
- 单轨播放时，其他轨道保留为空闲容量或系统摘要，不放大会话卡。
- 超过三条显示“另有 N 条活跃会话”；超过可见音响显示总数，不增加卡片。
- 移动端解除高度限制，三轨转为纵向会话卡并允许页面滚动。

## 动效规则

- 播放轨使用一颗低频移动的信号点和短声带，不使用全屏波纹、呼吸圆环或装饰粒子。
- 暂停轨冻结；异常轨使用静态虚线；空闲时不伪造流动。
- 首次进入只做一次有顺序的轨道淡入；`prefers-reduced-motion` 下全部关闭。

