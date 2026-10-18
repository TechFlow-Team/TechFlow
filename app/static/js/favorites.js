"use strict";
// Mục 3 — Yêu thích: toggle tim tức thì (optimistic), đồng bộ trạng thái + badge header.
(function () {
  const tokenMeta = document.querySelector('meta[name="csrf-token"]');
  const token = tokenMeta ? tokenMeta.getAttribute("content") : "";
  const buttons = document.querySelectorAll("[data-favorite-id]");
  if (!buttons.length) return;

  function setState(btn, on) {
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    const icon = btn.querySelector("i.bi");
    if (icon) { icon.classList.toggle("bi-heart-fill", on); icon.classList.toggle("bi-heart", !on); }
    const label = btn.querySelector("[data-favorite-label]");
    if (label) label.textContent = on ? "Đã thích" : "Yêu thích";
  }

  function updateHeaderCount(count) {
    document.querySelectorAll("header [data-favorite-count]").forEach(function (e) {
      e.textContent = count; e.classList.toggle("d-none", !count);
    });
  }

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const id = btn.getAttribute("data-favorite-id");
      const wasOn = btn.getAttribute("aria-pressed") === "true";
      setState(btn, !wasOn); // optimistic
      fetch("/account/favorites/" + id, {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": token },
        credentials: "same-origin",
      }).then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
        .then(function (data) {
          setState(btn, data.favorited);
          updateHeaderCount(data.count);
          if (window.tfToast) window.tfToast(data.favorited ? "Đã thêm vào yêu thích." : "Đã bỏ yêu thích.");
          if (!data.favorited && document.body.classList.contains("favorites-page")) {
            const card = btn.closest(".store-card");
            if (card) card.remove();
            if (!document.querySelector(".store-grid .store-card")) window.location.reload();
          }
        })
        .catch(function () {
          setState(btn, wasOn);
          if (window.tfToast) window.tfToast("Không thể cập nhật yêu thích. Vui lòng thử lại.");
        });
    });
  });

  // Đồng bộ trạng thái tim khi tải trang
  fetch("/account/favorites/state", { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
    .then(function (data) {
      const ids = data.ids || [];
      updateHeaderCount(data.count || 0);
      buttons.forEach(function (btn) {
        setState(btn, ids.indexOf(parseInt(btn.getAttribute("data-favorite-id"), 10)) !== -1);
      });
    })
    .catch(function () {});
})();
