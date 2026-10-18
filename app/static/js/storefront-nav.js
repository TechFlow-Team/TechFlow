"use strict";
// Mục 7 — menu mobile (hamburger). Không phụ thuộc framework.
(function () {
  var toggle = document.querySelector("[data-nav-toggle]");
  var nav = document.getElementById("store-nav");
  if (!toggle || !nav) return;
  toggle.addEventListener("click", function () {
    var open = nav.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Đóng menu" : "Mở menu");
  });
})();
