/**
 * Auto Music Player — Admin Dashboard
 * Single-file vanilla JS SPA
 */

const API = window.__API_BASE__ || '';

// ─── Auth ────────────────────────────────────────────────────────────────────
const token = localStorage.getItem('amp_token');
if (!token) window.location.href = 'login.html';

const authHeaders = () => ({
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${token}`,
});

async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: { ...authHeaders(), ...(opts.headers || {}) },
  });
  if (res.status === 401) {
    localStorage.removeItem('amp_token');
    window.location.href = 'login.html';
    return;
  }
  return res;
}

// ─── Toast ───────────────────────────────────────────────────────────────────
function toast(msg, type = 'info', duration = 3000) {
  const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icons[type] || ''}</span><span>${msg}</span>`;
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ─── Confirm modal ───────────────────────────────────────────────────────────
function confirm(title, message) {
  return new Promise(resolve => {
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmMessage').textContent = message;
    document.getElementById('confirmModal').classList.remove('hidden');
    const yes = document.getElementById('btnConfirmYes');
    const no = document.getElementById('btnConfirmNo');
    const close = v => { document.getElementById('confirmModal').classList.add('hidden'); resolve(v); };
    yes.onclick = () => close(true);
    no.onclick = () => close(false);
  });
}

// ─── Page navigation ─────────────────────────────────────────────────────────
const pages = ['playlist', 'add', 'settings'];
function showPage(name) {
  pages.forEach(p => {
    document.getElementById(`page-${p}`).classList.toggle('hidden', p !== name);
  });
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.page === name);
  });
  if (name === 'playlist') loadPlaylist();
  if (name === 'settings') loadSettings();
}

document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => showPage(btn.dataset.page));
});

// Add tabs
document.querySelectorAll('.add-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.add-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    ['search', 'url', 'manual'].forEach(id => {
      document.getElementById(`tab-${id}`).classList.toggle('hidden', id !== tab.dataset.tab);
    });
  });
});

// ─── Playlist state ───────────────────────────────────────────────────────────
let playlist = [];
let dragSrcIdx = null;

function fmtDuration(sec) {
  if (!sec) return '';
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function songHTML(item, idx) {
  const thumb = item.thumbnail
    ? `<img class="song-thumb" src="${item.thumbnail}" alt="" loading="lazy" onerror="this.style.display='none'">`
    : `<div class="song-thumb-placeholder">🎵</div>`;

  const typeTag = item.type === 'local'
    ? `<span class="song-type local">로컬</span>`
    : `<span class="song-type youtube">YT</span>`;

  const duration = item.duration ? ` · ${fmtDuration(item.duration)}` : '';
  const songId = item.song_id || item.id || '';

  return `
    <li class="playlist-item" draggable="true" data-idx="${idx}" data-id="${item.id}">
      <span class="drag-handle" title="드래그로 순서 변경">⋮⋮</span>
      ${thumb}
      <div class="song-info">
        <div class="song-title">${escHtml(item.title)}</div>
        <div class="song-meta">${typeTag} ${escHtml(songId)}${duration}</div>
      </div>
      <div class="song-actions">
        <button class="btn-ghost btn-icon btn-sm" title="수정" onclick="openEdit(${idx})">✏️</button>
        <button class="btn-danger btn-icon btn-sm" title="삭제" onclick="deleteSong(${idx})">🗑️</button>
      </div>
    </li>`;
}

function renderPlaylist(items) {
  const list = document.getElementById('playlistList');
  const empty = document.getElementById('playlistEmpty');
  const count = document.getElementById('playlistCount');
  count.textContent = `${items.length} 곡`;
  if (!items.length) {
    list.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  list.innerHTML = items.map(songHTML).join('');
  initDrag();
}

async function loadPlaylist() {
  try {
    const res = await apiFetch('/api/playlist');
    const data = await res.json();
    playlist = data.playlist || [];
    renderPlaylist(filterPlaylist());
  } catch {
    toast('플레이리스트 불러오기 실패', 'error');
  }
}

function filterPlaylist() {
  const q = document.getElementById('filterInput').value.toLowerCase();
  return q ? playlist.filter(s => s.title.toLowerCase().includes(q)) : playlist;
}

document.getElementById('filterInput').addEventListener('input', () => renderPlaylist(filterPlaylist()));

// ─── Drag & drop reorder ──────────────────────────────────────────────────────
function initDrag() {
  document.querySelectorAll('.playlist-item').forEach(item => {
    item.addEventListener('dragstart', e => {
      dragSrcIdx = Number(item.dataset.idx);
      item.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    item.addEventListener('dragend', () => item.classList.remove('dragging'));
    item.addEventListener('dragover', e => {
      e.preventDefault();
      document.querySelectorAll('.playlist-item').forEach(i => i.classList.remove('drag-over'));
      item.classList.add('drag-over');
    });
    item.addEventListener('dragleave', () => item.classList.remove('drag-over'));
    item.addEventListener('drop', async e => {
      e.preventDefault();
      item.classList.remove('drag-over');
      const toIdx = Number(item.dataset.idx);
      if (dragSrcIdx === toIdx) return;
      const moved = playlist.splice(dragSrcIdx, 1)[0];
      playlist.splice(toIdx, 0, moved);
      renderPlaylist(filterPlaylist());
      await saveReorder();
    });
  });
}

async function saveReorder() {
  try {
    const items = playlist.map((s, i) => ({ id: s.id, sort_order: i }));
    const res = await apiFetch('/api/playlist/reorder', {
      method: 'PUT',
      body: JSON.stringify({ items }),
    });
    if (!res.ok) throw new Error();
    toast('순서 저장됨', 'success', 1500);
  } catch {
    toast('순서 저장 실패', 'error');
    await loadPlaylist();
  }
}

// ─── Delete ───────────────────────────────────────────────────────────────────
window.deleteSong = async function (idx) {
  const song = playlist[idx];
  const ok = await confirm('곡 삭제', `"${song.title}"을(를) 삭제하시겠습니까?`);
  if (!ok) return;
  try {
    const res = await apiFetch(`/api/playlist/${song.id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error();
    playlist.splice(idx, 1);
    renderPlaylist(filterPlaylist());
    toast('삭제됨', 'success');
  } catch {
    toast('삭제 실패', 'error');
  }
};

// Clear all
document.getElementById('btnClearAll').addEventListener('click', async () => {
  if (!playlist.length) return;
  const ok = await confirm('전체 삭제', `플레이리스트의 모든 ${playlist.length}곡을 삭제하시겠습니까?`);
  if (!ok) return;
  try {
    const res = await apiFetch('/api/playlist', { method: 'DELETE' });
    if (!res.ok) throw new Error();
    playlist = [];
    renderPlaylist([]);
    toast('전체 삭제됨', 'success');
  } catch {
    toast('삭제 실패', 'error');
  }
});

// Refresh
document.getElementById('btnRefreshPlaylist').addEventListener('click', loadPlaylist);

// ─── Edit modal ───────────────────────────────────────────────────────────────
let editIdx = null;
window.openEdit = function (idx) {
  editIdx = idx;
  const song = playlist[idx];
  document.getElementById('editTitle').value = song.title;
  document.getElementById('editThumb').value = song.thumbnail || '';
  document.getElementById('editDuration').value = song.duration || '';
  document.getElementById('editModal').classList.remove('hidden');
};
document.getElementById('btnEditCancel').addEventListener('click', () => {
  document.getElementById('editModal').classList.add('hidden');
});
document.getElementById('btnEditSave').addEventListener('click', async () => {
  const song = playlist[editIdx];
  const updates = {
    title: document.getElementById('editTitle').value.trim(),
    thumbnail: document.getElementById('editThumb').value.trim(),
    duration: Number(document.getElementById('editDuration').value) || 0,
  };
  if (!updates.title) { toast('제목을 입력해주세요', 'warning'); return; }
  try {
    const res = await apiFetch(`/api/playlist/${song.id}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    });
    if (!res.ok) throw new Error();
    Object.assign(playlist[editIdx], updates);
    renderPlaylist(filterPlaylist());
    document.getElementById('editModal').classList.add('hidden');
    toast('수정됨', 'success');
  } catch {
    toast('수정 실패', 'error');
  }
});

// ─── Add song: YouTube search ─────────────────────────────────────────────────
document.getElementById('btnSearch').addEventListener('click', searchYouTube);
document.getElementById('searchInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') searchYouTube();
});

async function searchYouTube() {
  const q = document.getElementById('searchInput').value.trim();
  if (!q) return;
  const progress = document.getElementById('searchProgress');
  const bar = document.getElementById('searchBar');
  const results = document.getElementById('searchResults');
  progress.classList.remove('hidden');
  bar.style.width = '30%';
  results.innerHTML = '<li style="color:var(--text-3);padding:.5rem">검색 중…</li>';

  try {
    // We call a YouTube search proxy via the Worker (if configured)
    // Fallback: search using YouTube oEmbed / data API
    bar.style.width = '70%';
    const res = await apiFetch(`/api/youtube/search?q=${encodeURIComponent(q)}&limit=8`);
    bar.style.width = '100%';

    if (!res.ok) {
      results.innerHTML = `<li class="hint" style="padding:.5rem">YouTube 검색 API가 설정되지 않았습니다. URL 탭 또는 수동 입력을 이용해 주세요.</li>`;
      return;
    }
    const data = await res.json();
    renderSearchResults(data.items || []);
  } catch {
    results.innerHTML = `<li class="hint" style="padding:.5rem">YouTube 검색 API가 설정되지 않았습니다. URL 탭 또는 수동 입력을 이용해 주세요.</li>`;
  } finally {
    setTimeout(() => progress.classList.add('hidden'), 400);
    bar.style.width = '0';
  }
}

function renderSearchResults(items) {
  const results = document.getElementById('searchResults');
  if (!items.length) { results.innerHTML = '<li class="hint" style="padding:.5rem">검색 결과 없음</li>'; return; }
  results.innerHTML = items.map((item, i) => `
    <li class="result-item">
      ${item.thumbnail ? `<img class="song-thumb" src="${item.thumbnail}" alt="" loading="lazy">` : '<div class="song-thumb-placeholder">🎵</div>'}
      <div class="song-info">
        <div class="song-title">${escHtml(item.title)}</div>
        <div class="song-meta"><span class="song-type youtube">YT</span> ${escHtml(item.id)}${item.duration ? ` · ${fmtDuration(item.duration)}` : ''}</div>
      </div>
      <button class="btn-primary btn-sm" onclick="addYouTubeSong('${escHtml(item.id)}','${escHtml(item.title).replace(/'/g,"\\'")}','${escHtml(item.thumbnail || '')}',${item.duration||0})">추가</button>
    </li>`).join('');
}

// ─── Add song: YouTube URL ────────────────────────────────────────────────────
document.getElementById('btnAddUrl').addEventListener('click', addFromUrl);
document.getElementById('urlInput').addEventListener('keydown', e => { if (e.key === 'Enter') addFromUrl(); });

async function addFromUrl() {
  const url = document.getElementById('urlInput').value.trim();
  const hint = document.getElementById('urlHint');
  const id = extractYouTubeId(url);
  if (!id) { hint.textContent = '올바른 YouTube URL을 입력해주세요.'; return; }
  hint.textContent = '';
  await addYouTubeSong(id, `YouTube: ${id}`, `https://i.ytimg.com/vi/${id}/hqdefault.jpg`, 0);
  document.getElementById('urlInput').value = '';
}

function extractYouTubeId(url) {
  const patterns = [
    /youtu\.be\/([A-Za-z0-9_-]{11})/,
    /[?&]v=([A-Za-z0-9_-]{11})/,
    /embed\/([A-Za-z0-9_-]{11})/,
    /shorts\/([A-Za-z0-9_-]{11})/,
  ];
  for (const p of patterns) {
    const m = url.match(p);
    if (m) return m[1];
  }
  if (/^[A-Za-z0-9_-]{11}$/.test(url)) return url;
  return null;
}

window.addYouTubeSong = async function (id, title, thumbnail, duration) {
  try {
    const res = await apiFetch('/api/playlist', {
      method: 'POST',
      body: JSON.stringify({ type: 'youtube', song_id: id, title, thumbnail, duration }),
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    playlist.push(data.song);
    toast(`"${title}" 추가됨`, 'success');
    showPage('playlist');
  } catch {
    toast('추가 실패', 'error');
  }
};

// ─── Add song: Manual ─────────────────────────────────────────────────────────
document.getElementById('btnAddManual').addEventListener('click', async () => {
  const title = document.getElementById('manualTitle').value.trim();
  const id = document.getElementById('manualId').value.trim();
  const thumbnail = document.getElementById('manualThumb').value.trim();
  const duration = Number(document.getElementById('manualDuration').value) || 0;
  if (!title || !id) { toast('제목과 Video ID는 필수입니다', 'warning'); return; }
  await addYouTubeSong(id, title, thumbnail || `https://i.ytimg.com/vi/${id}/hqdefault.jpg`, duration);
  document.getElementById('manualTitle').value = '';
  document.getElementById('manualId').value = '';
  document.getElementById('manualThumb').value = '';
  document.getElementById('manualDuration').value = '';
});

// ─── Settings ─────────────────────────────────────────────────────────────────
async function loadSettings() {
  try {
    const res = await apiFetch('/api/settings');
    const { settings } = await res.json();
    document.getElementById('settingAutostart').checked = settings.autostart === 'true';
    document.getElementById('settingPort').value = settings.port || '8765';
    document.getElementById('settingBrowser').value = settings.broadcast_browser || 'auto';
    document.getElementById('settingEndImage').value = settings.end_broadcast_image || '';
  } catch {
    toast('설정 불러오기 실패', 'error');
  }
}

document.getElementById('btnSaveSettings').addEventListener('click', async () => {
  const settings = {
    autostart: document.getElementById('settingAutostart').checked ? 'true' : 'false',
    port: document.getElementById('settingPort').value,
    broadcast_browser: document.getElementById('settingBrowser').value,
    end_broadcast_image: document.getElementById('settingEndImage').value,
  };
  try {
    const res = await apiFetch('/api/settings', { method: 'PUT', body: JSON.stringify(settings) });
    if (!res.ok) throw new Error();
    toast('설정 저장됨', 'success');
  } catch {
    toast('설정 저장 실패', 'error');
  }
});

// ─── Sync buttons ─────────────────────────────────────────────────────────────
function setSyncStatus(msg, type = '') {
  const el = document.getElementById('syncStatus');
  el.textContent = msg;
  el.className = `sync-status ${type}`;
}

// 앱 동기화: push current DB state down to Windows app (DB is source of truth)
// In web context: push web-visible playlist + settings → DB (already IS the DB)
// The "앱 동기화" from the website pushes any local edits to ensure DB is up to date.
document.getElementById('btnSyncPush').addEventListener('click', async () => {
  const btn = document.getElementById('btnSyncPush');
  btn.disabled = true;
  setSyncStatus('앱 → DB 동기화 중…');
  try {
    const [plRes, setRes] = await Promise.all([
      apiFetch('/api/playlist'),
      apiFetch('/api/settings'),
    ]);
    const { playlist: pl } = await plRes.json();
    const { settings } = await setRes.json();
    const res = await apiFetch('/api/sync/push', {
      method: 'POST',
      body: JSON.stringify({ playlist: pl, settings }),
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    setSyncStatus(`✅ ${new Date(data.pushed_at).toLocaleTimeString('ko-KR')} 완료`, 'ok');
    toast('앱 동기화 완료', 'success');
  } catch {
    setSyncStatus('❌ 동기화 실패', 'err');
    toast('앱 동기화 실패', 'error');
  } finally {
    btn.disabled = false;
  }
});

// 데이터베이스 동기화: pull fresh data from DB into this page
document.getElementById('btnSyncPull').addEventListener('click', async () => {
  const btn = document.getElementById('btnSyncPull');
  btn.disabled = true;
  setSyncStatus('DB → 앱 동기화 중…');
  try {
    const res = await apiFetch('/api/sync/pull');
    if (!res.ok) throw new Error();
    const data = await res.json();
    playlist = data.playlist || [];
    renderPlaylist(filterPlaylist());
    // apply settings if on settings page
    if (!document.getElementById('page-settings').classList.contains('hidden')) {
      const s = data.settings || {};
      document.getElementById('settingAutostart').checked = s.autostart === 'true';
      document.getElementById('settingPort').value = s.port || '8765';
      document.getElementById('settingBrowser').value = s.broadcast_browser || 'auto';
      document.getElementById('settingEndImage').value = s.end_broadcast_image || '';
    }
    setSyncStatus(`✅ ${new Date(data.pulled_at).toLocaleTimeString('ko-KR')} 완료`, 'ok');
    toast('데이터베이스 동기화 완료', 'success');
  } catch {
    setSyncStatus('❌ 동기화 실패', 'err');
    toast('데이터베이스 동기화 실패', 'error');
  } finally {
    btn.disabled = false;
  }
});

// ─── Export / Import JSON ──────────────────────────────────────────────────────
document.getElementById('btnExportJson').addEventListener('click', () => {
  const json = JSON.stringify({ playlist }, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `playlist_${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  toast('JSON 내보내기 완료', 'success');
});

document.getElementById('btnImportJson').addEventListener('click', () => {
  document.getElementById('importFileInput').click();
});
document.getElementById('importFileInput').addEventListener('change', async e => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    const items = data.playlist || (Array.isArray(data) ? data : []);
    if (!items.length) { toast('유효한 playlist 데이터가 없습니다', 'warning'); return; }
    const ok = await confirm('JSON 가져오기', `${items.length}곡을 추가하시겠습니까? 기존 플레이리스트에 추가됩니다.`);
    if (!ok) return;
    let added = 0;
    for (const item of items) {
      const res = await apiFetch('/api/playlist', {
        method: 'POST',
        body: JSON.stringify({
          type: item.type || 'youtube',
          song_id: item.song_id || item.id,
          title: item.title,
          thumbnail: item.thumbnail || '',
          duration: item.duration || 0,
        }),
      });
      if (res.ok) { const d = await res.json(); playlist.push(d.song); added++; }
    }
    renderPlaylist(filterPlaylist());
    toast(`${added}곡 가져오기 완료`, 'success');
  } catch {
    toast('JSON 파일을 읽을 수 없습니다', 'error');
  }
  e.target.value = '';
});

// ─── Logout ───────────────────────────────────────────────────────────────────
document.getElementById('btnLogout').addEventListener('click', () => {
  localStorage.removeItem('amp_token');
  localStorage.removeItem('amp_user');
  window.location.href = 'login.html';
});

// ─── Utils ────────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.getElementById('currentUser').textContent = localStorage.getItem('amp_user') || 'admin';
loadPlaylist();
