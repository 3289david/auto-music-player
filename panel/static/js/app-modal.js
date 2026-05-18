/**
 * 브라우저 alert/confirm 대신 패널 내 모달
 */
(function () {
  "use strict";

  const overlay = document.getElementById("appModal");
  if (!overlay) return;

  const titleEl = document.getElementById("appModalTitle");
  const msgEl = document.getElementById("appModalMessage");
  const btnOk = document.getElementById("appModalOk");
  const btnCancel = document.getElementById("appModalCancel");

  let mode = "alert";
  let resolver = null;

  function finish(value) {
    overlay.hidden = true;
    const r = resolver;
    resolver = null;
    if (r) r(value);
  }

  btnOk.addEventListener("click", () => {
    finish(mode === "confirm" ? true : undefined);
  });

  btnCancel.addEventListener("click", () => {
    if (mode === "confirm") finish(false);
  });

  overlay.addEventListener("click", (e) => {
    if (e.target !== overlay) return;
    if (mode === "confirm") finish(false);
    else finish(undefined);
  });

  document.addEventListener("keydown", (e) => {
    if (overlay.hidden || e.key !== "Escape") return;
    if (mode === "confirm") finish(false);
    else finish(undefined);
  });

  window.showAppAlert = function showAppAlert(message, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      mode = "alert";
      titleEl.textContent = opts.title || "안내";
      msgEl.textContent = message == null ? "" : String(message);
      btnOk.textContent = opts.okText || "확인";
      btnCancel.hidden = true;
      resolver = () => resolve();
      overlay.hidden = false;
      btnOk.focus();
    });
  };

  window.showAppConfirm = function showAppConfirm(message, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      mode = "confirm";
      titleEl.textContent = opts.title || "확인";
      msgEl.textContent = message == null ? "" : String(message);
      btnOk.textContent = opts.okText || "확인";
      btnCancel.textContent = opts.cancelText || "취소";
      btnCancel.hidden = false;
      resolver = (v) => resolve(!!v);
      overlay.hidden = false;
      btnOk.focus();
    });
  };
})();
