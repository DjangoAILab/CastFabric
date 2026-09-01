/* CastFabric Runtime v2 console. All rendered values come from /api/v1. */
(() => {
  'use strict';

  const state = {
    system: null,
    targets: [],
    suites: [],
    sessions: [],
    events: [],
    settings: null,
    selectedTargetId: null,
    selectedEventId: null,
    loading: true,
    error: null,
  };

  Object.assign(translations, {
    calm: ['当前没有投放', 'No active cast right now'],
    calmDetail: ['接收入口保持就绪，等待下一次投放', 'Receivers are ready for the next cast'],
    sourceUnknown: ['发送设备', 'Sender device'],
    sourceNotProvided: ['协议未提供设备名称', 'The protocol did not provide a device name'],
    outputUnknown: ['未配置输出', 'Output not configured'],
    healthDegraded: ['部分声路需要留意', 'Some routes need attention'],
    healthIdle: ['等待配置音响', 'Waiting for a speaker'],
    healthUnavailable: ['状态暂时不可用', 'Status is temporarily unavailable'],
    onlineUnknown: ['尚未完成扫描', 'Not scanned yet'],
    onlineLatest: ['本次扫描在线', 'Online in latest scan'],
    offlineLatest: ['本次扫描未发现', 'Not seen in latest scan'],
    readyState: ['已就绪', 'Ready'], activeState: ['传输中', 'Active'],
    stoppedState: ['已停止', 'Stopped'], unavailableState: ['不可用', 'Unavailable'],
    degradedState: ['需留意', 'Attention'], startingState: ['启动中', 'Starting'],
    playingState: ['播放中', 'Playing'], pausedState: ['已暂停', 'Paused'],
    failedState: ['异常结束', 'Failed'], endedState: ['已结束', 'Ended'],
    unknownState: ['未知', 'Unknown'],
    savedLive: ['更改已保存', 'Changes saved'],
    savedRestart: ['已保存；重启服务后生效', 'Saved; restart the service to apply'],
    actionFailed: ['操作未完成，请稍后重试', 'The action could not be completed'],
    scanningLive: ['正在扫描；现有音响保持可用', 'Scanning; existing speakers remain available'],
    scanComplete: ['扫描完成', 'Scan complete'],
    noReason: ['未提供原因代码', 'No reason code provided'],
    noSession: ['未关联会话', 'No linked session'],
    eventInfo: ['信息', 'Info'],
    addressOnly: ['局域网地址', 'LAN address'],
    unknownTime: ['暂无活动', 'No activity yet'],
    configuredLive: ['已配置', 'Configured'], newTarget: ['新发现', 'Newly found'],
    enableTarget: ['启用', 'Enable'],
  });

  const tr = key => t(key);
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
  const byId = items => new Map(items.map(item => [item.id || item.target?.id, item]));
  const targetMap = () => byId(state.targets);
  const suiteMap = () => byId(state.suites);

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: options.body ? {'Content-Type': 'application/json'} : {},
      ...options,
    });
    const type = response.headers.get('content-type') || '';
    const payload = type.includes('json') ? await response.json() : null;
    if (!response.ok) {
      const error = new Error(payload?.error?.code || `HTTP_${response.status}`);
      error.payload = payload;
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function setText(selector, value) {
    document.querySelectorAll(selector).forEach(node => { node.textContent = value; });
  }

  function formatTime(value, relative = false) {
    if (!value) return tr('unknownTime');
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return tr('unknownTime');
    if (relative) {
      const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
      if (seconds < 60) return language === 'zh' ? '刚刚' : 'Just now';
      if (seconds < 3600) return language === 'zh' ? `${Math.floor(seconds / 60)} 分钟前` : `${Math.floor(seconds / 60)} min ago`;
      if (seconds < 86400) return language === 'zh' ? `${Math.floor(seconds / 3600)} 小时前` : `${Math.floor(seconds / 3600)} h ago`;
    }
    return new Intl.DateTimeFormat(language === 'zh' ? 'zh-CN' : 'en', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  function stateLabel(value) {
    return tr({
      ready: 'readyState', active: 'activeState', stopped: 'stoppedState',
      unavailable: 'unavailableState', degraded: 'degradedState', starting: 'startingState',
      playing: 'playingState', paused: 'pausedState', failed: 'failedState',
      ended: 'endedState', healthy: 'healthyShort', disabled: 'disabled',
      idle: 'healthIdle', scanning: 'startingState', error: 'failedState',
      authenticated: 'success'
    }[value] || 'unknownState');
  }

  function onlineLabel(value) {
    return value === true ? tr('onlineLatest') : value === false ? tr('offlineLatest') : tr('onlineUnknown');
  }

  function summaryLabel(event) {
    const labels = {
      'activity.session_started': ['投放已开始', 'Casting started'],
      'activity.session_ended': ['投放已结束', 'Casting ended'],
      'activity.session_failed': ['投放异常结束', 'Casting failed'],
      'activity.session_preempted': ['投放被新会话接管', 'Casting was taken over'],
      'activity.miplay_output_started': ['实体音响已开始拉取音频', 'Speaker started pulling audio'],
      'activity.miplay_pcm_forwarded': ['音频已送入实体输出', 'Audio reached the physical output'],
      'activity.miplay_output_failed': ['实体输出未建立', 'Physical output was not established'],
      'activity.miplay_output_stopped': ['实体输出已停止', 'Physical output stopped'],
    };
    const pair = labels[event.summary_key];
    return pair ? pair[language === 'zh' ? 0 : 1] : event.type.replaceAll('.', ' · ');
  }

  function renderNumbers() {
    if (!state.system) return;
    const s = state.system;
    setText('[data-field="system.targets.count"]', s.targets.count);
    setText('[data-field="system.suites.enabled_count"]', s.suites.enabled_count);
    setText('[data-field="system.sessions.playing_count"]', s.sessions.playing_count);
    setText('[data-field="system.suites.ready_count"]', s.suites.ready_count);
    setText('[data-field="system.suites.attention_count"]', s.suites.attention_count);
    setText('[data-field="system.suites.disabled_count"]', s.suites.disabled_count);
    setText('[data-field="system.version"]', s.version);
    const summary = document.querySelector('.health-summary');
    summary?.classList.remove('degraded', 'idle');
    if (s.health !== 'healthy') summary?.classList.add(s.health);
    const label = summary?.querySelector('.health-copy strong');
    if (label) label.textContent = s.health === 'healthy' ? tr('healthy') : s.health === 'idle' ? tr('healthIdle') : tr('healthDegraded');
  }

  function renderHome() {
    const stack = document.querySelector('#page-home .lane-stack');
    if (!stack) return;
    const targets = targetMap();
    const suites = suiteMap();
    const active = state.sessions.slice(0, 3);
    if (!active.length) {
      stack.innerHTML = `<article class="route-row route-empty"><div class="empty-signal"><span class="empty-orbit" aria-hidden="true"></span><strong>${esc(tr('calm'))}</strong><span>${esc(tr('calmDetail'))}</span></div></article>`;
      return;
    }
    stack.innerHTML = active.map((session, index) => {
      const target = targets.get(session.target_id);
      const suite = suites.get(session.target_id);
      const source = session.source?.device_name || tr('sourceUnknown');
      const sourceHint = session.source?.device_name ? (session.source.provenance || '') : tr('sourceNotProvided');
      const playing = session.state === 'playing';
      const rowClass = playing ? 'live' : session.state === 'paused' ? 'paused' : suite?.health === 'healthy' ? '' : 'attention';
      return `<article class="route-row ${rowClass}" style="animation-delay:${index * .08}s">
        <div class="endpoint source-endpoint"><span class="endpoint-icon unknown"></span><div class="endpoint-copy"><small>${esc(tr('sender'))}</small><strong>${esc(source)}</strong><span>${esc(sourceHint)}</span></div><span class="endpoint-state">${esc(stateLabel(session.state))}</span></div>
        <div class="route-channel"><span class="protocol-chip">${esc(session.protocol)}</span><span class="route-line">${playing ? '<i class="signal-packet"></i>' : ''}</span><span class="route-result">${esc(playing ? tr('routing') : stateLabel(session.state))}</span></div>
        <div class="endpoint output-endpoint"><span class="endpoint-icon speaker"></span><div class="endpoint-copy"><small>${esc(tr('output'))}</small><strong>${esc(target?.name || tr('outputUnknown'))}</strong><span>${esc(onlineLabel(target?.online))}</span></div><span class="endpoint-state">${esc(suite?.health === 'healthy' ? tr('readyState') : tr('degradedState'))}</span></div>
      </article>`;
    }).join('');
  }

  function ingressHtml(suite, enabled) {
    const ingress = suite?.ingress || {};
    return ['dlna', 'airplay', 'miplay'].map(protocol => {
      const item = ingress[protocol];
      const itemState = enabled ? (item?.state || 'unavailable') : 'stopped';
      const cls = itemState === 'active' ? 'active' : ['degraded', 'unavailable'].includes(itemState) ? 'warn' : itemState === 'stopped' ? 'off' : '';
      return `<span class="ingress-pill ${cls}"><i></i><span>${protocol === 'airplay' ? 'AirPlay' : protocol === 'miplay' ? 'MiPlay' : 'DLNA'} · ${esc(stateLabel(itemState))}</span></span>`;
    }).join('');
  }

  function setPageState(page, mode) {
    page.classList.remove('is-loading', 'is-empty', 'is-error', 'is-degraded');
    if (mode) page.classList.add(`is-${mode}`);
  }

  function renderSpeakers() {
    const page = document.getElementById('page-speakers');
    const registry = page.querySelector('.registry');
    const head = registry.querySelector('.registry-head');
    registry.querySelectorAll('.speaker-row').forEach(node => node.remove());
    registry.classList.add('registry-live');
    if (state.error) { setPageState(page, 'error'); return; }
    if (!state.targets.length) { setPageState(page, 'empty'); return; }
    setPageState(page, state.system?.health === 'degraded' ? 'degraded' : null);
    const suites = suiteMap();
    const sessionsByTarget = new Map(state.sessions.map(item => [item.target_id, item]));
    state.targets.forEach(target => {
      const suite = suites.get(target.id);
      const session = sessionsByTarget.get(target.id);
      const row = document.createElement('article');
      row.className = `speaker-row ${target.enabled ? '' : 'disabled'} ${session?.state === 'playing' ? 'playing' : ''}`;
      row.tabIndex = 0;
      row.dataset.targetId = target.id;
      row.innerHTML = `<div class="speaker-identity"><span class="endpoint-icon speaker"></span><div><strong>${esc(target.name)}</strong><span>${esc(target.location_host || '—')} · ${esc(target.kind.toUpperCase())}</span></div></div>
        <div class="output-state"><strong>${esc(onlineLabel(target.online))}</strong><span>${esc(target.suite_health === 'healthy' ? tr('localControl') : stateLabel(target.suite_health))}</span></div>
        <div class="ingress-strip">${ingressHtml(suite, target.enabled)}</div>
        <div class="activity-state"><strong>${esc(suite?.last_activity_at ? formatTime(suite.last_activity_at, true) : tr('unknownTime'))}</strong><span>${esc(session?.protocol || '—')}</span></div>
        <button class="suite-toggle" aria-label="${esc(tr('toggleReceiver'))}" aria-pressed="${target.enabled}" data-live-toggle></button><span class="chevron">›</span>`;
      registry.appendChild(row);
    });
  }

  function renderEventFilters() {
    const select = document.getElementById('speakerFilter');
    const current = select.value || 'all';
    select.innerHTML = `<option value="all">${esc(tr('all'))}</option>` + state.targets.map(target => `<option value="${esc(target.id)}">${esc(target.name)}</option>`).join('');
    select.value = state.targets.some(item => item.id === current) ? current : 'all';
    const protocol = document.getElementById('protocolFilter');
    const protocolValue = protocol.value || 'all';
    protocol.innerHTML = `<option value="all">${esc(tr('all'))}</option><option value="dlna">DLNA</option><option value="airplay">AirPlay</option><option value="miplay">MiPlay</option>`;
    protocol.value = protocolValue;
    const outcome = document.getElementById('resultFilter');
    const outcomeValue = outcome.value || 'all';
    outcome.innerHTML = `<option value="all">${esc(tr('all'))}</option><option value="success">${esc(tr('success'))}</option><option value="failed">${esc(tr('failed'))}</option>`;
    outcome.value = outcomeValue;
  }

  function renderEvents() {
    const page = document.getElementById('page-activity');
    const list = page.querySelector('.event-list');
    list.classList.add('event-list-live');
    renderEventFilters();
    const targetFilter = document.getElementById('speakerFilter').value;
    const protocolFilter = document.getElementById('protocolFilter').value;
    const outcomeFilter = document.getElementById('resultFilter').value;
    const filtered = state.events.filter(event =>
      (targetFilter === 'all' || event.target_id === targetFilter) &&
      (protocolFilter === 'all' || event.protocol === protocolFilter) &&
      (outcomeFilter === 'all' || event.outcome === outcomeFilter)
    );
    list.innerHTML = `<div class="event-day">${esc(tr('today'))}</div>`;
    if (state.error) { setPageState(page, 'error'); return; }
    if (!state.events.length) { setPageState(page, 'empty'); return; }
    setPageState(page, state.system?.observability?.state === 'degraded' ? 'degraded' : null);
    const targets = targetMap();
    filtered.forEach(event => {
      const target = targets.get(event.target_id);
      const button = document.createElement('button');
      button.className = `event-item ${event.outcome === 'failed' ? 'failed' : event.outcome === 'info' ? 'info' : ''}`;
      button.dataset.eventId = event.id;
      button.innerHTML = `<span class="event-time">${esc(formatTime(event.occurred_at))}</span><i class="event-dot"></i><span class="event-speaker"><strong>${esc(target?.name || event.target_id)}</strong><span>${esc(tr('sourceUnknown'))}</span></span><span class="event-protocol">${esc(event.protocol || '—')}</span><span class="event-summary"><strong>${esc(summaryLabel(event))}</strong><span>${esc(event.reason_code || event.type)}</span></span><span class="status-chip ${event.outcome === 'failed' ? 'warn' : ''}">${esc(event.outcome === 'failed' ? tr('failed') : event.outcome === 'success' ? tr('success') : tr('eventInfo'))}</span><span class="event-arrow">›</span>`;
      list.appendChild(button);
    });
    page.querySelector('.filter-empty').style.display = filtered.length ? 'none' : 'grid';
    page.querySelector('[data-filter-count]').textContent = language === 'zh' ? `${filtered.length} 条事件` : `${filtered.length} events`;
  }

  function renderSpeakerDrawer() {
    const target = targetMap().get(state.selectedTargetId);
    if (!target) return;
    const suite = suiteMap().get(target.id);
    const overlay = document.getElementById('speakerOverlay');
    const name = overlay.querySelector('[data-drawer-name]');
    const alias = overlay.querySelector('[data-drawer-alias]');
    [name, alias].forEach(node => node?.removeAttribute('data-i18n'));
    name.textContent = target.name;
    alias.textContent = target.receiver_alias;
    overlay.querySelector('[data-edit-name]').value = target.name;
    overlay.querySelector('[data-edit-alias]').value = target.receiver_alias;
    const chip = overlay.querySelector('[data-field="suite.health"]');
    chip.removeAttribute('data-i18n'); chip.textContent = stateLabel(suite?.health || target.suite_health);
    const detailValues = overlay.querySelectorAll('.detail-grid .detail-cell strong');
    detailValues[0].textContent = target.location_host || '—';
    detailValues[1].textContent = onlineLabel(target.online);
    detailValues[2].textContent = target.kind.toUpperCase();
    detailValues[3].textContent = suite?.last_activity_at ? formatTime(suite.last_activity_at, true) : tr('unknownTime');
    overlay.querySelector('.drawer-body > .ingress-strip').innerHTML = ingressHtml(suite, target.enabled);
    const toggle = overlay.querySelector('.danger-zone button');
    toggle.dataset.liveTargetToggle = target.id;
    toggle.textContent = target.enabled ? tr('disableSpeaker') : tr('enableTarget');
  }

  async function openEventDrawer(eventId) {
    const payload = await api(`/api/v1/events/${encodeURIComponent(eventId)}`);
    state.selectedEventId = eventId;
    const {event, session, target} = payload;
    const overlay = document.getElementById('eventOverlay');
    const title = overlay.querySelector('[data-field="event.summary_key"]');
    title.removeAttribute('data-i18n'); title.textContent = summaryLabel(event);
    const heroMeta = title.nextElementSibling;
    heroMeta.textContent = `${target?.name || event.target_id} · ${event.protocol || '—'}`;
    const outcome = overlay.querySelector('[data-field="event.outcome"]');
    outcome.removeAttribute('data-i18n'); outcome.textContent = event.outcome === 'failed' ? tr('failed') : event.outcome === 'success' ? tr('success') : tr('eventInfo');
    outcome.className = `status-chip ${event.outcome === 'failed' ? 'warn' : ''}`;
    const values = overlay.querySelectorAll('.detail-grid .detail-cell strong');
    values[0].textContent = formatTime(event.occurred_at);
    values[1].textContent = session?.source?.device_name || tr('sourceUnknown');
    values[2].textContent = session?.id ? `…${session.id.slice(-8)}` : tr('noSession');
    values[3].textContent = event.reason_code || tr('noReason');
    overlay.querySelector('.event-sequence').innerHTML = `<div class="sequence-step ${event.outcome === 'failed' ? 'warn' : ''}"><strong>${esc(summaryLabel(event))}</strong><span>${esc(formatTime(event.occurred_at))} · ${esc(event.type)}</span></div>`;
    const details = overlay.querySelector('[data-field="event.details"]');
    const entries = Object.entries(event.details || {});
    details.innerHTML = entries.length ? entries.map(([key, value]) => `<div class="setting-row"><div class="setting-copy"><strong>${esc(key)}</strong></div><div class="setting-value">${esc(value)}</div></div>`).join('') : `<div class="event-details-empty">—</div>`;
    openOverlay('eventOverlay');
  }

  function renderSettings() {
    if (!state.settings || !state.system) return;
    const settings = state.settings;
    const overlay = document.getElementById('settingsOverlay');
    overlay.querySelector('[data-field="system.interface"]').textContent = state.system.hostname;
    const observedAt = overlay.querySelector('[data-field="system.discovery.observed_at"]');
    observedAt.removeAttribute('data-i18n');
    observedAt.textContent = state.system.discovery.observed_at ? formatTime(state.system.discovery.observed_at, true) : tr('onlineUnknown');
    const discovery = overlay.querySelector('[data-field="system.discovery.state"]');
    discovery.removeAttribute('data-i18n'); discovery.textContent = stateLabel(state.system.discovery.state);
    overlay.querySelector('[data-field="system.receiver_prefix"]').value = settings.identity.receiver_prefix;
    overlay.querySelector('[data-field="system.suites.protocol_health"]').innerHTML = ['dlna','airplay','miplay'].map(protocol => { const item = state.system.suites.protocol_health[protocol]; return `<span class="ingress-pill ${item.ready < item.total ? 'warn' : ''}"><i></i>${protocol === 'airplay' ? 'AirPlay' : protocol === 'miplay' ? 'MiPlay' : 'DLNA'} · ${item.ready}/${item.total}</span>`; }).join('');
    overlay.querySelector('[data-field="config.follow_device_volume"]').setAttribute('aria-pressed', String(settings.playback.follow_device_volume));
    overlay.querySelector('[data-field="config.default_volume"]').value = settings.playback.default_volume;
    overlay.querySelector('[data-field="config.auto_resume"]').setAttribute('aria-pressed', String(settings.playback.auto_resume_on_interrupt));
    overlay.querySelector('[data-field="config.resume_delay"]').value = settings.playback.resume_delay_seconds;
    overlay.querySelector('[data-field="system.port.web"]').value = settings.network.web_port;
    overlay.querySelector('[data-field="system.port.dlna"]').value = settings.network.dlna_port;
    overlay.querySelector('[data-field="system.port.miplay"]').value = settings.network.miplay_port;
    overlay.querySelector('[data-field="system.xiaomi_extension"]').setAttribute('aria-pressed', String(settings.extensions.xiaomi_enabled));
    const auth = overlay.querySelector('[data-field="system.xiaomi_auth_state"]');
    auth.removeAttribute('data-i18n'); auth.textContent = stateLabel(settings.extensions.xiaomi_auth_state);
    const logLevel = overlay.querySelector('[data-field="system.log_level"]');
    logLevel.selectedIndex = settings.system.log_level === 'debug' ? 1 : 0;
    renderScanTargets();
  }

  function renderScanTargets() {
    const list = document.querySelector('#settingsOverlay .target-scan-list');
    if (!list) return;
    list.innerHTML = state.targets.map(target => `<div class="scan-target"><div><strong>${esc(target.name)}</strong><span>${esc(target.location_host || '—')} · ${esc(target.enabled ? tr('configuredLive') : tr('newTarget'))}</span></div><button ${target.enabled ? 'disabled' : ''} data-enable-target="${esc(target.id)}">${esc(target.enabled ? tr('configuredLive') : tr('enableTarget'))}</button></div>`).join('') || `<div class="event-details-empty">${esc(tr('noSpeakersTitle'))}</div>`;
  }

  function renderAll() {
    renderNumbers(); renderHome(); renderSpeakers(); renderEvents(); renderSettings(); renderAI();
    if (state.selectedTargetId) renderSpeakerDrawer();
  }

  const aiState = {client: 'codex'};

  function aiEndpoint() {
    const origin = window.location.origin;
    if (!/^https?:\/\//.test(origin)) return '';
    return `${origin.replace(/\/$/, '')}/mcp`;
  }

  function aiCommand(client = aiState.client) {
    const endpoint = aiEndpoint();
    if (!endpoint) return language === 'zh' ? '请通过 CastFabric 的 HTTP 地址打开控制台' : 'Open the console from the CastFabric HTTP origin';
    if (client === 'claude') return `claude mcp add --transport http castfabric ${endpoint}`;
    if (client === 'generic') return JSON.stringify({
      mcpServers: {castfabric: {type: 'http', url: endpoint}}
    }, null, 2);
    return `codex mcp add castfabric --url ${endpoint}`;
  }

  function aiVerifyPrompt() {
    return language === 'zh'
      ? '连接 CastFabric MCP，先调用 list_outputs 列出所有可输出音响，但不要播放声音。若尚未安装 CastFabric Agent Skill，请从当前仓库的 skills/castfabric 安装；本地文件、实时 PCM 或播放列表优先按 Skill 的说明调用。'
      : 'Connect to the CastFabric MCP and call list_outputs to list every output speaker without playing audio. If the CastFabric Agent Skill is not installed, install it from skills/castfabric in this repository; follow the Skill for local files, live PCM, and playlists.';
  }

  function renderAI() {
    const page = document.getElementById('page-ai');
    if (!page) return;
    const endpoint = aiEndpoint();
    page.querySelector('[data-ai-endpoint]').textContent = endpoint || '—';
    page.querySelector('[data-ai-command]').textContent = aiCommand();
    const label = page.querySelector('[data-ai-command-label]');
    label.textContent = t(aiState.client === 'generic' ? 'configSnippet' : 'runCommand');
    const status = page.querySelector('[data-ai-endpoint-state]');
    const statusKey = state.loading ? 'aiLoading' : state.error || !endpoint ? 'aiUnavailable' : 'aiReady';
    status.textContent = t(statusKey);
    status.classList.toggle('off', statusKey === 'aiUnavailable');
    page.querySelectorAll('[data-copy-target="endpoint"],[data-copy-target="command"]').forEach(button => {
      button.disabled = !endpoint;
    });
  }

  async function copyAIText(kind) {
    const value = kind === 'endpoint' ? aiEndpoint() : kind === 'verify' ? aiVerifyPrompt() : aiCommand();
    let copied = false;
    try {
      await navigator.clipboard.writeText(value);
      copied = true;
    } catch (_error) {
      const input = document.createElement('textarea');
      input.value = value; input.setAttribute('readonly', '');
      input.style.position = 'fixed'; input.style.opacity = '0';
      document.body.appendChild(input); input.select();
      copied = document.execCommand('copy'); input.remove();
    }
    const region = document.querySelector('[data-ai-copy-status]');
    region.textContent = t(copied ? 'copied' : 'copyFailed');
    toast(copied ? 'copied' : 'copyFailed');
  }

  document.querySelectorAll('[data-ai-client]').forEach(tab => {
    tab.addEventListener('click', () => {
      aiState.client = tab.dataset.aiClient;
      document.querySelectorAll('[data-ai-client]').forEach(item => {
        item.setAttribute('aria-selected', String(item === tab));
        item.tabIndex = item === tab ? 0 : -1;
      });
      renderAI();
    });
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...document.querySelectorAll('[data-ai-client]')];
      const destination = event.key === 'Home' ? tabs[0]
        : event.key === 'End' ? tabs[tabs.length - 1]
        : tabs[(tabs.indexOf(tab) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
      destination.focus();
    });
  });
  document.querySelectorAll('[data-copy-target]').forEach(button => button.addEventListener('click', () => copyAIText(button.dataset.copyTarget)));

  async function loadAll({quiet = false} = {}) {
    if (!quiet) {
      state.loading = true; state.error = null;
      setPageState(document.getElementById('page-speakers'), 'loading');
      setPageState(document.getElementById('page-activity'), 'loading');
    }
    try {
      const [system, targets, suites, sessions, events, settings] = await Promise.all([
        api('/api/v1/system'), api('/api/v1/targets'), api('/api/v1/suites'),
        api('/api/v1/sessions'), api('/api/v1/events?limit=100'), api('/api/v1/settings')
      ]);
      Object.assign(state, {system, targets: targets.items, suites: suites.items, sessions: sessions.items, events: events.items, settings, error: null, loading: false});
      document.body.dataset.liveReady = 'true';
      renderAll();
    } catch (error) {
      state.error = error; state.loading = false;
      document.body.dataset.liveReady = 'true';
      renderAll();
      const stack = document.querySelector('#page-home .lane-stack');
      stack.innerHTML = `<div class="error-inline"><span>${esc(tr('healthUnavailable'))}</span><button class="secondary-button" data-live-retry>${esc(language === 'zh' ? '重试' : 'Retry')}</button></div>`;
    }
  }

  async function patchTarget(targetId, body, busyNode) {
    busyNode?.classList.add('is-busy');
    try {
      const result = await api(`/api/v1/targets/${encodeURIComponent(targetId)}`, {method: 'PATCH', body: JSON.stringify(body)});
      toast(result.restart_required ? 'savedRestart' : 'savedLive');
      await loadAll({quiet: true});
      return true;
    } catch (error) {
      toast('actionFailed');
      return false;
    } finally {
      busyNode?.classList.remove('is-busy');
    }
  }

  async function scan() {
    toast('scanningLive');
    try {
      const result = await api('/api/v1/targets/scan', {method: 'POST'});
      state.targets = result.items;
      toast('scanComplete');
      await loadAll({quiet: true});
    } catch (error) { toast('actionFailed'); }
  }

  async function saveSettings() {
    const overlay = document.getElementById('settingsOverlay');
    const toggleValue = selector => overlay.querySelector(selector).getAttribute('aria-pressed') === 'true';
    const payload = {
      identity: {receiver_prefix: overlay.querySelector('[data-field="system.receiver_prefix"]').value},
      playback: {
        follow_device_volume: toggleValue('[data-field="config.follow_device_volume"]'),
        default_volume: Number(overlay.querySelector('[data-field="config.default_volume"]').value),
        auto_resume_on_interrupt: toggleValue('[data-field="config.auto_resume"]'),
        resume_delay_seconds: Number(overlay.querySelector('[data-field="config.resume_delay"]').value),
      },
      network: {
        web_port: Number(overlay.querySelector('[data-field="system.port.web"]').value),
        dlna_port: Number(overlay.querySelector('[data-field="system.port.dlna"]').value),
        miplay_port: Number(overlay.querySelector('[data-field="system.port.miplay"]').value),
      },
      extensions: {xiaomi_enabled: toggleValue('[data-field="system.xiaomi_extension"]')},
      system: {log_level: overlay.querySelector('[data-field="system.log_level"]').selectedIndex === 1 ? 'debug' : 'info'},
    };
    try {
      const result = await api('/api/v1/settings', {method: 'PATCH', body: JSON.stringify(payload)});
      state.settings = result.settings;
      toast(result.restart_required ? 'savedRestart' : 'savedLive');
      closeOverlay();
      await loadAll({quiet: true});
    } catch (error) { toast('actionFailed'); }
  }

  document.addEventListener('click', async event => {
    const retry = event.target.closest('[data-live-retry]');
    if (retry) { event.preventDefault(); await loadAll(); return; }
    const rowToggle = event.target.closest('[data-live-toggle]');
    if (rowToggle) {
      event.preventDefault(); event.stopPropagation();
      const row = rowToggle.closest('.speaker-row');
      const target = targetMap().get(row.dataset.targetId);
      await patchTarget(target.id, {enabled: !target.enabled}, row);
      return;
    }
    const row = event.target.closest('.speaker-row[data-target-id]');
    if (row) { state.selectedTargetId = row.dataset.targetId; renderSpeakerDrawer(); openOverlay('speakerOverlay'); return; }
    const eventRow = event.target.closest('.event-item[data-event-id]');
    if (eventRow) { await openEventDrawer(eventRow.dataset.eventId); return; }
    const enable = event.target.closest('[data-enable-target]');
    if (enable) { event.preventDefault(); await patchTarget(enable.dataset.enableTarget, {enabled: true}, enable.closest('.scan-target')); return; }
  });

  document.addEventListener('click', async event => {
    const saveSpeaker = event.target.closest('[data-save-speaker]');
    const drawerToggle = event.target.closest('[data-live-target-toggle], .danger-zone [data-action="target.toggle"]');
    const saveSettingsButton = event.target.closest('[data-save-settings]');
    const scanButton = event.target.closest('[data-scan-button], [data-action="target.scan"]');
    const diagnostics = event.target.closest('[data-action="diagnostics.export"]');
    const update = event.target.closest('[data-action="system.update"]');
    if (!(saveSpeaker || drawerToggle || saveSettingsButton || scanButton || diagnostics || update)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (saveSpeaker && state.selectedTargetId) {
      const overlay = document.getElementById('speakerOverlay');
      const ok = await patchTarget(state.selectedTargetId, {name: overlay.querySelector('[data-edit-name]').value, receiver_alias: overlay.querySelector('[data-edit-alias]').value}, overlay.querySelector('.drawer'));
      if (ok) closeOverlay();
    } else if (drawerToggle && state.selectedTargetId) {
      const target = targetMap().get(state.selectedTargetId);
      const ok = await patchTarget(target.id, {enabled: !target.enabled}, document.querySelector('#speakerOverlay .drawer'));
      if (ok) closeOverlay();
    } else if (saveSettingsButton) await saveSettings();
    else if (scanButton) await scan();
    else if (diagnostics) window.location.assign('/api/v1/diagnostics/export');
    else if (update) toast('actionFailed');
  }, true);

  document.querySelectorAll('#speakerFilter,#protocolFilter,#resultFilter').forEach(node => node.addEventListener('change', renderEvents));
  document.querySelectorAll('#settingsOverlay .setting-value .suite-toggle').forEach(button => button.addEventListener('click', event => {
    event.preventDefault(); event.stopPropagation();
    event.stopImmediatePropagation();
    button.setAttribute('aria-pressed', String(button.getAttribute('aria-pressed') !== 'true'));
  }, true));

  translations.networkInterface = translations.addressOnly;
  translations.networkInterfaceHelp = ['CastFabric 发布和扫描使用的局域网地址', 'LAN address used for CastFabric advertising and discovery'];
  translations.restartNote = ['部分配置需要重启 CastFabric 后才会生效；重启会中断当前声路。', 'Some settings require a CastFabric restart, which interrupts active routes.'];
  renderAI();
  translate();
  localStorage.getItem('castfabric.language') === 'en' && applyLanguage('en');
  document.getElementById('languageButton').addEventListener('click', () => localStorage.setItem('castfabric.language', language));
  document.querySelector('[data-field="system.language"]').addEventListener('change', () => localStorage.setItem('castfabric.language', language));
  new MutationObserver(() => renderAll()).observe(document.documentElement, {attributes: true, attributeFilter: ['lang']});

  loadAll();
  window.setInterval(() => { if (!document.hidden && !document.querySelector('.overlay.open')) loadAll({quiet: true}); }, 5000);
})();
