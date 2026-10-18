"use strict";
// Mục 6 — Hỗ trợ: polling tin nhắn mỗi 5s + gửi trả lời qua fetch (CSP-safe, dựng DOM bằng textContent).
(function () {
  const tokenMeta = document.querySelector('meta[name="csrf-token"]');
  const token = tokenMeta ? tokenMeta.getAttribute("content") : "";

  const chat = document.querySelector(".support-chat[data-support-thread]");
  if (!chat) return;

  const threadId = chat.getAttribute("data-support-thread");
  let lastId = parseInt(chat.getAttribute("data-last-id"), 10) || 0;
  let timer = null;
  let stopped = false;

  const form = document.getElementById("support-reply-form");
  const bodyField = document.getElementById("support-body");
  const detailUrl = form ? form.getAttribute("action") : "/support/" + threadId;

  function nearBottom() {
    return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
  }

  function scrollToBottom() {
    chat.scrollTop = chat.scrollHeight;
  }

  function appendMessage(message) {
    const article = document.createElement("article");
    article.className = "chat-bubble " + (message.mine ? "chat-bubble--mine" : "chat-bubble--them");
    const meta = document.createElement("header");
    meta.className = "chat-bubble__meta";
    meta.textContent = (message.author || "") + " · " + (message.created_at || "");
    const text = document.createElement("p");
    text.className = "chat-bubble__body mb-0";
    text.textContent = message.body || "";
    article.appendChild(meta);
    article.appendChild(text);
    chat.appendChild(article);
  }

  function handlePayload(data) {
    if (!data) return;
    const messages = data.messages || [];
    const stick = nearBottom();
    messages.forEach(function (message) {
      appendMessage(message);
      if (typeof message.id === "number" && message.id > lastId) lastId = message.id;
    });
    if (messages.length && stick) scrollToBottom();
    if (data.status === "closed") {
      stopped = true;
      if (timer) { clearInterval(timer); timer = null; }
      if (form) {
        if (bodyField) bodyField.setAttribute("disabled", "disabled");
        const submit = form.querySelector("button[type=submit]");
        if (submit) submit.setAttribute("disabled", "disabled");
      }
    }
  }

  function poll() {
    return fetch("/support/" + threadId + "/messages?after=" + lastId, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    }).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(handlePayload).catch(function () {});
  }

  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const value = bodyField ? bodyField.value.trim() : "";
      if (!value) return;
      const payload = "body=" + encodeURIComponent(value) + "&csrf_token=" + encodeURIComponent(token);
      fetch(detailUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": token,
        },
        credentials: "same-origin",
        body: payload,
      }).then(function (r) {
        if (r.ok || r.status === 303) {
          if (bodyField) bodyField.value = "";
          return poll();
        }
      }).catch(function () {
        // Nếu fetch lỗi, người dùng vẫn có thể bấm gửi lại bằng form thường.
      });
    });
  }

  scrollToBottom();
  if (!stopped) {
    timer = setInterval(function () { if (!stopped) poll(); }, 5000);
  }
})();
