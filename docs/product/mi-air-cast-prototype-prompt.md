# MiAir Cast 安卓客户端原型提示词（历史资料）

> 本文件描述的是早期安卓 PCM 推流客户端，不是 CastFabric 控制台，也不代表当前
> 项目名称或产品模型。保留它仅用于未来可能恢复安卓发送端探索。

生成方式：Codex 内置 imagegen  
用途：产品方向评审，不作为像素级实现规范

```text
Use case: ui-mockup
Asset type: Android mobile app product prototype overview
Primary request: create a polished, realistic four-screen Android app prototype for “MiAir Cast”, an app that sends allowed Android system media audio as lossless PCM over the home Wi-Fi to a bedroom Xiaomi speaker through a MiAir server.
Style/medium: shippable Material 3 product UI, not concept art; dark mode; precise spacing; restrained and trustworthy home-audio utility.
Composition/framing: landscape presentation board with four complete tall Android phone screens side by side, equal size, no device-brand logos. Each screen has a clear single primary action.
Color palette: near-black and charcoal surfaces, off-white text, restrained teal/cyan accent for healthy PCM flow, amber only for warnings.
Typography: modern Chinese sans-serif, large readable hierarchy, avoid tiny text.

Screen 1 — onboarding and pairing:
Text (verbatim): “让卧室音箱成为手机的无线声卡”
Text (verbatim): “仅传输媒体声音，不采集画面，不保存音频”
Show a discovered server card named “MiAir 家庭服务器” and a primary button “连接 MiAir”.

Screen 2 — ready home:
Text (verbatim): “卧室小爱 HD”
Text (verbatim): “MiAir 已连接”
Show small capability chips “PCM 48 kHz”, “局域网”, “无新增有损编码”.
Large primary button “开始投送”.

Screen 3 — active streaming:
Text (verbatim): “正在投送”
Text (verbatim): “系统媒体音频”
Show an elegant live waveform, three healthy pipeline steps “手机采集中”, “MiAir 已接收”, “音箱已连接”, small metrics “延迟 620 ms” and “网络稳定”, a speaker volume slider, and a strong button “停止投送”.

Screen 4 — actionable limitation state:
Text (verbatim): “未检测到可捕获音频”
Text (verbatim): “当前应用可能不允许第三方捕获声音”
Show two actions “换个应用试试” and “查看诊断”. Use amber warning accents without making the screen alarming.

Constraints: render all specified Chinese text verbatim and only once where requested; practical Android UI; no song artwork; no fake song metadata; no microphone icon; no screen-recording preview; no Apple styling; no gradients except extremely subtle surface depth; no logos, no watermarks, no decorative clutter.
```
