# ADR-0001：首版采用 AudioPlaybackCapture 作为 Android PCM 输入

## 状态

Accepted for MVP validation

## 背景

M01 不支持小米妙播，蓝牙可能退化到 SBC，现有 MiAir 则能够让 M01
从局域网 HTTP 地址拉取音频。我们需要一个无需 Root、无需额外硬件、能够
从 Redmi K60 Ultra 实时发送媒体声音的首版方案，并且避免新增 AAC/SBC
有损编码。

普通 Android App 不能注册系统级虚拟音频输出设备。USB Audio Gadget
能够提供更原生、覆盖更完整的系统音频路由，但需要随身硬件、USB 供电和线缆。

## 决策

首版使用 Android `AudioPlaybackCapture` + `AudioRecord` 获取系统允许捕获的
PCM 16-bit/48 kHz/双声道，经版本化 WebSocket 二进制协议发送给 MiAir。
MiAir 使用抖动缓冲并输出实时 WAV HTTP 流给 M01。

同时把 MiAir PCM Session 设计成输入无关接口，使未来 USB UAC 网桥可以
复用同一后端。

## 后果

### 正面

- 无 Root、无外接硬件，最适合先验证 M01 实时 WAV 的体验上限。
- 手机到 MiAir 不增加有损编码。
- 完全无线，能覆盖大多数普通音乐、视频、播客和游戏。
- 后端可复用于未来 USB UAC 网桥。
- 开发和故障定位边界清晰。

### 负面

- Android 14+ 每个新会话需要用户确认 MediaProjection。
- DRM、通话和禁止第三方捕获的 App 可能输出静音。
- Android 系统混音可能发生采样率转换，因此是无有损编码，不承诺源文件 bit-perfect。
- 端到端延迟仍受 M01 HTTP 缓冲影响，不保证视频口型同步。

### 中性

- 首版使用 PCM 约 192 KB/s，家庭 Wi-Fi 容量足够。
- 用户继续在源 App 内控制播放；MiAir Cast 只控制目标音箱音量和投送会话。

## 备选方案

### USB UAC Wi-Fi 网桥

更接近原生插入声卡，覆盖 DRM 和更多系统音频；但引入硬件、线缆、供电和
USB-C 角色兼容问题。保留为 Phase 3，等待 M01 实时 WAV 链路验证通过。

### Root/Audio HAL/Remote Submix

理论体验最佳，但会提高主力手机的系统升级、完整性、DRM 和安全维护成本，
不适合 MVP。

### 蓝牙 A2DP 网桥

系统体验原生，但仍受 SBC/AAC/LDAC 编码与距离约束，不满足避免新增有损编码的目标。

### MiPlay 接收器模拟

能够提供小米原生入口，但协议私有、接收端实现不成熟，而且已观察路径使用 AAC，
不适合作为首个无损 PCM 验证方案。

## 参考

- https://developer.android.com/media/platform/av-capture
- https://developer.android.com/reference/android/media/AudioPlaybackCaptureConfiguration.html
- `docs/plans/2026-08-25-android-pcm-cast-design.md`

