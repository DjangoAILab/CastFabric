# Home Server 内容导入记录

日期：2026-09-06。通过现有 HTTPS Media / Playlist API 写入，无代码部署、无直接数据库修改、无播放命令。

## 已创建的用户内容

| 播放列表 | 内容 | 服务端 ID | 默认方式 |
| --- | --- | --- | --- |
| 有声书 · 鲁迅《呐喊》 | 完整 16 节，约 4 小时 38 分钟，Jing Li 普通话朗读 | `4lF1w0ieoEkE3lEDCqxE7ddP` | 顺序、结束停止 |
| 睡眠轻音乐 · 钢琴与氛围 | 4 首，约 19 分钟，Scott Buckley 无人声音乐 | `JTmvUk79OwB3zzS2qK9VL76u` | 顺序、结束停止 |

全部 20 个 MP3 均是持久化 managed files，不依赖播放时访问外部下载站。音频不加入 Git。用户可编辑显示名、说明、标签，授权及来源已写入逐项资源说明。

### 有声书来源

- [LibriVox: Call to Arms / 呐喊](https://librivox.org/call-to-arms-by-xun-lu/)
- [Internet Archive 原始条目与文件](https://archive.org/details/call_to_arms_jl_librivox)
- [录音公有领域说明](https://archive.org/download/LibrivoxCdCoverArt23/calltoarms_1210.pdf)
- 使用 `calltoarms_01_lu_64kb.mp3` 至 `calltoarms_16_lu_64kb.mp3`，按原书顺序：自序、狂人日记、孔乙己、药、明天、一件小事、头发的故事、风波、故乡、阿Q正传（上）、阿Q正传（下）、端午节、白光、兔和猫、鸭的喜剧、社戏。

### 轻音乐来源

全部作者为 Scott Buckley，许可 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，原始音频未改编。按作者的风格描述选取舒缓钢琴/氛围曲目，不作医学效果承诺；没有进行主观听感验收。

| 曲目 | 时长约 | 官方来源 | 下载文件 |
| --- | --- | --- | --- |
| Sleep · 梦境 | 3:04 | [Sleep](https://www.scottbuckley.com.au/library/sleep/) | `2019/08/sb_sleep.mp3` |
| Moonlight · 月光 | 4:14 | [Moonlight](https://www.scottbuckley.com.au/library/moonlight/) | `2022/07/Moonlight.mp3` |
| Solace · 慰藉 | 5:56 | [Solace](https://www.scottbuckley.com.au/library/solace/) | `2020/05/sb_solace.mp3` |
| Hiraeth · 归心 | 5:46 | [Hiraeth](https://www.scottbuckley.com.au/library/hiraeth/) | `2020/06/sb_hiraeth.mp3` |

下载根路径为官方站 `https://www.scottbuckley.com.au/library/wp-content/uploads/`。Sleep 的钢琴独奏备用链接返回 406，实际采用可用的原版 Sleep，未将其误标为纯钢琴。

### 为什么没有使用旧有声书目录

已查阅用户指定的 [LiberSonora](https://github.com/LiberSonora/LiberSonora)：它主要提供工具与示例资源链接，工具的 MIT 授权不等于所有示例录音的授权。网上已经找到来源与录音许可明确的完整中文书，因此没有进入 Home Server 的旧资源目录进行广泛搜索。

## 验证与边界

- 20 个下载文件通过 MP3 元数据解析，均有合理非零时长；16 个书籍文件另核对 Archive 的字节长度与 MD5。
- 导入后逐个验证服务端 `Range: bytes=0-127` 返回 206，内容与上传文件开头一致。
- 最终 API 列表为两本播放列表，分别 16 / 4 项；全部 20 个资源状态 `available`。
- 有声书最后两节的下载曾 SSL 中断；按已导入的标题幂等补齐，无重复条目。
- 本次未发送播放、停止、音量或重启命令。导入结束发现一个 `starting` 会话，`started_at=2026-09-06T02:07:18Z`，早于本次导入；未擅自停止，也不把它当成本次播放验收证据。
- **新发现待修复：** 当前 `_duration` 仅提取 WAV 时长，MP3 资源的 `duration_seconds` 是 `null`，播放列表合计显示 `0`。逐项说明中保留了本地解析出的时长；不能将界面上的 0 当作音频真实长度。后续 UI/代码修订获批后，增加通用本地音频时长提取与已导入资源回填，并保证未知时长不误报为零。
- 本次仅验证内容持久化 API 与音频读取；没有重新做实际音响拉流、发声、重启持久化验收。

## 后续发布门禁（已完成）

用户随后审批 A 方向原型、授权实现，并明确确认部署验收。`v0.11.0-alpha.4` 已合并、推送、发布并部署。
20 个 MP3 的缺失时长全部补齐，书籍合计 16696.4506 秒，轻音乐合计 1141.1513 秒。资源元数据、ID、列表顺序和 revision 保持不变；重启、数据库完整性、32 MCP 工具及全部音频 Range 读取通过。
上文“待修复”和“未重启”是导入当时的历史记录，不再代表当前状态。完整发布/部署证据见 `docs/testing/2026-09-06-header-dialog-release.md`；未新增主观听感验收。
