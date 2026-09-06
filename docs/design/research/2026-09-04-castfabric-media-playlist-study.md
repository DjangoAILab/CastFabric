# CastFabric 媒体资源、播放列表与播放记录研究

研究日期：2026-09-04

## 研究问题

CastFabric 已经能够通过 MCP 播放一次性 URL、Agent 本地文件与实时 PCM，但客户端脚本中的
顺序列表无法在 Agent 退出后继续，也没有稳定媒体对象、持久播放实例或可查询进度。本次
研究用于判断：媒体资源、播放列表、当前队列、播放进度和历史记录应该如何分层，以及这些
能力是否需要进入现有控制台。

## Audiobookshelf：内容组织、用户进度与监听 Session 分离

来源（访问于 2026-09-04）：

- [Collections and Playlists](https://audiobookshelf.org/docs/documentation/libraries/common-content/playlists/)
- [Listening Sessions](https://audiobookshelf.org/docs/documentation/server-management/listening-sessions/)
- [Introduction](https://audiobookshelf.org/docs/documentation/introduction/)

交互观察：

- Collection/Playlist 是可排序的内容集合，顶部提供 Play All；播放列表出现后才进入导航，
  避免空产品预先制造复杂入口。
- 收听进度按用户维护，不直接成为 Playlist 自身的共享字段。
- Listening Sessions 有独立表格，可查看当前与历史 Session，并按用户过滤；详情包含发生
  播放的设备，说明内容组织、续播状态和诊断历史是三个相关但不同的对象。

CastFabric 应借鉴：Playlist 只定义有序内容；一次投放生成独立 PlaybackRun，并关联输出、
item、asset 和底层 media session。Playlist 详情可以聚合进度，但不能只保存一个会被并发
音箱覆盖的全局位置。

CastFabric 应避免：不复制用户、RSS、Podcast、统计报表和书籍元数据系统。音乐与有声书
先使用同一 Playlist 模型，只通过默认顺序、循环和续播参数区分。

## Navidrome：服务器保存资源，客户端生态消费稳定 API

来源（访问于 2026-09-04）：

- [Navidrome Overview](https://www.navidrome.org/docs/overview/)
- [Configuration Options](https://www.navidrome.org/docs/usage/configuration/options/)

交互与能力观察：

- Navidrome 把服务器媒体库作为稳定事实源，同时允许 Web UI 与 Subsonic 客户端消费；播放
  列表、书签和保存队列建立在持久资源之上。
- `Get/Save Play Queue` 明确支持换设备后继续，但这是保存的队列状态，不是媒体文件自身属性。
- `.m3u` 导入、标签浏览、多媒体库和智能列表展示了成熟媒体服务器的扩张方向。

CastFabric 应借鉴：上传完成后返回稳定 `asset_id`；PlaylistItem 引用 asset，而不是重复
上传；数据库查询服务与 MCP/HTTP 传输层解耦，将来可增加客户端而无需重写领域关系。

CastFabric 应避免：首版不扫描任意音乐目录、不构建艺术家/专辑/标签索引、不做智能列表、
转码策略、歌词、封面抓取或多用户权限。否则产品会从音频路由器直接膨胀成完整音乐服务器。

## Sonos：Playlist 与每个输出的 Queue 是不同对象

来源（访问于 2026-09-04）：

- [Using the queue in the Sonos app](https://support.sonos.com/en-us/article/using-the-queue-in-the-sonos-app)

交互观察：

- 每个 room 拥有独立 queue；同一媒体或 playlist 可以在不同房间形成不同的运行队列。
- queue 是动态 playlist：开始播放会先进入当前 room 的 queue，再支持 shuffle、repeat、移除
  和重排。
- queue 位于 Now Playing 上下文，而不是被误认为内容库里的 Playlist 定义。

CastFabric 应借鉴：Playlist 不绑定音箱；`start_playlist` 创建绑定 `target_id` 的
PlaybackRun，并保存本次解析后的随机顺序。每个输出最多一个活动 run，但同一 Playlist 可
同时拥有多个 run。

CastFabric 应避免：首版不引入临时“接下来播放”编辑、跨音箱分组和毫秒级同步。稳定 Playlist
管理与运行实例已经足够覆盖 Agent 播放音乐和有声书。

## Spotify 与 Apple Music：定义版本和正在播放的 Queue 分离

来源（访问于 2026-09-04）：

- [Spotify Playlists](https://developer.spotify.com/documentation/web-api/concepts/playlists)
- [Spotify Play Queue](https://support.spotify.com/no-en/article/play-queue/)
- [Apple Music Queue](https://support.apple.com/en-ca/guide/iphone/ipha4521ef7d/ios)

交互与契约观察：

- Spotify 每次增删或重排 Playlist 都生成新的 `snapshot_id`，修改接口可以携带旧 snapshot
  处理并发变更；这说明 Playlist 当前定义本身需要版本身份。
- Spotify 和 Apple Music 都把“正在播放/接下来播放”的 Queue 放在 Now Playing 上下文，允许
  对本次 Queue 重排或移除，而不是把运行状态直接等同于原 Playlist。
- Apple Music 明确区分 Play Next、Add to Queue、清空 Queue 和最近播放历史；选择新内容时
  还会询问是否替换现有 Queue。

CastFabric 应借鉴：Playlist 编辑产生新 revision；`start_playlist` 从某一 revision 物化本次
Execution Queue。当前 run 的上一项、下一项和指定 item 操作针对 Execution Queue，不反向
修改 Playlist 定义。

CastFabric 应避免：第一阶段不开放完整动态 Queue 编辑。虽然运行时 Queue 必须作为内部对象
存在，但 UI/MCP 只需上一项、下一项和选择已有 item，暂不提供插入临时资源或拖动本次 Queue。

后续讨论中的简化决定：CastFabric 只借鉴“定义具有 revision”和“运行状态不回写定义”两个
原则，不照搬完整 Queue 快照。Playlist 采用单一实时定义；当前 item 受影响时由调用方解决
结构化冲突，上一项读取实际播放历史，下一项读取当前定义。这样更符合首版规模。

## Jellyfin：库配置属于管理面，不等于日常播放面

来源（访问于 2026-09-04）：

- [Jellyfin Libraries](https://jellyfin.org/docs/general/server/libraries/)
- [Jellyfin Clients](https://jellyfin.org/docs/general/clients/)

交互观察：

- 媒体路径和库类型位于 Admin Dashboard；普通客户端消费已经整理好的内容。
- 一个 Library 可以聚合多个服务器路径，并在新增媒体时显示索引进度。
- Jellyfin 推荐明确媒体类型，反对把所有内容混进 unreliable 的 mixed library。

CastFabric 应借鉴：存储容量、上传失败、清理和数据库健康属于管理信息；播放列表内容属于
日常内容面。即便二者使用同一数据库，也不应全部堆进“连接配置”。

CastFabric 应避免：首版不开放任意服务器路径扫描。上传资源进入 CastFabric 管理的持久
目录，可以显著缩小权限、索引和文件漂移问题。

## OWASP：持久上传必须把原始文件名与实际存储路径分开

来源（访问于 2026-09-04）：

- [File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)

能力观察：

- 文件扩展名和浏览器提交的 Content-Type 都不能单独作为类型判断；应组合允许列表、内容探测
  和大小限制。
- 存储文件名不应直接使用用户输入；上传文件应使用应用生成的不透明名字并与 Web 直接路径
  隔离。
- 上传需要最小权限、容量限制和失败清理，避免覆盖、路径穿越与磁盘耗尽。

对 CastFabric 的约束：延续当前 opaque token 和受控临时目录，但持久资源按服务端 SHA-256
寻址；原始文件名只保存为显示元数据。持久上传不接受服务器任意文件路径，完成前必须验证
大小并实际探测为可播放音频。

## Jellyfin 清理警告：暂时不可用不能等同于应删除

来源（访问于 2026-09-04）：

- [Jellyfin Scheduled Tasks](https://jellyfin.org/docs/general/server/tasks/)
- [Jellyfin Storage](https://jellyfin.org/docs/general/administration/storage/)

失败观察：Jellyfin 文档明确警告，媒体存储暂时不可用时运行 collection/playlist 清理可能使
Playlist 丢失。这说明“扫描时没找到文件 → 自动删除对象关系”是危险的自动化边界。

对 CastFabric 的约束：文件丢失、损坏或外部 URL 失效时保留 MediaAsset tombstone、
PlaylistItem 和历史关系，只标记不可用；只自动删除短期上传残片。稳定无引用资源必须先预览，
再由用户或 Agent 显式确认。

## 负面案例：Sonos 2024 重构移除既有核心工作流

来源（访问于 2026-09-04）：

- [Update on the Sonos app from Patrick](https://www.sonos.com/en/blog/update-on-the-sonos-app)
- [Your feedback on the new Sonos App](https://en.community.sonos.com/general-feedback-and-conversation-229090/your-feedback-on-the-new-sonos-app-6892527)
- [New Sonos App Update](https://en.community.sonos.com/product-updates/new-sonos-app-update-6896801)

失败观察：

- 2024-05-07 发布的新应用先追求统一、可定制首页，却缺失或延后本地 Music Library 搜索、
  Playlist 编辑、Queue 编辑、Sleep Timer 和 Alarm 等已有能力。
- Sonos CEO 在 2024-07-25 公开致歉，并把恢复 Music Library、Playlist 和 Queue 编辑列入
  后续数月的修复计划；社区公告还记录了索引状态不清、操作失败和平台能力不一致。

对 CastFabric 的约束：

- 新内容页不能替代或隐藏现有“总览、音响、活动、AI 接入、连接配置”任务。
- Playlist 详情必须看得见实际运行音箱、当前 item、进度和错误，不能只有漂亮封面。
- 上传、索引、去重和清理必须展示明确状态；不能让文件已经保存但列表中暂时不可见。
- 先验证信息架构和完整工作流，再做视觉风格；不把未完成的服务端 Playlist 能力宣传为
  Skill 已经可靠处理。

## 对 CastFabric 的信息架构结论

1. 增加一个主内容入口，但以用户主要对象“播放列表”为中心；资源文件是次级管理面。
2. Playlist 详情同时展示定义（items）和相关运行摘要（active/recent runs），两者视觉分区。
3. 当前运行继续出现在总览和音响上下文；完整内容编辑不进入总览或音响页。
4. Activity 保留系统与协议诊断职责；内容播放历史从 Playlist/Run 进入，可链接到关联 Activity。
5. AI 接入页只说明和复制 MCP 接入方式，不成为媒体管理后台。
6. 媒体容量、无引用资源和清理属于内容页的“存储”次级视图；只有真正需要用户选择的全局
   策略才进入连接配置。
