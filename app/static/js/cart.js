"use strict";
// Mục 4 — Giỏ hàng: +/- tự cập nhật, xóa (xác nhận), mã giảm giá, badge realtime.
(function () {
  const tokenMeta = document.querySelector('meta[name="csrf-token"]');
  const token = tokenMeta ? tokenMeta.getAttribute("content") : "";
  const layout = document.querySelector(".cart-layout");
  if (!layout) return;

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": token,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      credentials: "same-origin",
      body: body || "",
    }).then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); });
  }

  function updateBadge(count) {
    document.querySelectorAll("header [data-cart-count]").forEach(function (e) {
      e.textContent = count; e.classList.toggle("d-none", !count);
    });
  }

  function updateSummary(d) {
    const set = function (sel, val) { const el = layout.querySelector(sel); if (el && val !== undefined && val !== null) el.textContent = val; };
    set("[data-sum-subtotal]", d.subtotal_display);
    set("[data-sum-shipping]", d.shipping_display);
    set("[data-sum-total]", d.total_display);
    const drow = layout.querySelector("[data-sum-discount-row]");
    if (drow) {
      if (d.discount_percent) {
        drow.hidden = false;
        set("[data-sum-discount]", "- " + d.discount_display);
        set("[data-sum-discount-code]", d.discount_code || "");
      } else { drow.hidden = true; }
    }
    updateBadge(d.count);
    if (!d.count) window.location.reload();
  }

  function setItem(id, qty) {
    return post("/cart/item/" + id, "quantity=" + encodeURIComponent(qty)).then(function (res) {
      const d = res.data;
      const row = layout.querySelector('[data-cart-row="' + id + '"]');
      if (d.removed && row) {
        row.remove();
      } else if (row) {
        const input = row.querySelector("[data-qty-input]");
        if (input) input.value = d.quantity;
        const line = row.querySelector("[data-cart-line]");
        if (line && d.line_total_display) line.textContent = d.line_total_display;
        const warn = row.querySelector("[data-cart-warn]");
        if (warn) { if (d.warning) { warn.textContent = d.warning; warn.hidden = false; } else { warn.hidden = true; } }
      }
      if (d.warning && window.tfToast) window.tfToast(d.warning);
      updateSummary(d);
    });
  }

  layout.addEventListener("click", function (e) {
    const dec = e.target.closest("[data-qty-dec]");
    const inc = e.target.closest("[data-qty-inc]");
    const rm = e.target.closest("[data-cart-remove]");
    if (dec || inc) {
      const input = e.target.closest("[data-qty]").querySelector("[data-qty-input]");
      let qty = (parseInt(input.value, 10) || 0) + (inc ? 1 : -1);
      if (qty < 0) qty = 0;
      setItem(input.getAttribute("data-product-id"), qty);
    } else if (rm) {
      if (window.confirm("Xóa sản phẩm này khỏi giỏ hàng?")) setItem(rm.getAttribute("data-cart-remove"), 0);
    }
  });

  layout.addEventListener("change", function (e) {
    const input = e.target.closest("[data-qty-input]");
    if (!input) return;
    let qty = parseInt(input.value, 10);
    if (isNaN(qty) || qty < 0) qty = 0;
    setItem(input.getAttribute("data-product-id"), qty);
  });

  const discountForm = layout.querySelector("[data-discount-form]");
  if (discountForm) {
    discountForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const code = discountForm.querySelector('[name="code"]').value.trim();
      const msg = discountForm.querySelector("[data-discount-msg]");
      post("/cart/discount", "code=" + encodeURIComponent(code)).then(function (res) {
        const d = res.data;
        if (msg) msg.textContent = res.ok ? (code ? "Đã áp dụng mã " + (d.discount_code || code) + "." : "Đã bỏ mã giảm giá.") : (d.error || "Mã không hợp lệ.");
        if (res.ok) updateSummary(d);
      });
    });
  }
})();
