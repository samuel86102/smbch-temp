/* 石門浸信會 floating chatbot —— 自製 RAG 問答前端
 * 取代原本的 Dify 嵌入。後端：POST /api/chat（SSE 串流）。
 */
(function () {
  "use strict";

  // 偵測語言：依 <html lang> 或路徑 /en/
  var isEN =
    location.pathname.indexOf("/en/") === 0 ||
    /^en/i.test(document.documentElement.lang || "");
  var L = isEN
    ? {
        title: "Ask SMBC",
        subtitle: "Church assistant",
        placeholder: "Type your question…",
        greeting:
          "Hi! I'm the Shihmen Baptist Church assistant. Ask me about service times, courses, location, giving, or recent events.",
        thinking: "Thinking…",
        send: "Send",
        open: "Chat with us",
      }
    : {
        title: "石門小幫手",
        subtitle: "教會線上問答",
        placeholder: "輸入您的問題…",
        greeting:
          "您好！我是石門浸信會的小幫手 🙂 可以問我聚會時間、裝備課程、環境位置、奉獻方式或最新活動喔！",
        thinking: "思考中…",
        send: "送出",
        open: "有問題嗎？",
      };

  var PRIMARY = "#3A5A40";

  // ---------- 樣式 ----------
  var css =
    "" +
    "#smbc-chat-btn{position:fixed;right:20px;bottom:20px;z-index:9998;width:60px;height:60px;border-radius:50%;background:" +
    PRIMARY +
    ";color:#fff;border:none;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.25);font-size:24px;display:flex;align-items:center;justify-content:center;transition:transform .2s,box-shadow .2s;}" +
    "#smbc-chat-btn:hover{transform:translateY(-2px);box-shadow:0 12px 28px rgba(0,0,0,.3);}" +
    "#smbc-chat-panel{position:fixed;right:20px;bottom:92px;z-index:9999;width:24rem;max-width:calc(100vw - 32px);height:40rem;max-height:calc(100vh - 120px);background:#fff;border-radius:18px;box-shadow:0 20px 60px rgba(0,0,0,.28);display:none;flex-direction:column;overflow:hidden;font-family:'Noto Sans TC',system-ui,sans-serif;}" +
    "#smbc-chat-panel.open{display:flex;animation:smbc-in .22s ease;}" +
    "@keyframes smbc-in{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:translateY(0);}}" +
    ".smbc-head{background:" +
    PRIMARY +
    ";color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px;}" +
    ".smbc-head .smbc-logo{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.18);display:flex;align-items:center;justify-content:center;font-size:16px;}" +
    ".smbc-head h3{margin:0;font-size:15px;font-weight:700;line-height:1.2;}" +
    ".smbc-head p{margin:0;font-size:11px;opacity:.85;}" +
    ".smbc-close{margin-left:auto;background:none;border:none;color:#fff;font-size:20px;cursor:pointer;opacity:.85;line-height:1;}" +
    ".smbc-close:hover{opacity:1;}" +
    ".smbc-body{flex:1;overflow-y:auto;padding:16px;background:#FAF9F6;display:flex;flex-direction:column;gap:12px;}" +
    ".smbc-msg{max-width:85%;padding:10px 13px;border-radius:14px;font-size:14px;line-height:1.6;word-wrap:break-word;overflow-wrap:break-word;}" +
    ".smbc-msg.bot{background:#fff;color:#333;border:1px solid #eee;border-bottom-left-radius:4px;align-self:flex-start;}" +
    ".smbc-msg.user{background:" +
    PRIMARY +
    ";color:#fff;border-bottom-right-radius:4px;align-self:flex-end;}" +
    ".smbc-msg a{color:" +
    PRIMARY +
    ";text-decoration:underline;}" +
    ".smbc-msg.user a{color:#fff;}" +
    ".smbc-msg p{margin:0 0 6px;}.smbc-msg p:last-child{margin-bottom:0;}" +
    ".smbc-msg ul{margin:6px 0;padding-left:18px;}" +
    ".smbc-dots span{display:inline-block;width:6px;height:6px;margin:0 1px;border-radius:50%;background:#bbb;animation:smbc-blink 1.2s infinite both;}" +
    ".smbc-dots span:nth-child(2){animation-delay:.2s;}.smbc-dots span:nth-child(3){animation-delay:.4s;}" +
    "@keyframes smbc-blink{0%,80%,100%{opacity:.2;}40%{opacity:1;}}" +
    ".smbc-foot{border-top:1px solid #eee;padding:10px;display:flex;gap:8px;background:#fff;}" +
    ".smbc-foot textarea{flex:1;resize:none;border:1px solid #ddd;border-radius:12px;padding:9px 12px;font-size:14px;font-family:inherit;max-height:90px;outline:none;}" +
    ".smbc-foot textarea:focus{border-color:" +
    PRIMARY +
    ";}" +
    ".smbc-foot button{background:" +
    PRIMARY +
    ";color:#fff;border:none;border-radius:12px;width:42px;cursor:pointer;font-size:16px;flex-shrink:0;}" +
    ".smbc-foot button:disabled{opacity:.5;cursor:not-allowed;}";

  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  // ---------- DOM ----------
  var btn = document.createElement("button");
  btn.id = "smbc-chat-btn";
  btn.setAttribute("aria-label", L.open);
  btn.innerHTML = '<i class="fas fa-comment-dots"></i>';

  var panel = document.createElement("div");
  panel.id = "smbc-chat-panel";
  panel.innerHTML =
    '<div class="smbc-head">' +
    '<div class="smbc-logo"><i class="fas fa-cross"></i></div>' +
    "<div><h3>" +
    L.title +
    "</h3><p>" +
    L.subtitle +
    "</p></div>" +
    '<button class="smbc-close" aria-label="close">&times;</button>' +
    "</div>" +
    '<div class="smbc-body" id="smbc-body"></div>' +
    '<div class="smbc-foot">' +
    '<textarea id="smbc-input" rows="1" placeholder="' +
    L.placeholder +
    '"></textarea>' +
    '<button id="smbc-send" aria-label="' +
    L.send +
    '"><i class="fas fa-paper-plane"></i></button>' +
    "</div>";

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  var body = panel.querySelector("#smbc-body");
  var input = panel.querySelector("#smbc-input");
  var sendBtn = panel.querySelector("#smbc-send");
  var greeted = false;
  var busy = false;

  // ---------- 工具 ----------
  function escapeHTML(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // 極簡 markdown → HTML（粗體、連結、清單、換行）
  function mdToHtml(text) {
    var html = escapeHTML(text);
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]*)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>'
    );
    // 裸網址
    html = html.replace(
      /(^|[^"=])(https?:\/\/[^\s<]+)/g,
      '$1<a href="$2" target="_blank" rel="noopener">$2</a>'
    );
    var lines = html.split("\n");
    var out = [];
    var inList = false;
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i];
      if (/^\s*[-*]\s+/.test(ln)) {
        if (!inList) {
          out.push("<ul>");
          inList = true;
        }
        out.push("<li>" + ln.replace(/^\s*[-*]\s+/, "") + "</li>");
      } else {
        if (inList) {
          out.push("</ul>");
          inList = false;
        }
        if (ln.trim() === "") out.push("<br>");
        else out.push("<p>" + ln + "</p>");
      }
    }
    if (inList) out.push("</ul>");
    return out.join("");
  }

  function addMsg(role, html) {
    var el = document.createElement("div");
    el.className = "smbc-msg " + role;
    el.innerHTML = html;
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
    return el;
  }

  function scroll() {
    body.scrollTop = body.scrollHeight;
  }

  // ---------- 開合 ----------
  function open() {
    panel.classList.add("open");
    if (!greeted) {
      addMsg("bot", mdToHtml(L.greeting));
      greeted = true;
    }
    setTimeout(function () {
      input.focus();
    }, 100);
  }
  function close() {
    panel.classList.remove("open");
  }
  btn.addEventListener("click", function () {
    panel.classList.contains("open") ? close() : open();
  });
  panel.querySelector(".smbc-close").addEventListener("click", close);

  // textarea 自動長高
  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 90) + "px";
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendBtn.addEventListener("click", send);

  // ---------- 送出 + 串流接收 ----------
  function send() {
    var q = input.value.trim();
    if (!q || busy) return;
    busy = true;
    sendBtn.disabled = true;

    addMsg("user", escapeHTML(q).replace(/\n/g, "<br>"));
    input.value = "";
    input.style.height = "auto";

    // 思考中泡泡
    var botEl = addMsg(
      "bot",
      '<span class="smbc-dots"><span></span><span></span><span></span></span>'
    );
    var answer = "";

    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: q, lang: isEN ? "en" : "zh" }),
    })
      .then(function (resp) {
        if (!resp.ok || !resp.body) {
          throw new Error("network");
        }
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";

        function pump() {
          return reader.read().then(function (res) {
            if (res.done) {
              finish();
              return;
            }
            buffer += decoder.decode(res.value, { stream: true });
            var parts = buffer.split("\n\n");
            buffer = parts.pop();
            parts.forEach(handleEvent);
            return pump();
          });
        }
        return pump();
      })
      .catch(function () {
        if (!answer) {
          botEl.innerHTML = mdToHtml(
            isEN
              ? "Sorry, something went wrong. Please try again later or call (03) 471-2542."
              : "抱歉，發生了一點問題，請稍後再試，或來電 (03) 471-2542。"
          );
        }
        finish();
      });

    function handleEvent(block) {
      var line = block.trim();
      if (line.indexOf("data:") !== 0) return;
      var payload = line.slice(5).trim();
      if (!payload) return;
      var obj;
      try {
        obj = JSON.parse(payload);
      } catch (e) {
        return;
      }
      if (obj.delta) {
        answer += obj.delta;
        botEl.innerHTML = mdToHtml(answer);
        scroll();
      } else if (obj.error) {
        botEl.innerHTML = mdToHtml(obj.error);
        scroll();
      }
    }

    function finish() {
      busy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }
})();
