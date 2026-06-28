"""石門浸信會 chatbot —— 以 markdown 檔案為來源的簡易 RAG（不用向量資料庫）。

流程：
1. classify()：用 LLM 判斷問題屬於哪些類別（對應 knowledge/ 下的子資料夾）。
2. read_categories()：讀取對應資料夾內所有 .md 檔，串接成「參考資料」。
3. answer_stream()：把系統提示 + 參考資料 + 問題交給 LLM，串流回答。

所有 LLM 呼叫透過 OpenRouter，API key 僅存在後端（.env）。
"""
import os
import re
import json

import bleach
import requests
from flask import Blueprint, request, Response, jsonify

ROOT = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.path.join(ROOT, "knowledge")
EVENTS_DIR = os.path.join(KNOWLEDGE_DIR, "events")
SYSTEM_PROMPT_FILE = os.path.join(KNOWLEDGE_DIR, "_system_prompt.md")
CATEGORIES_FILE = os.path.join(KNOWLEDGE_DIR, "categories.json")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# 檢索內容總長上限（字元），避免 prompt 過大
MAX_CONTEXT_CHARS = 8000
# 單次提問長度上限
MAX_QUESTION_CHARS = 1000

DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash")
CLASSIFY_MODEL = os.environ.get("OPENROUTER_CLASSIFY_MODEL", DEFAULT_MODEL)

DEFAULT_SYSTEM_PROMPT = (
    "你是石門浸信會官方網站的客服小幫手，請依提供的參考資料親切、簡潔地回答訪客問題；"
    "若資料中沒有答案，請誠實告知並建議聯絡教會辦公室，不要編造。請用提問者的語言回覆。"
)

chatbot_bp = Blueprint("chatbot", __name__)


# ---------- 知識庫讀取 ----------
def load_categories():
    """讀 categories.json，回傳 [{id, name, desc}, ...]。"""
    try:
        with open(CATEGORIES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _category_ids():
    return {c["id"] for c in load_categories()}


def load_system_prompt():
    try:
        with open(SYSTEM_PROMPT_FILE, encoding="utf-8") as f:
            text = f.read().strip()
        return text or DEFAULT_SYSTEM_PROMPT
    except OSError:
        return DEFAULT_SYSTEM_PROMPT


def read_category(cat_id):
    """讀取單一類別資料夾內所有 .md（events 依檔案修改時間新→舊）。回傳純文字。"""
    if cat_id not in _category_ids():
        return ""
    folder = os.path.join(KNOWLEDGE_DIR, cat_id)
    if not os.path.isdir(folder):
        return ""
    files = [
        os.path.join(folder, fn)
        for fn in os.listdir(folder)
        if fn.endswith(".md")
    ]
    # events：最新優先；其他類別：檔名排序，輸出穩定
    if cat_id == "events":
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    else:
        files.sort()

    parts = []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                parts.append(f.read().strip())
        except OSError:
            continue
    return "\n\n".join(parts)


def read_categories(cat_ids):
    """串接多個類別的內容，套用總長上限。"""
    blocks = []
    total = 0
    for cid in cat_ids:
        text = read_category(cid)
        if not text:
            continue
        if total + len(text) > MAX_CONTEXT_CHARS:
            text = text[: max(0, MAX_CONTEXT_CHARS - total)]
        blocks.append(text)
        total += len(text)
        if total >= MAX_CONTEXT_CHARS:
            break
    return "\n\n---\n\n".join(blocks)


# ---------- 活動（events）→ markdown 自動同步 ----------
def _html_to_text(html):
    """把活動內文的 HTML 去標籤、轉純文字（保留段落換行）。"""
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", html or "")
    text = re.sub(r"(?i)</\s*(p|div|li|h[1-6])\s*>", "\n", text)
    text = bleach.clean(text, tags=[], strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _event_md_path(event_id):
    name = re.sub(r"[^A-Za-z0-9_-]", "", str(event_id))
    if not name:
        return None
    return os.path.join(EVENTS_DIR, f"{name}.md")


def sync_event_md(event):
    """把一筆已發布活動寫成 knowledge/events/<id>.md。event 為 dict-like。"""
    path = _event_md_path(event["id"])
    if not path:
        return
    os.makedirs(EVENTS_DIR, exist_ok=True)
    created = event.get("createtime")
    date_str = created.strftime("%Y-%m-%d") if hasattr(created, "strftime") else ""
    body = _html_to_text(event.get("content", ""))
    lines = [f"# {event.get('title', '').strip()}"]
    if date_str:
        lines.append(f"\n發布日期：{date_str}")
    if body:
        lines.append(f"\n{body}")
    lines.append(f"\n活動連結：/events/{event['id']}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")


def remove_event_md(event_id):
    """移除某活動的 markdown（取消發布或刪除時）。"""
    path = _event_md_path(event_id)
    if path and os.path.exists(path):
        os.remove(path)


# ---------- OpenRouter ----------
def _headers():
    key = os.environ.get("OPENROUTER_API_KEY", "")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://smbch.org",
        "X-Title": "Shihmen Baptist Church Chatbot",
    }


def openrouter_chat(messages, model, stream=False, temperature=0.3, timeout=60):
    """呼叫 OpenRouter chat completions。stream=True 時回傳 requests 串流回應。"""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    return requests.post(
        OPENROUTER_URL,
        headers=_headers(),
        json=payload,
        stream=stream,
        timeout=timeout,
    )


# ---------- 步驟一：分類 ----------
def classify(question):
    """用 LLM 判斷問題對應的類別 id 清單；失敗或判不出來時回傳全部類別（fallback 全讀）。"""
    categories = load_categories()
    all_ids = [c["id"] for c in categories]
    if not categories:
        return all_ids

    catalog = "\n".join(f'- {c["id"]}：{c["desc"]}' for c in categories)
    sys = (
        "你是分類器。根據使用者的問題，從以下類別中挑出最相關的 1 至 2 個類別。\n"
        f"{catalog}\n\n"
        "只輸出一個 JSON 陣列，內容是類別 id（字串），例如 [\"worship\"]。"
        "若問題與所有類別都無關，輸出 []。不要輸出其他文字。"
    )
    try:
        resp = openrouter_chat(
            [
                {"role": "system", "content": sys},
                {"role": "user", "content": question},
            ],
            model=CLASSIFY_MODEL,
            stream=False,
            temperature=0,
            timeout=30,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return all_ids  # 分類失敗 → 全讀

    match = re.search(r"\[.*?\]", content, re.DOTALL)
    if not match:
        return all_ids
    try:
        ids = json.loads(match.group(0))
    except json.JSONDecodeError:
        return all_ids

    valid = [i for i in ids if i in set(all_ids)]
    return valid or all_ids


# ---------- 步驟三：回答（串流）----------
def answer_stream(question, context, lang="zh"):
    """串流產生回答文字片段（generator of str）。"""
    lang_hint = "請用繁體中文回答。" if lang.startswith("zh") else "Please answer in English."
    system_content = (
        f"{load_system_prompt()}\n\n"
        f"{lang_hint}\n\n"
        f"# 參考資料\n{context if context.strip() else '（目前沒有可用的參考資料）'}"
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]
    resp = openrouter_chat(messages, model=DEFAULT_MODEL, stream=True, temperature=0.3)
    resp.raise_for_status()
    resp.encoding = "utf-8"  # 確保中文以 UTF-8 解碼，避免亂碼

    for raw in resp.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        data = raw[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
            delta = chunk["choices"][0]["delta"].get("content")
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
        if delta:
            yield delta


# ---------- API 路由 ----------
def _sse(obj):
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@chatbot_bp.route("/api/chat", methods=["POST"])
def api_chat():
    if not os.environ.get("OPENROUTER_API_KEY"):
        return jsonify(error="伺服器尚未設定 OPENROUTER_API_KEY"), 503

    data = request.get_json(silent=True) or {}
    question = (data.get("message") or "").strip()
    lang = (data.get("lang") or "zh")[:5]
    if not question:
        return jsonify(error="請輸入問題"), 400
    if len(question) > MAX_QUESTION_CHARS:
        question = question[:MAX_QUESTION_CHARS]

    def generate():
        try:
            cat_ids = classify(question)
            # 後端 log：方便觀察 RAG 流程
            print(f"[chatbot] Q={question!r} -> categories={cat_ids}", flush=True)
            yield _sse({"categories": cat_ids})

            context = read_categories(cat_ids)
            for delta in answer_stream(question, context, lang):
                yield _sse({"delta": delta})
            yield _sse({"done": True})
        except requests.exceptions.RequestException as e:
            print(f"[chatbot] OpenRouter error: {e}", flush=True)
            yield _sse({"error": "抱歉，目前無法連線到問答服務，請稍後再試，或來電 (03) 471-2542。"})
        except Exception as e:  # noqa: BLE001
            print(f"[chatbot] error: {e}", flush=True)
            yield _sse({"error": "抱歉，發生了一點問題，請稍後再試。"})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
