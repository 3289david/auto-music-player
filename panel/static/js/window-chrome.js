/**
 * 네이티브 패널(127.0.0.1) — 창 버튼은 HTTP로 제어 (WebView2 API 크래시 회피)
 */
(function () {
  "use strict";

  function isNativePanelHost() {
    const h = location.hostname;
    return h === "127.0.0.1" || h === "localhost";
  }

  function sendWinCmd(action) {
    return fetch("/api/panel/window/" + action, {
      method: "POST",
      credentials: "same-origin",
    }).catch(function () {});
  }

  function initWindowChrome() {
    const chrome = document.getElementById("winChrome");
    if (!chrome) return;

    if (!isNativePanelHost()) {
      chrome.hidden = true;
      document.body.classList.remove("has-win-chrome");
      return;
    }

    document.body.classList.add("has-win-chrome");
    let maximized = false;

    document.getElementById("winMin")?.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      sendWinCmd("minimize");
    });

    const maxBtn = document.getElementById("winMax");
    maxBtn?.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      const action = maximized ? "restore" : "maximize";
      sendWinCmd(action).then(function () {
        maximized = !maximized;
        maxBtn.textContent = maximized ? "\u2750" : "\u25a1";
        maxBtn.title = maximized ? "복원" : "최대화";
      });
    });

    document.getElementById("winClose")?.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      sendWinCmd("hide");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initWindowChrome);
  } else {
    initWindowChrome();
  }
})();
