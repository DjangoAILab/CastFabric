/* CastFabric Runtime v2 console. All rendered values come from /api/v1. */
(() => {
  'use strict';

  const state = {
    system: null,
    targets: [],
    suites: [],
    sessions: [],
    events: [],
    playlists: [],
    assets: [],
    playbackHistory: [],
    playlistRuns: [],
    selectedPlaylistId: null,
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

  const contentCopy = {
    title: ['播放内容', 'Content'], intro: ['整理可复用音频，组成播放列表，再投到任意一台音响。', 'Organize reusable audio into playlists, then play it on any speaker.'],
    playlists: ['播放列表', 'Playlists'], assets: ['音频资源', 'Audio resources'], history: ['播放记录', 'Playback record'],
    historyNote: ['这里只记录已经发生的播放，不提供“继续播放”。需要续播时，请回到对应播放列表选择明确的位置。', 'This is a factual playback record, not a resume queue. To resume, return to the playlist and choose an explicit position.'],
    newPlaylist: ['新建播放列表', 'New playlist'], upload: ['上传', 'Upload'], addUrl: ['添加 URL', 'Add URL'],
    allSources: ['全部来源', 'All sources'], uploadedFile: ['上传文件', 'Uploaded file'], externalUrl: ['外部 URL', 'External URL'],
    retry: ['重试', 'Retry'],
  };
  const ct = key => contentCopy[key]?.[language === 'zh' ? 0 : 1] || key;
  const playIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 9 6-9 6Z"/></svg>';
  const editIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 20 4.2-1 10.5-10.5-3.2-3.2L5 15.8 4 20Z"/><path d="m13.8 7 3.2 3.2"/></svg>';

  function formatDuration(value) {
    if (value === null || value === undefined) return '—';
    const seconds = Math.max(0, Math.floor(Number(value)));
    const minutes = Math.floor(seconds / 60);
    return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
  }

  function applyContentLanguage() {
    document.querySelectorAll('[data-content-copy]').forEach(node => {
      node.textContent = ct(node.dataset.contentCopy);
    });
    document.querySelector('[data-playlist-search]')?.setAttribute('placeholder', language === 'zh' ? '搜索播放列表' : 'Search playlists');
    document.querySelector('[data-asset-search]')?.setAttribute('placeholder', language === 'zh' ? '搜索名称、说明、标签或原文件名' : 'Search name, notes, tags, or filename');
    document.querySelector('.content-tabs')?.setAttribute('aria-label', language === 'zh' ? '内容分类' : 'Content sections');
  }

  function selectedPlaylist() {
    return state.playlists.find(item => item.id === state.selectedPlaylistId) || state.playlists[0] || null;
  }

  function renderContent() {
    applyContentLanguage();
    const stateNode = document.querySelector('[data-content-state]');
    const views = document.querySelectorAll('[data-content-view]');
    if (state.loading || state.error) {
      views.forEach(node => { node.hidden = true; });
      stateNode.hidden = false; stateNode.style.display = 'grid';
      stateNode.querySelector('strong').textContent = state.error ? (language === 'zh' ? '内容存储暂时不可用' : 'Content storage is unavailable') : (language === 'zh' ? '正在读取内容' : 'Loading content');
      stateNode.querySelector('p').textContent = state.error ? (language === 'zh' ? '没有开始新的播放；请检查服务后重试。' : 'No new playback was started. Check the service and retry.') : (language === 'zh' ? '播放列表、音频资源和记录正在载入。' : 'Loading playlists, audio resources, and records.');
      stateNode.querySelector('button').hidden = !state.error;
      return;
    }
    views.forEach(node => { node.hidden = false; });
    stateNode.hidden = true; stateNode.style.display = '';
    const list = document.querySelector('[data-playlist-list]');
    const detail = document.querySelector('[data-playlist-detail]');
    if (!list || !detail) return;
    if (!state.selectedPlaylistId && state.playlists[0]) state.selectedPlaylistId = state.playlists[0].id;
    const term = (document.querySelector('[data-playlist-search]')?.value || '').trim().toLowerCase();
    const visiblePlaylists = state.playlists.filter(item => item.name.toLowerCase().includes(term));
    list.innerHTML = visiblePlaylists.map(item => `<button class="playlist-pick ${item.id === state.selectedPlaylistId ? 'active' : ''}" data-select-playlist="${esc(item.id)}"><i class="playlist-disc"></i><span><strong>${esc(item.name)}</strong><span>${item.item_count} ${language === 'zh' ? '项' : 'items'} · ${formatDuration(item.total_duration_seconds)}</span></span></button>`).join('') || `<div class="content-empty"><p>${language === 'zh' ? '没有匹配的播放列表' : 'No matching playlists'}</p></div>`;
    const playlist = selectedPlaylist();
    if (!playlist) {
      detail.innerHTML = `<div class="content-empty"><div><strong>${language === 'zh' ? '从一张播放列表开始' : 'Start with a playlist'}</strong><p>${language === 'zh' ? '把以后还会用到的音频编排在一起；单次播放不需要建列表。' : 'Arrange reusable audio together. One-off playback does not need a playlist.'}</p><button class="primary-button" data-content-action="create-playlist">${ct('newPlaylist')}</button></div></div>`;
    } else {
      const run = state.playlistRuns.find(item => item.playlist_id === playlist.id);
      const tracks = playlist.items.map((item, index) => `<div class="track-row ${item.asset_status !== 'available' ? 'unavailable' : ''}"><span class="track-number">${String(index + 1).padStart(2, '0')}</span><div class="track-title"><strong>${esc(item.title)}</strong><span>${esc(item.source_kind === 'managed_file' ? (language === 'zh' ? '已上传' : 'Uploaded') : 'URL')}</span></div><span class="track-meta">${esc(item.source_kind === 'managed_file' ? (language === 'zh' ? '上传文件' : 'File') : 'External URL')}</span><span class="track-meta">${formatDuration(item.duration_seconds)}</span><div class="resource-actions"><button class="icon-action" data-play-playlist="${esc(playlist.id)}" data-start-item="${esc(item.id)}" ${item.asset_status !== 'available' ? 'disabled' : ''} aria-label="${language === 'zh' ? '从此项播放' : 'Play from item'}">${playIcon}</button><button class="icon-action" data-edit-item="${esc(item.id)}" aria-label="${language === 'zh' ? '编辑项目' : 'Edit item'}">${editIcon}</button></div></div>`).join('');
      detail.innerHTML = `<header class="playlist-hero"><div><p class="eyebrow">PLAYLIST</p><h2>${esc(playlist.name)}</h2><p>${playlist.item_count} ${language === 'zh' ? '项' : 'items'} · ${formatDuration(playlist.total_duration_seconds)} · ${playlist.default_order === 'random' ? (language === 'zh' ? '随机' : 'Random') : (language === 'zh' ? '顺序' : 'Sequential')}</p></div><div class="playlist-actions"><button class="secondary-button" data-edit-playlist="${esc(playlist.id)}">${editIcon}${language === 'zh' ? '编辑' : 'Edit'}</button><button class="primary-button" data-play-playlist="${esc(playlist.id)}" ${playlist.item_count ? '' : 'disabled'}>${playIcon}${language === 'zh' ? '全部播放' : 'Play all'}</button></div></header><div class="playlist-section-head"><h3>${language === 'zh' ? '内容' : 'Items'}</h3><span>${language === 'zh' ? '选择任意一项即可从这里开始' : 'Choose any item to start there'}</span></div><div class="track-list">${tracks || `<div class="content-empty"><div><strong>${language === 'zh' ? '列表还是空的' : 'This playlist is empty'}</strong><p>${language === 'zh' ? '从已有音频资源中添加内容。' : 'Add from existing audio resources.'}</p></div></div>`}</div><div style="margin-top:12px"><button class="secondary-button" data-add-playlist-content="${esc(playlist.id)}">${language === 'zh' ? '＋ 添加内容' : '+ Add content'}</button></div>${run ? renderRunStrip(run, playlist) : ''}`;
    }
    renderAssets();
    renderPlaybackHistory();
  }

  function renderRunStrip(run, playlist) {
    const target = targetMap().get(run.target_id);
    return `<div class="run-strip"><div><strong>${esc(target?.name || run.target_id)} · ${esc(run.current_item?.title || '')}</strong><span>${esc(playlist.name)} · ${formatDuration(run.position_seconds)} / ${formatDuration(run.duration_seconds)} · ${esc(stateLabel(run.session_state))}</span></div><div class="run-controls"><button data-run-control="${esc(run.run_id)}" data-run-action="previous">${language === 'zh' ? '上一项' : 'Previous'}</button><button data-run-control="${esc(run.run_id)}" data-run-action="${run.session_state === 'paused' ? 'resume' : 'pause'}">${run.session_state === 'paused' ? (language === 'zh' ? '继续' : 'Resume') : (language === 'zh' ? '暂停' : 'Pause')}</button><button data-run-control="${esc(run.run_id)}" data-run-action="next">${language === 'zh' ? '下一项' : 'Next'}</button><button data-run-control="${esc(run.run_id)}" data-run-action="stop">${language === 'zh' ? '停止' : 'Stop'}</button></div></div>`;
  }

  function renderAssets() {
    const list = document.querySelector('[data-asset-list]');
    if (!list) return;
    const term = (document.querySelector('[data-asset-search]')?.value || '').trim().toLowerCase();
    const source = document.querySelector('[data-asset-source]')?.value || '';
    const items = state.assets.filter(item => (!source || item.source_kind === source) && (!term || [item.display_name, item.description, item.original_filename, ...(item.tags || [])].join(' ').toLowerCase().includes(term)));
    list.innerHTML = items.map(item => `<article class="resource-row"><div class="resource-identity"><i class="resource-glyph"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V5l10-2v13M9 9l10-2M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm10-2a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/></svg></i><div><strong>${esc(item.display_name)}</strong><span>${esc(item.description || item.original_filename || item.source_summary)}</span></div></div><span class="resource-cell">${item.source_kind === 'managed_file' ? (language === 'zh' ? '上传文件' : 'File') : 'URL'}</span><span class="resource-cell">${formatDuration(item.duration_seconds)}</span><span class="resource-cell">${item.reference_count} Playlist</span><div class="resource-actions"><button class="icon-action" data-play-asset="${esc(item.id)}" ${item.status !== 'available' ? 'disabled' : ''} aria-label="${language === 'zh' ? '播放' : 'Play'}">${playIcon}</button><button class="icon-action" data-edit-asset="${esc(item.id)}" aria-label="${language === 'zh' ? '编辑' : 'Edit'}">${editIcon}</button></div></article>`).join('') || `<div class="content-empty"><div><strong>${language === 'zh' ? '没有匹配的音频' : 'No matching audio'}</strong><p>${language === 'zh' ? '可以上传文件或添加一个外部 URL。' : 'Upload a file or add an external URL.'}</p></div></div>`;
  }

  function renderPlaybackHistory() {
    const list = document.querySelector('[data-playback-history]');
    if (!list) return;
    list.innerHTML = state.playbackHistory.map(item => {
      const playlist = state.playlists.find(value => value.id === item.playlist_id);
      const target = targetMap().get(item.target_id);
      const reasons = {completed: ['已完成', 'Completed'], stopped: ['手动停止', 'Stopped'], skipped: ['已跳过', 'Skipped'], failed: ['失败', 'Failed'], preempted: ['被替换', 'Preempted'], interrupted: ['已中断', 'Interrupted']};
      const result = item.end_reason ? (reasons[item.end_reason]?.[language === 'zh' ? 0 : 1] || item.end_reason) : stateLabel(item.state);
      return `<article class="history-record"><time>${esc(formatTime(item.started_at))}</time><div><strong>${esc(playlist?.name || item.item_title_snapshot || (language === 'zh' ? '单个音频' : 'Single audio'))}</strong><span>${esc(item.item_title_snapshot || item.source_label || '—')} · ${formatDuration(item.position_seconds)} / ${formatDuration(item.duration_seconds)}</span></div><div><strong>${esc(target?.name || item.target_id)}</strong><span>${esc(item.source_type)}</span></div><span class="status-chip ${item.end_reason === 'failed' ? 'warn' : ''}">${esc(result)}</span></article>`;
    }).join('') || `<div class="content-empty"><div><strong>${language === 'zh' ? '还没有播放记录' : 'No playback record yet'}</strong><p>${language === 'zh' ? '播放发生后，这里会保留结果和最后位置。' : 'Completed playback facts and final positions will appear here.'}</p></div></div>`;
  }

  function modal(title, copy, body, actions = '') {
    const overlay = document.getElementById('contentModal');
    overlay.querySelector('[data-content-modal-title]').textContent = title;
    overlay.querySelector('[data-content-modal-copy]').textContent = copy || '';
    overlay.querySelector('[data-content-modal-body]').innerHTML = body;
    overlay.querySelector('[data-content-modal-actions]').innerHTML = actions;
    openOverlay('contentModal');
    return overlay;
  }

  async function reloadContent() {
    const [playlists, assets, history, runs] = await Promise.all([
      api('/api/v1/playlists'), api('/api/v1/media/assets?limit=200'),
      api('/api/v1/playback/history?limit=100'), api('/api/v1/playlist-runs'),
    ]);
    state.playlists = playlists.items; state.assets = assets.items;
    state.playbackHistory = history.items; state.playlistRuns = runs.items;
    if (!state.playlists.some(item => item.id === state.selectedPlaylistId)) state.selectedPlaylistId = state.playlists[0]?.id || null;
    renderContent();
  }

  let contentIntent = null;
  let conflictResolver = null;

  function formValue(name) {
    return document.querySelector(`#contentModal [name="${name}"]`)?.value ?? '';
  }

  function formHtml(fields) {
    return `<form id="contentForm" class="content-form" data-content-form novalidate>${fields}</form>`;
  }

  function field(label, name, value = '', type = 'text') {
    return `<label>${esc(label)}<input type="${type}" name="${name}" value="${esc(value)}" ${name === 'name' ? 'required maxlength="200" aria-describedby="playlistNameError"' : ''}>${name === 'name' ? '<span id="playlistNameError" class="field-error" hidden></span>' : ''}</label>`;
  }

  function dialogButtons(primary, action, extra = '') {
    return `${extra}<button class="secondary-button" data-content-cancel>${language === 'zh' ? '取消' : 'Cancel'}</button><button class="primary-button" type="submit" form="contentForm" data-content-modal-action="${action}">${esc(primary)}</button>`;
  }

  function openPlaylistForm(playlist = null) {
    contentIntent = {kind: playlist ? 'edit-playlist' : 'create-playlist', playlist};
    modal(
      playlist ? (language === 'zh' ? '编辑播放列表' : 'Edit playlist') : ct('newPlaylist'),
      language === 'zh' ? '名称与默认播放方式会用于下一次启动。' : 'Name and playback defaults apply to the next run.',
      formHtml(`${field(language === 'zh' ? '名称' : 'Name', 'name', playlist?.name || '')}<label>${language === 'zh' ? '说明（可选）' : 'Description (optional)'}<textarea name="description">${esc(playlist?.description || '')}</textarea></label><div class="content-form-pair"><label>${language === 'zh' ? '默认顺序' : 'Default order'}<select name="default_order"><option value="sequential" ${playlist?.default_order !== 'random' ? 'selected' : ''}>${language === 'zh' ? '顺序播放' : 'Sequential'}</option><option value="random" ${playlist?.default_order === 'random' ? 'selected' : ''}>${language === 'zh' ? '随机播放' : 'Random'}</option></select></label><label>${language === 'zh' ? '播放结束' : 'At the end'}<select name="default_repeat"><option value="none" ${playlist?.default_repeat !== 'all' ? 'selected' : ''}>${language === 'zh' ? '停止' : 'Stop'}</option><option value="all" ${playlist?.default_repeat === 'all' ? 'selected' : ''}>${language === 'zh' ? '列表循环' : 'Repeat all'}</option></select></label></div>`),
      dialogButtons(playlist ? (language === 'zh' ? '保存更改' : 'Save changes') : (language === 'zh' ? '创建播放列表' : 'Create playlist'), 'save-playlist'),
    );
  }

  function openUrlForm() {
    contentIntent = {kind: 'add-url'};
    modal(ct('addUrl'), language === 'zh' ? '保存显示名称与外部地址；列表中不会暴露 URL 参数。' : 'Save a display name and external address. URL parameters stay private.', formHtml(`${field(language === 'zh' ? '显示名称' : 'Display name', 'display_name')}${field('URL', 'url', '', 'url')}<label>${language === 'zh' ? '说明' : 'Description'}<textarea name="description"></textarea></label>${field(language === 'zh' ? '标签（逗号分隔）' : 'Tags (comma separated)', 'tags')}`), dialogButtons(language === 'zh' ? '添加资源' : 'Add asset', 'save-url'));
  }

  function openUploadForm() {
    contentIntent = {kind: 'upload'};
    modal(language === 'zh' ? '上传音频' : 'Upload audio', language === 'zh' ? '原文件名用于追溯；你可以另设系统内显示名称。' : 'The original filename is retained; choose a separate display name.', formHtml(`<label>${language === 'zh' ? '音频文件' : 'Audio file'}<input type="file" name="file" accept="audio/*"></label>${field(language === 'zh' ? '显示名称（可选）' : 'Display name (optional)', 'display_name')}`), dialogButtons(language === 'zh' ? '上传并保存' : 'Upload and save', 'save-upload'));
  }

  function openAssetForm(asset) {
    contentIntent = {kind: 'edit-asset', asset};
    const remove = asset.reference_count ? '' : `<button class="secondary-button" data-content-modal-action="delete-asset">${language === 'zh' ? '删除资源' : 'Delete asset'}</button>`;
    modal(language === 'zh' ? '编辑音频资源' : 'Edit audio resource', asset.source_kind === 'managed_file' ? (language === 'zh' ? `原文件：${asset.original_filename || '—'}` : `Original file: ${asset.original_filename || '—'}`) : asset.source_summary, formHtml(`${field(language === 'zh' ? '显示名称' : 'Display name', 'display_name', asset.display_name)}<label>${language === 'zh' ? '说明' : 'Description'}<textarea name="description">${esc(asset.description || '')}</textarea></label>${field(language === 'zh' ? '标签（逗号分隔）' : 'Tags (comma separated)', 'tags', (asset.tags || []).join(', '))}`), dialogButtons(language === 'zh' ? '保存更改' : 'Save changes', 'save-asset', remove));
  }

  function openAssetPicker(playlist) {
    const available = state.assets.filter(item => item.status === 'available');
    contentIntent = {kind: 'add-content', playlist, assetId: available[0]?.id || null};
    modal(language === 'zh' ? '选择音频资源' : 'Choose audio resources', language === 'zh' ? '搜索并选择一项；上传和 URL 在“音频资源”页管理。' : 'Search and select one item. Uploads and URLs are managed under Audio resources.', `<label class="content-search"><svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 4 4"/></svg><input data-picker-search placeholder="${language === 'zh' ? '搜索音频资源' : 'Search audio'}"></label><div class="asset-options" style="margin-top:10px">${available.map((item, index) => `<button class="choice-row ${index === 0 ? 'selected' : ''}" data-picker-asset="${esc(item.id)}"><i></i><span><strong>${esc(item.display_name)}</strong><span>${esc(item.source_kind === 'managed_file' ? (item.original_filename || 'Uploaded') : item.source_summary)}</span></span><span>${formatDuration(item.duration_seconds)}</span></button>`).join('')}</div>`, dialogButtons(language === 'zh' ? '添加到列表' : 'Add to playlist', 'confirm-add-content'));
  }

  function openItemForm(playlist, item) {
    contentIntent = {kind: 'edit-item', playlist, item};
    const index = playlist.items.findIndex(value => value.id === item.id);
    const extra = `<button class="secondary-button" data-content-modal-action="move-up" ${index === 0 ? 'disabled' : ''}>${language === 'zh' ? '上移' : 'Move up'}</button><button class="secondary-button" data-content-modal-action="move-down" ${index === playlist.items.length - 1 ? 'disabled' : ''}>${language === 'zh' ? '下移' : 'Move down'}</button><button class="secondary-button" data-content-modal-action="remove-item">${language === 'zh' ? '移除' : 'Remove'}</button>`;
    modal(language === 'zh' ? '编辑列表项' : 'Edit playlist item', language === 'zh' ? '标题只影响这张播放列表，不会修改音频资源名称。' : 'This title only affects this playlist.', formHtml(field(language === 'zh' ? '列表内标题' : 'Playlist title', 'title', item.title_override || '')), dialogButtons(language === 'zh' ? '保存' : 'Save', 'save-item', extra));
  }

  function openOutputPicker(intent) {
    const targets = state.targets.filter(item => item.enabled);
    contentIntent = {...intent, targetId: targets[0]?.id || null};
    if (!targets.length) {
      modal(language === 'zh' ? '还没有可用的音响' : 'No enabled speakers',
        language === 'zh' ? '请先在“音响”页面添加并启用一台音响。内容已保存，不会开始播放。' : 'Add and enable a speaker on the Speakers page first. Your content is saved; playback has not started.',
        '', `<button class="secondary-button" data-content-cancel>${language === 'zh' ? '关闭' : 'Close'}</button>`);
      return;
    }
    modal(language === 'zh' ? '播放到哪台音响？' : 'Choose a speaker', language === 'zh' ? '开始后由 CastFabric 服务端继续播放。' : 'CastFabric continues playback on the server.', `<div class="output-options">${targets.map((target, index) => `<button class="choice-row ${index === 0 ? 'selected' : ''}" data-picker-target="${esc(target.id)}"><i></i><span><strong>${esc(target.name)}</strong><span>${esc(target.online === false ? (language === 'zh' ? '本次扫描离线' : 'Offline in latest scan') : (language === 'zh' ? '已启用' : 'Enabled'))}</span></span><span>${target.online === false ? (language === 'zh' ? '离线' : 'Offline') : (language === 'zh' ? '就绪' : 'Ready')}</span></button>`).join('')}</div>`, dialogButtons(language === 'zh' ? '播放' : 'Play', 'confirm-play'));
  }

  function chooseConflict(error) {
    return new Promise(resolve => {
      conflictResolver = resolve;
      const runs = error.payload?.error?.details?.affected_runs || [];
      modal(language === 'zh' ? '内容正在播放' : 'Content is playing', language === 'zh' ? `这次更改会影响 ${runs.length} 个正在播放的会话，请选择一次处理方式。` : `This change affects ${runs.length} active run(s). Choose one resolution.`, `<div class="output-options"><button class="choice-row" data-conflict-resolution="keep"><i></i><span><strong>${language === 'zh' ? '保留当前声音' : 'Keep current audio'}</strong><span>${language === 'zh' ? '播完后使用新定义' : 'Use the new definition after it ends'}</span></span></button><button class="choice-row" data-conflict-resolution="reload"><i></i><span><strong>${language === 'zh' ? '立即重新加载' : 'Reload now'}</strong><span>${language === 'zh' ? '切到更新后的内容' : 'Switch to the updated content'}</span></span></button><button class="choice-row" data-conflict-resolution="stop"><i></i><span><strong>${language === 'zh' ? '停止相关播放' : 'Stop affected playback'}</strong><span>${language === 'zh' ? '保存后不再发声' : 'Save without further audio'}</span></span></button></div>`, `<button class="secondary-button" data-content-cancel>${language === 'zh' ? '取消' : 'Cancel'}</button>`);
    });
  }

  async function requestWithConflict(path, options) {
    try { return await api(path, options); }
    catch (error) {
      if (error.payload?.error?.details?.reason !== 'ACTIVE_PLAYBACK_CONFLICT') throw error;
      const resolution = await chooseConflict(error);
      if (!resolution) throw error;
      const separator = path.includes('?') ? '&' : '?';
      if (options.method === 'DELETE') return api(`${path}${separator}resolution=${resolution}`, options);
      const payload = JSON.parse(options.body || '{}'); payload.resolution = resolution;
      return api(path, {...options, body: JSON.stringify(payload)});
    }
  }

  async function reorderItem(direction) {
    const {playlist, item} = contentIntent;
    const ids = playlist.items.map(value => value.id);
    const from = ids.indexOf(item.id), to = from + (direction === 'move-up' ? -1 : 1);
    if (to < 0 || to >= ids.length) return;
    [ids[from], ids[to]] = [ids[to], ids[from]];
    await api(`/api/v1/playlists/${encodeURIComponent(playlist.id)}/items`, {method: 'PUT', body: JSON.stringify({expected_revision: playlist.revision, item_ids: ids})});
    closeOverlay(); await reloadContent();
  }

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
      'activity.agent_output_started': ['实体音响已开始拉取音频', 'Speaker started pulling Agent audio'],
      'activity.agent_pcm_forwarded': ['实时音频已送入实体输出', 'Live Agent audio reached the physical output'],
      'activity.agent_output_failed': ['Agent 实体输出未建立', 'Agent physical output was not established'],
      'activity.agent_output_stopped': ['Agent 实体输出已停止', 'Agent physical output stopped'],
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
    renderNumbers(); renderHome(); renderSpeakers(); renderContent(); renderEvents(); renderSettings(); renderAI();
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
      ? '连接 CastFabric MCP，先调用 list_outputs 列出所有可输出音响，但不要播放声音。若尚未安装 CastFabric Agent Skill，请从 github.com/DjangoAILab/CastFabric 的 skills/castfabric 安装；本地文件、实时 PCM 或播放列表优先按 Skill 的说明调用。'
      : 'Connect to the CastFabric MCP and call list_outputs to list every output speaker without playing audio. If the CastFabric Agent Skill is not installed, install skills/castfabric from github.com/DjangoAILab/CastFabric; follow the Skill for local files, live PCM, and playlists.';
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
      const [system, targets, suites, sessions, events, settings, playlists, assets, history, runs] = await Promise.all([
        api('/api/v1/system'), api('/api/v1/targets'), api('/api/v1/suites'),
        api('/api/v1/sessions'), api('/api/v1/events?limit=100'), api('/api/v1/settings'),
        api('/api/v1/playlists'), api('/api/v1/media/assets?limit=200'),
        api('/api/v1/playback/history?limit=100'), api('/api/v1/playlist-runs')
      ]);
      Object.assign(state, {system, targets: targets.items, suites: suites.items, sessions: sessions.items, events: events.items, settings, playlists: playlists.items, assets: assets.items, playbackHistory: history.items, playlistRuns: runs.items, error: null, loading: false});
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

  document.addEventListener('input', event => {
    if (event.target.matches('#contentModal [name="name"]')) {
      event.target.removeAttribute('aria-invalid');
      document.getElementById('playlistNameError').hidden = true;
    }
    if (event.target.matches('[data-playlist-search]')) renderContent();
    if (event.target.matches('[data-asset-search]')) renderAssets();
    if (event.target.matches('[data-picker-search]')) {
      const term = event.target.value.trim().toLowerCase();
      document.querySelectorAll('[data-picker-asset]').forEach(row => {
        row.hidden = !row.textContent.toLowerCase().includes(term);
      });
    }
  });
  document.querySelector('[data-asset-source]')?.addEventListener('change', renderAssets);

  document.addEventListener('click', async event => {
    const tab = event.target.closest('[data-content-tab]');
    const selectPlaylist = event.target.closest('[data-select-playlist]');
    const action = event.target.closest('[data-content-action]');
    const playPlaylist = event.target.closest('[data-play-playlist]');
    const playAsset = event.target.closest('[data-play-asset]');
    const editPlaylist = event.target.closest('[data-edit-playlist]');
    const editAsset = event.target.closest('[data-edit-asset]');
    const addContent = event.target.closest('[data-add-playlist-content]');
    const editItem = event.target.closest('[data-edit-item]');
    const runControl = event.target.closest('[data-run-control]');
    const pickerTarget = event.target.closest('[data-picker-target]');
    const pickerAsset = event.target.closest('[data-picker-asset]');
    const modalAction = event.target.closest('[data-content-modal-action]');
    const cancel = event.target.closest('[data-content-cancel]');
    const conflict = event.target.closest('[data-conflict-resolution]');
    if (!(tab || selectPlaylist || action || playPlaylist || playAsset || editPlaylist || editAsset || addContent || editItem || runControl || pickerTarget || pickerAsset || modalAction || cancel || conflict)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      if (tab) {
        document.querySelectorAll('[data-content-tab]').forEach(node => node.classList.toggle('active', node === tab));
        document.querySelectorAll('[data-content-view]').forEach(node => node.classList.toggle('active', node.dataset.contentView === tab.dataset.contentTab));
      } else if (selectPlaylist) {
        state.selectedPlaylistId = selectPlaylist.dataset.selectPlaylist; renderContent();
      } else if (action?.dataset.contentAction === 'create-playlist') openPlaylistForm();
      else if (action?.dataset.contentAction === 'add-url') openUrlForm();
      else if (action?.dataset.contentAction === 'upload-asset') openUploadForm();
      else if (editPlaylist) openPlaylistForm(state.playlists.find(item => item.id === editPlaylist.dataset.editPlaylist));
      else if (editAsset) openAssetForm(state.assets.find(item => item.id === editAsset.dataset.editAsset));
      else if (addContent) openAssetPicker(state.playlists.find(item => item.id === addContent.dataset.addPlaylistContent));
      else if (editItem) {
        const playlist = selectedPlaylist();
        openItemForm(playlist, playlist.items.find(item => item.id === editItem.dataset.editItem));
      } else if (playPlaylist) {
        openOutputPicker({kind: 'play-playlist', playlistId: playPlaylist.dataset.playPlaylist, startItemId: playPlaylist.dataset.startItem || null});
      } else if (playAsset) openOutputPicker({kind: 'play-asset', assetId: playAsset.dataset.playAsset});
      else if (runControl) {
        const run = state.playlistRuns.find(item => item.run_id === runControl.dataset.runControl);
        await api(`/api/v1/playlist-runs/${encodeURIComponent(run.run_id)}/control`, {method: 'POST', body: JSON.stringify({action: runControl.dataset.runAction, if_session_id: run.session_id})});
        await reloadContent();
      } else if (pickerTarget) {
        contentIntent.targetId = pickerTarget.dataset.pickerTarget;
        document.querySelectorAll('[data-picker-target]').forEach(node => node.classList.toggle('selected', node === pickerTarget));
      } else if (pickerAsset) {
        contentIntent.assetId = pickerAsset.dataset.pickerAsset;
        document.querySelectorAll('[data-picker-asset]').forEach(node => node.classList.toggle('selected', node === pickerAsset));
      } else if (conflict) {
        const resolve = conflictResolver; conflictResolver = null; closeOverlay(); resolve?.(conflict.dataset.conflictResolution);
      } else if (cancel) {
        const resolve = conflictResolver; conflictResolver = null; closeOverlay(); resolve?.(null);
      } else if (modalAction) {
        const operation = modalAction.dataset.contentModalAction;
        modalAction.disabled = true;
        if (operation === 'save-playlist') {
          if (!formValue('name').trim()) {
            const input = document.querySelector('#contentModal [name="name"]');
            const error = document.getElementById('playlistNameError');
            error.textContent = language === 'zh' ? '请填写播放列表名称。' : 'Enter a playlist name.';
            error.hidden = false; input.setAttribute('aria-invalid', 'true'); input.focus();
            modalAction.disabled = false;
            return;
          }
          const payload = {name: formValue('name'), description: formValue('description'), default_order: formValue('default_order'), default_repeat: formValue('default_repeat')};
          if (contentIntent.playlist) {
            payload.expected_revision = contentIntent.playlist.revision;
            await api(`/api/v1/playlists/${encodeURIComponent(contentIntent.playlist.id)}`, {method: 'PATCH', body: JSON.stringify(payload)});
          } else {
            const created = await api('/api/v1/playlists', {method: 'POST', body: JSON.stringify(payload)});
            state.selectedPlaylistId = created.item.id;
          }
          closeOverlay(); await reloadContent();
        } else if (operation === 'save-url') {
          await api('/api/v1/media/assets/url', {method: 'POST', body: JSON.stringify({url: formValue('url'), display_name: formValue('display_name'), description: formValue('description'), tags: formValue('tags').split(',').map(value => value.trim()).filter(Boolean)})});
          closeOverlay(); await reloadContent();
        } else if (operation === 'save-upload') {
          const file = document.querySelector('#contentModal [name="file"]').files[0];
          if (!file) throw new Error('FILE_REQUIRED');
          const ticket = await api('/api/v1/media/uploads', {method: 'POST', body: JSON.stringify({filename: file.name, content_type: file.type || 'application/octet-stream', size_bytes: file.size, display_name: formValue('display_name') || file.name})});
          const response = await fetch(ticket.upload_path, {method: 'PUT', headers: {'Content-Type': 'application/octet-stream'}, body: file});
          if (!response.ok) throw new Error(`HTTP_${response.status}`);
          closeOverlay(); await reloadContent();
        } else if (operation === 'save-asset') {
          await api(`/api/v1/media/assets/${encodeURIComponent(contentIntent.asset.id)}`, {method: 'PATCH', body: JSON.stringify({display_name: formValue('display_name'), description: formValue('description'), tags: formValue('tags').split(',').map(value => value.trim()).filter(Boolean)})});
          closeOverlay(); await reloadContent();
        } else if (operation === 'delete-asset') {
          await api(`/api/v1/media/assets/${encodeURIComponent(contentIntent.asset.id)}`, {method: 'DELETE'});
          closeOverlay(); await reloadContent();
        } else if (operation === 'confirm-add-content') {
          await api(`/api/v1/playlists/${encodeURIComponent(contentIntent.playlist.id)}/items`, {method: 'POST', body: JSON.stringify({asset_id: contentIntent.assetId, expected_revision: contentIntent.playlist.revision})});
          closeOverlay(); await reloadContent();
        } else if (operation === 'save-item') {
          await requestWithConflict(`/api/v1/playlists/${encodeURIComponent(contentIntent.playlist.id)}/items/${encodeURIComponent(contentIntent.item.id)}`, {method: 'PATCH', body: JSON.stringify({expected_revision: contentIntent.playlist.revision, title: formValue('title')})});
          closeOverlay(); await reloadContent();
        } else if (operation === 'remove-item') {
          await requestWithConflict(`/api/v1/playlists/${encodeURIComponent(contentIntent.playlist.id)}/items/${encodeURIComponent(contentIntent.item.id)}?expected_revision=${contentIntent.playlist.revision}`, {method: 'DELETE'});
          closeOverlay(); await reloadContent();
        } else if (operation === 'move-up' || operation === 'move-down') await reorderItem(operation);
        else if (operation === 'confirm-play') {
          if (!contentIntent.targetId) throw new Error('TARGET_REQUIRED');
          if (contentIntent.kind === 'play-playlist') {
            await api('/api/v1/playlist-runs', {method: 'POST', body: JSON.stringify({playlist_id: contentIntent.playlistId, target_id: contentIntent.targetId, ...(contentIntent.startItemId ? {start_item_id: contentIntent.startItemId} : {})})});
          } else {
            await api(`/api/v1/media/assets/${encodeURIComponent(contentIntent.assetId)}/play`, {method: 'POST', body: JSON.stringify({target_id: contentIntent.targetId})});
          }
          closeOverlay(); await loadAll({quiet: true});
        }
      }
    } catch (error) {
      const body = document.querySelector('[data-content-modal-body]');
      if (body && document.getElementById('contentModal').classList.contains('open')) {
        body.querySelector('[data-modal-error]')?.remove();
        body.insertAdjacentHTML('afterbegin', `<div class="dialog-error" role="alert" data-modal-error>${language === 'zh' ? '操作未完成，填写内容已保留，请检查后重试。' : 'Could not complete the action. Your entries are preserved; please check and retry.'} <span>${esc(error.payload?.error?.details?.reason || error.message || '')}</span></div>`);
        body.scrollTop = 0;
      }
      else toast('actionFailed');
      if (modalAction) modalAction.disabled = false;
    }
  }, true);

  document.addEventListener('click', async event => {
    const retry = event.target.closest('[data-live-retry],[data-content-retry]');
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
  document.addEventListener('submit', event => {
    if (!event.target.matches('[data-content-form]')) return;
    event.preventDefault();
    document.querySelector('#contentModal .primary-button[data-content-modal-action]')?.click();
  });
  new MutationObserver(() => renderAll()).observe(document.documentElement, {attributes: true, attributeFilter: ['lang']});

  loadAll();
  window.setInterval(() => { if (!document.hidden && !document.querySelector('.overlay.open')) loadAll({quiet: true}); }, 5000);
})();
