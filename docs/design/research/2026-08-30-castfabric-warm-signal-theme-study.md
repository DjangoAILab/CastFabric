# CastFabric 温暖明亮声路主题研究

## 产品身份

CastFabric 不是音乐库、播放器或内容社区，而是家庭局域网里的多协议音频接收与路由层。
界面需要同时具备音乐的温度和基础设施的可信度，不能照搬播放器的专辑封面、播放队列
或内容推荐结构。

## 参考产品

### 网易云音乐：中性画布上的情绪识别

网易云的核心产品叙事包含评论、社区、歌单与音乐人格。红色主要承担品牌记忆、情绪和
关键动作，大面积内容区仍保持中性。

**借鉴：** 用一个温暖、高识别的信号色表达“声音正在经过”。

**避免：** 复制网易红、黑胶唱片或评论社区语汇，让 CastFabric 被误认为播放器。

来源：[网易云音乐 App Store](https://apps.apple.com/cn/app/%E7%BD%91%E6%98%93%E4%BA%91%E9%9F%B3%E4%B9%90-%E6%95%B0%E4%BA%BF%E9%9F%B3%E4%B9%90%E7%95%85%E5%90%AC/id590338362)

### QQ 音乐：轻盈、年轻与可个性化

QQ 音乐强调内容发现、无损音质、自定义播放器和沉浸体验；其清新绿色和可换肤体系服务
于娱乐感与个性表达。

**借鉴：** 明亮留白、圆润触感和轻盈层次。

**避免：** 绿钻式品牌绿、皮肤商城感和装饰性播放动效。

来源：[QQ 音乐 App Store](https://apps.apple.com/cn/app/qq%E9%9F%B3%E4%B9%90-%E5%90%AC%E6%88%91%E6%83%B3%E5%90%AC/id414603431)

### Apple Music：界面退后，让内容提供色彩

Apple Music 的媒体对象可提供背景色和多级文字色，说明其沉浸色彩由专辑内容驱动；
Apple 的颜色原则也强调颜色应帮助沟通层级、交互与状态。

**借鉴：** 清楚的层级、中性基础色和克制控件。

**避免：** CastFabric 没有稳定专辑图来源，不能依赖自适应封面色维持首页视觉中心。

来源：

- [Apple Music Artwork](https://developer.apple.com/documentation/applemusicapi/artwork)
- [Apple HIG: Color](https://developer.apple.com/design/human-interface-guidelines/color)

### Sonos 重设计：视觉首页不能牺牲基本系统任务

Sonos 2024 年将内容和系统控制聚合到一个可定制首页，隐藏手势和基础能力缺失造成明显
反弹，后续又强化直白的 Home / System / Search 导航。

**CastFabric 必须避免：** 用漂亮舞台替代整体健康、可用音响和真实播放状态；也不能在
主题重做时顺手虚构尚未实现的管理功能。

来源：[Sonos 2024 redesign](https://investors.sonos.com/news-and-events/investor-news/latest-news/2024/Sonos-Unveils-Completely-Reimagined-Sonos-App-Bringing-Services-Content-and-System-Controls-to-One-Customizable-Home-Screen/default.aspx)

## 比较过的三个方向

1. **温暖明亮的声路系统（选定）：** 暖白、深墨、珊瑚信号色；兼顾家庭温度与状态可信。
2. **清透青绿家庭设备：** 更轻盈，但容易变成通用智能家居面板。
3. **内容驱动动态色：** 播放时沉浸感强，但元数据缺失会导致品牌和体验不稳定。

## 主题基线

```text
canvas        #F6F1E8  暖纸色背景
surface       #FFFCF7  主要表面
ink           #202421  主文字
ink-muted     #6F746E  次要文字
signal        #F35F45  品牌与活跃声路
signal-soft   #F7A087  信号层次
healthy       #2F8064  仅用于健康状态
warning       #B87922  仅用于注意状态
line          #D8D3CA  结构边界
```

品牌色不是错误红；错误状态应使用更深的危险色并配合文字。健康绿不参与品牌装饰。

## 首页图形语法

首页只允许一个主要图形：**当前声音会话**。

```text
发送设备  →  接收协议  →  CastFabric  →  输出音响
```

- 声带只沿真实方向移动，不能同时出现背景波纹、网格、路径粒子和音响扩散圈。
- 输入、CastFabric 和输出必须位于同一个视觉组件中，不能拆成互不相干的三个区域。
- 协议是路径节点，不是三个并列卖点；没有播放时不画虚假路径。
- 房间插画只作为输出身份的一部分，不再搭建完整家具场景。
- 多会话最多显示三条；其余聚合。空闲音响只显示数量。

## 首页验收门槛

1. 三秒内能说出是否正常、使用哪个协议、投到哪台音响。
2. 不依赖来源 App 或歌曲信息也能成立。
3. 完整元数据、仅设备名、仅协议三种状态使用同一结构自然降级。
4. 1440×900 单屏完成；移动端不缩小成拓扑图。
5. 中文、英文、空闲、播放、降级、错误和 reduced motion 分别验证。
