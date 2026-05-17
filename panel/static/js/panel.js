/**
 * 3세대 음방시스템 컨트롤 패널
 */
(function () {
  "use strict";

  let socket = null;
  let csrfToken = "";
  let playlist = [];
  let currentIndex = -1;
  let playbackStatus = "stopped";
  let selectedDisplay = 0;
  let sortable = null;
  let socketConnected = false;
  let broadcastAllowed = false;

  const $ = (sel) => document.querySelector(sel);

  function isLocalAppView() {
    const h = location.hostname;
    return h === "127.0.0.1" || h === "localhost";
  }

  async function fetchCsrf() {
    const res = await fetch("/api/csrf-token", { credentials: "same-origin" });
    const data = await res.json();
    csrfToken = data.csrf_token;
  }

  function initSocket() {
    socket = io({ withCredentials: true });

    socket.on("playlist_update", (data) => {
      playlist = data.playlist || [];
      renderPlaylist();
    });

    socket.on("now_playing", (data) => {
      currentIndex = data.index;
      const title = data.title || "재생 중인 곡 없음";
      $("#nowTitle").textContent = title;
      $("#progressFill").style.width = "0%";
      renderPlaylist();
    });

    socket.on("playback_status", (data) => {
      playbackStatus = data.status;
      updatePauseButton();
    });

    socket.on("search_progress", (data) => {
      const wrap = $("#searchProgressWrap");
      wrap.hidden = false;
      const bar = $("#searchProgressBar");
      bar.style.setProperty("--pct", `${data.progress}%`);
      bar.style.width = `${data.progress}%`;
      bar.style.height = "6px";
      bar.style.background = "var(--primary)";
      bar.style.borderRadius = "99px";
      $("#searchProgressStatus").textContent = data.status || "";
      if (data.progress >= 100) {
        setTimeout(() => {
          wrap.hidden = true;
        }, 600);
      }
    });

    socket.on("playback_progress", (data) => {
      if (!data || !data.duration) return;
      if (typeof data.index === "number" && data.index >= 0) {
        currentIndex = data.index;
      }
      const pct = Math.min(100, Math.max(0, (data.current / data.duration) * 100));
      $("#progressFill").style.width = `${pct}%`;
    });

    socket.on("connect", () => {
      socketConnected = true;
      broadcastAllowed = false;
      setControlsEnabled(false);
      socket.emit("get_state", {});
      updateServerStatus();
    });

    socket.on("disconnect", () => {
      socketConnected = false;
      broadcastAllowed = false;
      setControlsEnabled(false);
      updateServerStatus();
    });

    socket.on("connect_error", () => {
      socketConnected = false;
      broadcastAllowed = false;
      setControlsEnabled(false);
      updateServerStatus();
    });

    socket.on("control_denied", (data) => {
      showAppAlert((data && data.message) || "방송을 제어할 수 없습니다. 로그인 상태를 확인해 주세요.");
      setControlsEnabled(false);
    });

    socket.on("session_status", (data) => {
      if (data && typeof data.broadcast_allowed === "boolean") {
        broadcastAllowed = data.broadcast_allowed;
        setControlsEnabled(socketConnected && broadcastAllowed);
      }
      updateServerStatusFromData(data);
    });
  }

  function setControlsEnabled(enabled) {
    const on = enabled && broadcastAllowed;
    ["btnBroadcastStart", "btnPrev", "btnPause", "btnNext", "btnStop"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = !on;
    });
  }

  function renderPlaylist() {
    const list = $("#playlistList");
    const empty = $("#playlistEmpty");
    list.innerHTML = "";
    empty.hidden = playlist.length > 0;

    playlist.forEach((item, idx) => {
      const li = document.createElement("li");
      li.className = "playlist-item" + (idx === currentIndex ? " playing" : "");
      li.dataset.index = String(idx);

      const displayTitle =
        item.type === "local"
          ? item.title || item.id || "로컬 파일"
          : item.title || "제목 없음";

      let thumb;
      if (item.type === "youtube" && item.thumbnail) {
        thumb = `<img src="${escapeHtml(item.thumbnail)}" alt="" />`;
      } else if (item.type === "youtube" && item.id) {
        thumb = `<img src="https://i.ytimg.com/vi/${escapeHtml(item.id)}/hqdefault.jpg" alt="" />`;
      } else {
        thumb = `<span class="thumb-icon">📁</span>`;
      }

      li.innerHTML = `
        <span class="drag-handle" title="드래그하여 순서 변경" aria-hidden="true">⋮⋮</span>
        ${thumb}
        <span class="title" title="${escapeHtml(displayTitle)}">${escapeHtml(displayTitle)}</span>
        <button type="button" class="btn-delete" data-index="${idx}" aria-label="삭제">✕</button>
      `;
      list.appendChild(li);
    });

    list.querySelectorAll(".btn-delete").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const index = parseInt(btn.dataset.index, 10);
        socket.emit("remove_song", { index });
      });
    });

    if (sortable) sortable.destroy();
    if (!list || playlist.length === 0) return;
    sortable = new Sortable(list, {
      animation: 200,
      handle: ".drag-handle",
      filter: ".btn-delete",
      preventOnFilter: true,
      forceFallback: true,
      fallbackOnBody: true,
      fallbackTolerance: 4,
      ghostClass: "sortable-ghost",
      delay: 80,
      delayOnTouchOnly: false,
      onEnd(evt) {
        if (evt.oldIndex === evt.newIndex) return;
        if (!socketConnected) return;
        socket.emit("reorder", { from_idx: evt.oldIndex, to_idx: evt.newIndex });
      },
    });
  }

  function endImagePublicUrl(path) {
    if (!path) return "";
    if (path.startsWith("http://") || path.startsWith("https://")) return path;
    if (path.startsWith("/")) return path;
    return "/" + path.replace(/^\/+/, "");
  }

  function updateEndImagePreview(path) {
    const wrap = $("#endImagePreviewWrap");
    const img = $("#endImagePreview");
    if (!wrap || !img) return;
    const url = endImagePublicUrl(path);
    if (!url) {
      wrap.hidden = true;
      img.removeAttribute("src");
      return;
    }
    img.onerror = () => {
      wrap.hidden = true;
    };
    img.onload = () => {
      wrap.hidden = false;
    };
    img.src = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function emitAddSong(payload) {
    return new Promise((resolve) => {
      if (!socket || !socket.connected) {
        showAppAlert("서버에 연결되어 있지 않습니다.", { title: "추가 실패" });
        resolve(null);
        return;
      }
      socket.emit("add_song", payload, (res) => {
        if (res && res.ok) {
          const name = payload.title || "곡";
          showAppAlert(`「${name}」이(가) 플레이리스트에 추가되었습니다.`, { title: "추가 완료" });
        } else {
          showAppAlert("플레이리스트에 추가하지 못했습니다.", { title: "추가 실패" });
        }
        resolve(res);
      });
    });
  }

  function updatePauseButton() {
    const btn = $("#btnPause");
    btn.textContent = playbackStatus === "playing" ? "⏸" : "▶";
  }

  const ONBOARDING_SLIDE_COUNT = 4;
  let onboardingSlide = 0;

  function initTabs() {
    document.querySelectorAll(".sidebar-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".sidebar-tab").forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        $("#panel-" + tab.dataset.tab).classList.add("active");
      });
    });
  }

  async function syncNetwork() {
    const btn = $("#btnSyncNetwork");
    if (btn) btn.disabled = true;
    try {
      const res = await fetch("/api/network", { credentials: "same-origin" });
      if (res.ok) {
        const data = await res.json();
        showLanUrls(data);
      }
      await loadPublicConfig();
      await updateServerStatus();
      const hint = document.querySelector(".server-sync-hint");
      if (hint) {
        const orig = hint.textContent;
        hint.textContent = "동기화 완료";
        setTimeout(() => {
          hint.textContent = orig;
        }, 2000);
      }
    } catch (err) {
      showAppAlert("동기화 실패: " + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function openBroadcastWarnModal() {
    const ack = $("#broadcastWarnAck");
    const confirmBtn = $("#btnBroadcastWarnConfirm");
    if (ack) ack.checked = false;
    if (confirmBtn) confirmBtn.disabled = true;
    $("#broadcastWarnModal").hidden = false;
  }

  function updateOnboardingUI() {
    const track = $("#onboardingTrack");
    const viewport = $("#onboardingViewport");
    if (track && viewport) {
      const w = viewport.getBoundingClientRect().width;
      track.style.transform = w > 0 ? `translateX(-${onboardingSlide * w}px)` : "";
    }
    document.querySelectorAll(".onboarding-dot").forEach((d, i) => {
      d.classList.toggle("active", i === onboardingSlide);
    });
    const prev = $("#btnOnboardingPrev");
    if (prev) prev.hidden = onboardingSlide === 0;
    const nextBtn = $("#btnOnboardingNext");
    if (nextBtn) {
      nextBtn.textContent =
        onboardingSlide >= ONBOARDING_SLIDE_COUNT - 1 ? "동의하고 시작" : "다음";
    }
    const err = $("#onboardingErr");
    if (err) err.hidden = true;
  }

  function initOnboardingControls() {
    const dots = $("#onboardingDots");
    if (!dots || dots.dataset.ready) return;
    dots.dataset.ready = "1";
    dots.innerHTML = "";
    for (let i = 0; i < ONBOARDING_SLIDE_COUNT; i++) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "onboarding-dot" + (i === 0 ? " active" : "");
      b.setAttribute("aria-label", i + 1 + "번째 안내");
      b.addEventListener("click", () => {
        onboardingSlide = i;
        updateOnboardingUI();
      });
      dots.appendChild(b);
    }
    $("#btnOnboardingPrev").addEventListener("click", () => {
      if (onboardingSlide > 0) {
        onboardingSlide--;
        updateOnboardingUI();
      }
    });
    $("#btnOnboardingNext").addEventListener("click", async () => {
      if (onboardingSlide < ONBOARDING_SLIDE_COUNT - 1) {
        onboardingSlide++;
        updateOnboardingUI();
        return;
      }
      if (!$("#onboardingTerms").checked) {
        $("#onboardingErr").hidden = false;
        return;
      }
      const res = await fetch("/api/settings/onboarding", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ agree_terms: true }),
      });
      const data = await res.json();
      if (!res.ok) {
        showAppAlert(data.error || "저장 실패");
        return;
      }
      $("#onboardingOverlay").hidden = true;
    });
  }

  async function maybeShowOnboarding() {
    try {
      const res = await fetch("/api/settings/onboarding", { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      if (data.complete) return;
      onboardingSlide = 0;
      initOnboardingControls();
      $("#onboardingOverlay").hidden = false;
      requestAnimationFrame(() => updateOnboardingUI());
    } catch (e) {
      /* ignore */
    }
  }

  async function addYoutubeByUrl() {
    const raw = $("#youtubeUrlInput").value.trim();
    const hint = $("#youtubeUrlHint");
    if (!raw) {
      if (hint) hint.textContent = "YouTube 링크를 입력해 주세요.";
      return;
    }
    const btn = $("#btnAddYoutubeUrl");
    if (btn) btn.disabled = true;
    if (hint) hint.textContent = "영상 정보를 가져오는 중…";
    try {
      const res = await fetch("/api/youtube/from-url", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ url: raw }),
      });
      const data = await res.json();
      if (!res.ok) {
        if (hint) hint.textContent = data.error || "추가 실패";
        showAppAlert(data.error || "추가 실패");
        return;
      }
      await emitAddSong({
        type: "youtube",
        id: data.id,
        title: data.title,
        thumbnail: data.thumbnail,
        duration: data.duration || 0,
      });
      $("#youtubeUrlInput").value = "";
      if (hint) hint.textContent = "";
    } catch (err) {
      if (hint) hint.textContent = "오류: " + err.message;
      showAppAlert("링크 추가 중 오류: " + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function doSearch() {
    const query = $("#searchInput").value.trim();
    if (!query) return;
    const resultsEl = $("#searchResults");
    resultsEl.innerHTML = "";
    $("#searchProgressWrap").hidden = false;

    try {
      const res = await fetch("/api/search", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();
      if (!res.ok) {
        showAppAlert(data.error || "검색 실패");
        return;
      }
      (data.results || []).forEach((item) => {
        const li = document.createElement("li");
        li.innerHTML = `
          <img src="${escapeHtml(item.thumbnail)}" alt="" />
          <span class="title">${escapeHtml(item.title)}</span>
          <button type="button" class="btn-primary btn-sm">추가</button>
        `;
        li.querySelector("button").addEventListener("click", () => {
          emitAddSong({
            type: "youtube",
            id: item.id,
            title: item.title,
            thumbnail: item.thumbnail,
            duration: item.duration || 0,
          });
        });
        resultsEl.appendChild(li);
      });
    } catch (err) {
      showAppAlert("검색 중 오류: " + err.message);
    }
  }

  async function uploadLocal(file) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/upload/local", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
      body: fd,
    });
    const data = await res.json();
    if (!res.ok) {
      showAppAlert(data.error || "업로드 실패");
      return;
    }
    await emitAddSong(data);
  }

  async function loadDisplays() {
    const res = await fetch("/api/displays", { credentials: "same-origin" });
    const data = await res.json();
    const list = $("#displayList");
    list.innerHTML = "";
    (data.displays || []).forEach((d) => {
      const li = document.createElement("li");
      li.textContent = d.name;
      li.dataset.index = String(d.index);
      if (d.index === selectedDisplay) li.classList.add("selected");
      li.addEventListener("click", () => {
        list.querySelectorAll("li").forEach((x) => x.classList.remove("selected"));
        li.classList.add("selected");
        selectedDisplay = d.index;
      });
      list.appendChild(li);
    });
  }

  function openDisplayModal() {
    $("#displayModal").hidden = false;
    loadDisplays();
  }

  function initControls() {
    $("#btnSearch").addEventListener("click", doSearch);
    $("#searchInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch();
    });

    $("#btnAddYoutubeUrl").addEventListener("click", addYoutubeByUrl);
    $("#youtubeUrlInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") addYoutubeByUrl();
    });

    $("#btnPickLocal").addEventListener("click", () => $("#localFileInput").click());
    $("#localFileInput").addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (file) uploadLocal(file);
      e.target.value = "";
    });

    $("#btnBroadcastStart").addEventListener("click", () => {
      if (!socketConnected || !broadcastAllowed) {
        showAppAlert("앱에 로그인되어 있어야 방송을 시작할 수 있습니다.");
        return;
      }
      if (!playlist.length) {
        showAppAlert("플레이리스트에 곡을 추가해 주세요.");
        return;
      }
      openBroadcastWarnModal();
    });

    $("#broadcastWarnAck").addEventListener("change", () => {
      $("#btnBroadcastWarnConfirm").disabled = !$("#broadcastWarnAck").checked;
    });
    $("#btnBroadcastWarnCancel").addEventListener("click", () => {
      $("#broadcastWarnModal").hidden = true;
    });
    $("#btnBroadcastWarnConfirm").addEventListener("click", () => {
      if (!$("#broadcastWarnAck").checked) return;
      $("#broadcastWarnModal").hidden = true;
      openDisplayModal();
    });

    $("#btnDisplayCancel").addEventListener("click", () => {
      $("#displayModal").hidden = true;
    });
    $("#btnDisplayConfirm").addEventListener("click", () => {
      $("#displayModal").hidden = true;
      if (!socketConnected || !broadcastAllowed) {
        showAppAlert("앱에 로그인되어 있어야 방송을 시작할 수 있습니다.");
        return;
      }
      if (!playlist.length) {
        showAppAlert("플레이리스트에 곡을 추가해 주세요.");
        return;
      }
      socket.emit("control", { action: "start", display_index: selectedDisplay });
    });

    $("#btnPause").addEventListener("click", () => {
      const action = playbackStatus === "playing" ? "pause" : "play";
      socket.emit("control", { action });
    });
    $("#btnPrev").addEventListener("click", () => socket.emit("control", { action: "prev" }));
    $("#btnNext").addEventListener("click", () => socket.emit("control", { action: "next" }));
    $("#btnStop").addEventListener("click", async () => {
      const ok = await showAppConfirm("방송을 종료할까요?", { title: "방송 종료" });
      if (ok) socket.emit("control", { action: "stop" });
    });

    $("#btnLogout").addEventListener("click", async () => {
      if (socket && socket.connected) {
        socket.disconnect();
      }
      socketConnected = false;
      broadcastAllowed = false;
      setControlsEnabled(false);
      await fetch("/api/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
      });
      window.location.href = "/login";
    });

    $("#btnEndImage").addEventListener("click", () => $("#endImageInput").click());
    $("#endImageInput").addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const localPreview = URL.createObjectURL(file);
      const previewImg = $("#endImagePreview");
      const previewWrap = $("#endImagePreviewWrap");
      if (previewImg && previewWrap) {
        previewImg.src = localPreview;
        previewWrap.hidden = false;
      }
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/settings/end-image", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
        body: fd,
      });
      const data = await res.json();
      if (res.ok) {
        const path = data.path || "";
        $("#endImageHint").textContent = path ? "커스텀 종료 이미지 적용 중" : "업로드 완료";
        if (localPreview) URL.revokeObjectURL(localPreview);
        updateEndImagePreview(path);
      } else {
        if (localPreview) URL.revokeObjectURL(localPreview);
        updateEndImagePreview("");
        showAppAlert(data.error);
      }
      e.target.value = "";
    });

    $("#btnEndImageClear").addEventListener("click", async () => {
      await fetch("/api/settings/end-image", {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
      });
      $("#endImageHint").textContent = "기본 종료 화면 사용 중";
      updateEndImagePreview("");
      const fileInput = $("#endImageInput");
      if (fileInput) fileInput.value = "";
    });

    $("#btnChangePassword").addEventListener("click", async () => {
      const res = await fetch("/api/password", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({
          current_password: $("#currentPassword").value,
          new_password: $("#newPassword").value,
        }),
      });
      const data = await res.json();
      showAppAlert(res.ok ? "비밀번호가 변경되었습니다." : data.error || "실패", {
        title: res.ok ? "완료" : "오류",
      });
    });

    $("#btnResetAccount").addEventListener("click", async () => {
      const ok = await showAppConfirm(
        "로컬 계정을 admin / 1234 로 초기화할까요?",
        { title: "DB 계정 초기화", okText: "초기화", cancelText: "취소" }
      );
      if (!ok) return;
      const res = await fetch("/api/settings/reset-account", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (res.ok) {
        window.location.href = "/login";
        return;
      }
      showAppAlert(data.error || "초기화 실패");
    });

    // #btnCopyLan 제거됨 (LAN 주소 표시 기능 삭제)

    document.querySelectorAll('input[name="broadcastBrowser"]').forEach((radio) => {
      radio.addEventListener("change", async () => {
        if (!radio.checked) return;
        const res = await fetch("/api/settings/broadcast-browser", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({ broadcast_browser: radio.value }),
        });
        const data = await res.json();
        if (!res.ok) showAppAlert(data.error || "저장 실패");
        else updateBrowserHint(data.available);
      });
    });

    $("#autostartToggle").addEventListener("change", async (e) => {
      await fetch("/api/settings/autostart", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ enabled: e.target.checked }),
      });
    });
  }

  function updateServerStatusFromData(data) {
    const el = $("#serverStatus");
    if (!el || !data) return;
    if (data.viewer_is_local || isLocalAppView()) {
      el.textContent = "서버 켜짐";
      el.className = "server-status";
    } else if (data.panel_online && data.broadcast_allowed) {
      el.textContent = "앱과 연결됨";
      el.className = "server-status status-remote-ok";
    } else if (data.panel_online) {
      el.textContent = "앱 로그인 대기";
      el.className = "server-status status-wait";
    } else {
      el.textContent = "앱 로그인 대기";
      el.className = "server-status status-wait";
    }
  }

  async function updateServerStatus() {
    const el = $("#serverStatus");
    if (!el) return;
    try {
      const res = await fetch("/api/session/status", { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      if (typeof data.broadcast_allowed === "boolean") {
        broadcastAllowed = data.broadcast_allowed;
        setControlsEnabled(socketConnected && broadcastAllowed);
      }
      if (isLocalAppView()) {
        el.textContent = "서버 켜짐";
        el.className = "server-status";
      } else if (data.panel_online && data.authenticated && data.broadcast_allowed) {
        el.textContent = "앱과 연결됨";
        el.className = "server-status status-remote-ok";
      } else if (data.panel_online) {
        el.textContent = "앱 로그인 대기";
        el.className = "server-status status-wait";
      } else {
        el.textContent = "앱 로그인 대기";
        el.className = "server-status status-wait";
      }
    } catch (e) {
      el.textContent = isLocalAppView() ? "서버 켜짐" : "연결 확인 중…";
    }
  }

  function showLanUrls(_data) {
    // LAN 주소 표시 UI 제거됨 — 아무것도 하지 않음
  }

  function updateBrowserHint(available) {
    const el = $("#browserAvailHint");
    if (!available) return;
    const parts = [];
    if (available.edge) parts.push("Edge 설치됨");
    else parts.push("Edge 없음");
    if (available.chrome) parts.push("Chrome 설치됨");
    else parts.push("Chrome 없음");
    el.textContent = parts.join(" · ");
    document
      .querySelector('input[name="broadcastBrowser"][value="edge"]')
      .closest("label")
      .style.opacity = available.edge ? "1" : "0.45";
    document
      .querySelector('input[name="broadcastBrowser"][value="chrome"]')
      .closest("label")
      .style.opacity = available.chrome ? "1" : "0.45";
  }

  async function loadBrowserSetting() {
    const res = await fetch("/api/settings/broadcast-browser", {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    const data = await res.json();
    const val = data.broadcast_browser || "auto";
    const radio = document.querySelector(
      'input[name="broadcastBrowser"][value="' + val + '"]'
    );
    if (radio) radio.checked = true;
    updateBrowserHint(data.available);
  }

  async function loadPublicConfig() {
    const res = await fetch("/api/config/public", { credentials: "same-origin" });
    const data = await res.json();
    $("#autostartToggle").checked = !!data.autostart;
    const endPath = data.end_broadcast_image || "";
    $("#endImageHint").textContent = endPath
      ? "커스텀 종료 이미지 적용 중"
      : "기본 종료 화면 사용 중";
    updateEndImagePreview(endPath);
    showLanUrls(data);
    const br = data.broadcast_browser || "auto";
    const radio = document.querySelector(
      'input[name="broadcastBrowser"][value="' + br + '"]'
    );
    if (radio) radio.checked = true;
    await loadBrowserSetting();
  }

  function updateMobileControlBarInset() {
    if (!window.matchMedia("(max-width: 768px)").matches) return;
    const bar = document.querySelector(".control-bar");
    if (!bar) return;
    const space = bar.getBoundingClientRect().height + 16;
    document.documentElement.style.setProperty("--mobile-control-bar-space", `${space}px`);
  }

  window.addEventListener("resize", () => {
    const overlay = $("#onboardingOverlay");
    if (overlay && !overlay.hidden) updateOnboardingUI();
    updateMobileControlBarInset();
  });

  async function init() {
    initTabs();
    setControlsEnabled(false);
    await fetchCsrf();
    initSocket();
    initControls();
    await loadPublicConfig();
    await updateServerStatus();
    await maybeShowOnboarding();
    setInterval(updateServerStatus, 4000);
    updatePauseButton();
    updateMobileControlBarInset();
    requestAnimationFrame(updateMobileControlBarInset);
    initCfSync();
  }

  document.addEventListener("DOMContentLoaded", init);
})();

/* ── Cloudflare 동기화 (브라우저 → Worker 직접 호출) ───────────────────── */
(function () {
  const WORKER = 'https://auto-music-player-backend.rukkit.workers.dev';
  let _jwt = null;

  function setCfStatus(msg, type = '') {
    const el = document.getElementById('cfSyncStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'cf-sync-status ' + type;
  }

  // Worker에 로그인해서 JWT 획득
  async function cfLogin() {
    const res = await fetch(`${WORKER}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: '1234' }),
    });
    const data = await res.json();
    if (!data.token) throw new Error('Worker 로그인 실패: ' + (data.error || `HTTP ${res.status}`));
    _jwt = data.token;
  }

  // Worker API 호출 (자동 로그인 + 401 시 재시도)
  async function workerFetch(method, path, body, retry = true) {
    if (!_jwt) await cfLogin();
    const res = await fetch(`${WORKER}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${_jwt}`,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401 && retry) {
      _jwt = null;
      return workerFetch(method, path, body, false);
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Worker HTTP ${res.status}`);
    return data;
  }

  // 로컬 Flask 호출
  async function localFetch(method, path, body) {
    const res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `로컬 HTTP ${res.status}`);
    return data;
  }

  // 📤 앱 동기화: 로컬 상태 읽기 → Worker에 푸시
  async function doPush() {
    const local = await localFetch('GET', '/api/local/state');
    await workerFetch('POST', '/api/sync/push', {
      playlist: local.playlist,
      settings: local.settings,
    });
    return local.playlist.length;
  }

  // 📥 데이터베이스 동기화: Worker에서 당기기 → 로컬에 적용
  async function doPull() {
    const remote = await workerFetch('GET', '/api/sync/pull');
    const result = await localFetch('POST', '/api/local/apply', {
      playlist: remote.playlist || [],
      settings: remote.settings || {},
    });
    return result.songs ?? 0;
  }

  async function loadCfConfig() {
    try {
      const cfgData = await localFetch('GET', '/api/cf/config');
      const pullEl = document.getElementById('cfAutoPull');
      if (pullEl) pullEl.checked = cfgData.cf_auto_pull_on_start !== false;
      setCfStatus('준비됨', '');
    } catch (_) {
      setCfStatus('준비됨', '');  // 연결 실패해도 버튼은 활성화
    }
  }

  window.initCfSync = function () {
    loadCfConfig();

    // 📤 앱 동기화
    const btnPush = document.getElementById('btnCfPush');
    if (btnPush) {
      btnPush.addEventListener('click', async () => {
        btnPush.disabled = true;
        setCfStatus('📤 DB에 저장 중…', 'busy');
        try {
          const count = await doPush();
          setCfStatus(`✅ ${new Date().toLocaleTimeString('ko-KR')} 저장됨 (${count}곡)`, 'ok');
        } catch (e) {
          setCfStatus('❌ ' + e.message, 'err');
          console.error('[CF push]', e);
        } finally {
          btnPush.disabled = false;
        }
      });
    }

    // 📥 데이터베이스 동기화
    const btnPull = document.getElementById('btnCfPull');
    if (btnPull) {
      btnPull.addEventListener('click', async () => {
        btnPull.disabled = true;
        setCfStatus('📥 DB에서 불러오는 중…', 'busy');
        try {
          const count = await doPull();
          setCfStatus(`✅ ${new Date().toLocaleTimeString('ko-KR')} (${count}곡)`, 'ok');
        } catch (e) {
          setCfStatus('❌ ' + e.message, 'err');
          console.error('[CF pull]', e);
        } finally {
          btnPull.disabled = false;
        }
      });
    }

    // 설정 저장 (자동 동기화 토글)
    const btnSave = document.getElementById('btnSaveCfConfig');
    if (btnSave) {
      btnSave.addEventListener('click', async () => {
        const hint = document.getElementById('cfSaveHint');
        try {
          await localFetch('POST', '/api/cf/config', {
            cf_auto_pull_on_start: document.getElementById('cfAutoPull')?.checked ?? true,
          });
          if (hint) { hint.textContent = '✅ 저장됨'; hint.style.color = '#22a35a'; }
        } catch (e) {
          if (hint) { hint.textContent = '❌ ' + e.message; hint.style.color = '#c0392b'; }
        }
        if (hint) setTimeout(() => { hint.textContent = ''; }, 3000);
      });
    }
  };

})();
