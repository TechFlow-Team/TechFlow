"use strict";
// Mục 2 — So sánh: chọn hàng loạt, thanh nổi, đồng bộ (session + localStorage mirror).
// Mục 1 — set chiều rộng biểu đồ phân bố sao qua CSSOM (hợp CSP vì không dùng style="").
(function () {
  const tokenMeta = document.querySelector('meta[name="csrf-token"]');
  const token = tokenMeta ? tokenMeta.getAttribute("content") : "";

  function toast(message) {
    if (!message) return;
    let el = document.getElementById("tf-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "tf-toast";
      el.className = "tf-toast";
      el.setAttribute("role", "status");
      el.setAttribute("aria-live", "polite");
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add("is-show");
    clearTimeout(el._timer);
    el._timer = setTimeout(function () { el.classList.remove("is-show"); }, 3000);
  }
  window.tfToast = toast;

  function postJSON(url) {
    return fetch(url, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": token },
      credentials: "same-origin",
    }).then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); });
  }

  const bar = document.getElementById("compare-bar");
  const itemsEl = bar ? bar.querySelector("[data-compare-items]") : null;

  function render(state) {
    state = state || { count: 0, ids: [], items: [] };
    const count = state.count || 0;
    const ids = state.ids || [];
    // Badge trên header
    document.querySelectorAll("header [data-compare-count]").forEach(function (e) {
      e.textContent = count;
      e.classList.toggle("d-none", count === 0);
    });
    // Thanh nổi
    if (bar) {
      bar.querySelectorAll("[data-compare-count]").forEach(function (e) { e.textContent = count; });
      if (itemsEl) {
        itemsEl.innerHTML = "";
        (state.items || []).forEach(function (it) {
          const chip = document.createElement("div");
          chip.className = "compare-chip";
          const img = document.createElement("img");
          img.src = it.image; img.alt = it.name; img.loading = "lazy";
          const name = document.createElement("span");
          name.className = "compare-chip__name"; name.textContent = it.name;
          const rm = document.createElement("button");
          rm.type = "button"; rm.className = "compare-chip__remove";
          rm.setAttribute("aria-label", "Bỏ " + it.name);
          rm.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
          rm.addEventListener("click", function () { postJSON("/compare/" + it.id + "/remove").then(function (res) { apply(res.data); }); });
          chip.appendChild(img); chip.appendChild(name); chip.appendChild(rm);
          itemsEl.appendChild(chip);
        });
      }
      const go = bar.querySelector("[data-compare-go]");
      if (go) { go.classList.toggle("disabled", count < 2); go.setAttribute("aria-disabled", count < 2 ? "true" : "false"); }
      bar.hidden = count === 0;
    }
    // Nút trên thẻ sản phẩm
    document.querySelectorAll("[data-compare-id]").forEach(function (btn) {
      const on = ids.indexOf(parseInt(btn.getAttribute("data-compare-id"), 10)) !== -1;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      const label = btn.querySelector("[data-compare-label]");
      if (label) label.textContent = on ? "Đang so sánh" : "So sánh";
    });
    try { localStorage.setItem("tf_compare", JSON.stringify(ids)); } catch (e) {}
  }

  function apply(data) {
    if (data && data.error) toast(data.error);
    render(data);
  }

  document.querySelectorAll("[data-compare-id]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const id = btn.getAttribute("data-compare-id");
      const active = btn.getAttribute("aria-pressed") === "true";
      postJSON("/compare/" + id + "/" + (active ? "remove" : "add")).then(function (res) {
        apply(res.data);
        if (res.ok && !active) toast("Đã thêm vào danh sách so sánh.");
      });
    });
  });

  if (bar) {
    const clear = bar.querySelector("[data-compare-clear]");
    if (clear) clear.addEventListener("click", function () { postJSON("/compare/clear").then(function (res) { apply(res.data); }); });
    const go = bar.querySelector("[data-compare-go]");
    if (go) go.addEventListener("click", function (e) {
      if (go.classList.contains("disabled")) { e.preventDefault(); toast("Hãy chọn ít nhất 2 sản phẩm để so sánh."); }
    });
  }

  // Trang /compare: lọc "chỉ hiện khác nhau" + nút bỏ so sánh
  const diffToggle = document.querySelector("[data-diff-toggle]");
  const compareTable = document.querySelector(".feature-comparison");
  if (diffToggle && compareTable) {
    diffToggle.addEventListener("change", function () { compareTable.classList.toggle("show-diff-only", diffToggle.checked); });
  }
  document.querySelectorAll("[data-compare-remove]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      postJSON("/compare/" + btn.getAttribute("data-compare-remove") + "/remove").then(function () { window.location.reload(); });
    });
  });

  // Mục 1 — chiều rộng cột biểu đồ phân bố sao (CSP-safe)
  document.querySelectorAll(".review-dist__fill[data-pct]").forEach(function (el) {
    el.style.width = (el.getAttribute("data-pct") || "0") + "%";
  });

  // Nạp trạng thái so sánh ban đầu
  if (bar) {
    fetch("/compare/state", { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () {});
  }
})();
