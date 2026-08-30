# ADR-0006：以 Receiver Suite 注册表渐进替换全局运行对象

## 状态

Accepted for implementation

## 背景

产品模型已经确认每台输出音响拥有独立 Receiver Suite，但当前应用仍有一个全局
`miplay_receiver`，DLNA、AirPlay 和目标控制器分别保存在不同字典中，Web API 再从这些
对象临时拼状态。直接把 v6 UI 接到旧 API 会重新固化“首个/默认目标”语义；一次性重写
所有协议服务又会把已经通过真机验证的链路置于不必要风险中。

## 决策

1. 采用渐进替换：先引入纯领域 read model、发现注册表、会话协调器和事件日志，再让
   现有协议实例逐个登记到 `ReceiverSuiteRegistry`，最后切换新 API 和生产 UI。
2. `ReceiverSuiteRegistry` 以稳定 `target_id` 为唯一键，持有目标控制器和三个入口的
   生命周期/诊断引用；共享 DLNA HTTP/SSDP 基础设施仍由应用级 runtime 托管。
3. 每个 MiPlay receiver 使用独立 TCP 端口。`miplay_port=0` 让系统分配临时端口；非零
   基准端口按稳定目标顺序递增。单端口冲突只把该入口标为 unavailable。
4. 同一 target 的会话由 `MediaSessionCoordinator` 串行仲裁；不同 target 使用独立锁，
   可以并行。首版只记录真实协议回调，不从文本日志反推事件。
5. 活动日志使用内存有界 deque，并向 `conf/activity.jsonl` 追加脱敏 JSONL；轮转采用固定
   大小和文件数，不引入数据库或消息队列。
6. 保留 `miplay_receiver`、`default_target_id` 和旧 API 作为一个迁移发布周期的兼容面；
   新代码只写集合模型，兼容属性返回稳定排序后的首项，不参与路由选择。

## 后果

### 正面

- 可以复用已验证的协议实现，同时逐层关闭全局状态。
- 单个 MiPlay/AirPlay 实例失败不会清空 DLNA 或其他音响。
- 控制台字段有稳定来源，结构化事件不会依赖日志文案。

### 负面

- 迁移期会同时维护旧兼容属性和新集合 API。
- 多 MiPlay 实例增加 socket、zeroconf 和 ffmpeg 资源，需要明确上限和清理测试。
- 动态启停必须补共享 DLNA 注册/注销能力，不能只调用进程重启。

### 中性

- 端口在目标集合变化后可能重新分配；发送端通过 mDNS 发现，不承诺固定 MiPlay 端口。
- 首版事件历史重启后由 JSONL 恢复有限窗口，不提供长期统计。

## 备选方案

### 一次性重写协议运行时

结构最终最整齐，但会同时改变 DLNA、AirPlay、MiPlay 和真机部署，回归面过大，拒绝。

### Web API 直接聚合旧对象

上线最快，但无法表达每目标 MiPlay、会话所有权和结构化事件，且继续依赖默认目标，拒绝。

### 引入 SQLite 事件数据库

查询方便，但当前规模只需最近活动，增加迁移、锁和备份成本，暂不采用。

## 参考

- [ADR-0004：每输出音响独立 Receiver Suite](0004-one-receiver-suite-per-output.md)
- [ADR-0005：控制台可观测性契约](0005-console-observability-contract.md)
- [控制台字段实现审计](../architecture/castfabric-console-field-audit.md)
