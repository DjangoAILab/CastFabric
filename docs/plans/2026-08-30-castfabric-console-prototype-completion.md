# CastFabric Complete Console Prototype Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the CastFabric product prototype after Home approval without connecting it to production APIs.

**Architecture:** Keep the approved v5 Home composition, add Speakers and Activity page states plus Speaker, Event, Discovery, and Connections overlays in one disconnected HTML review artifact. Bind every displayed product datum and action to a machine-readable capability contract before visual verification.

**Tech Stack:** Static HTML/CSS/JavaScript, Python standard-library contract validator, Playwright browser verification, Markdown/JSON architecture documents.

**Workspace note:** This plan changes only `docs/` prototype and validation artifacts on the existing feature worktree. Production Web UI, API and runtime remain untouched.

---

### Task 1: Audit product fields against runtime and target architecture

**Files:**
- Create: `docs/adr/0005-console-observability-contract.md`
- Create: `docs/architecture/castfabric-console-data-contract.md`
- Create: `docs/design/contracts/castfabric-console-fields.json`

**Steps:**
1. Map current `Config`, target discovery, renderer, AirPlay and MiPlay diagnostics to product fields.
2. Mark each field current, derived, planned or forbidden.
3. Define fallbacks, privacy class and collection owner for every planned field.
4. Verify the model preserves one Receiver Suite per output and contains no selected/default target UI.
5. Commit with the complete prototype after visual acceptance gates pass.

### Task 2: Add a machine-checkable prototype gate

**Files:**
- Create: `docs/prototypes/validate_console_prototype.py`
- Test: `docs/design/contracts/castfabric-console-fields.json`

**Steps:**
1. Parse `data-field` and `data-action` bindings from the prototype.
2. Fail on unknown or forbidden fields.
3. Fail when a planned field lacks an owner or fallback.
4. Run the validator and require `PASS: console prototype data contract`.

### Task 3: Build the complete v6 review prototype

**Files:**
- Create: `docs/prototypes/castfabric-console-v6.html`
- Modify: `docs/prototypes/README.md`

**Steps:**
1. Preserve the approved Home switchboard and remove unmeasurable numeric end-to-end latency.
2. Add the complete Speakers registry with independent toggles, discovery, detail and edit states.
3. Add the Activity event timeline, filters and event detail.
4. Add the sectioned Connections dialog with discovery, receiver naming, playback, network, extensions and system sections.
5. Implement Chinese/English switching, keyboard-close behavior and review scenarios.

### Task 4: Verify product, interaction and visual states

**Files:**
- Verify: `docs/prototypes/castfabric-console-v6.html`
- Verify: `docs/prototypes/validate_console_prototype.py`

**Steps:**
1. Run the data-contract validator and JavaScript syntax check.
2. Exercise all navigation, filters, toggles, drawers, dialogs and save/cancel flows.
3. Verify normal, empty, loading, degraded and error scenarios.
4. Verify Chinese and English visible copy and ARIA labels.
5. Capture desktop and mobile screenshots and inspect each before delivery.
6. Run `git diff --check`, update roadmap status, commit and push.

## 执行结果（2026-08-30）

- [x] 五类领域对象与字段来源已固化到 ADR-0005 和控制台数据契约。
- [x] 所有原型 `data-field` / `data-action` 通过机器契约校验；禁止字段未进入 DOM。
- [x] v6 已覆盖总览、音响、活动、音响详情、事件详情和六分区连接配置。
- [x] 已验证独立音响启停不会修改其他音响。
- [x] 已验证桌面首页无滚动、移动端无横向溢出、完整中英文和五类评审状态。
- [x] 已验证弹窗、抽屉、筛选、键盘关闭和配置语言切换。

复验命令：

```bash
python3 docs/prototypes/validate_console_prototype.py docs/prototypes/castfabric-console-v6.html
NODE_PATH=/Users/wang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
  /Users/wang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  docs/prototypes/verify_console_prototype.cjs /tmp/castfabric-prototype-shots
```
