"""石門浸信會網站後端（Flask）。

職責：
- 服務既有靜態頁（index/courses/tour/en + image 資產）
- 公開活動頁 /events 與 /events?id=xxx
- 後台 /login、/admin（需登入）發布活動：標題 + WYSIWYG 內文 + 圖片
資料庫：獨立的 smbc_website（見 db.py / .env）。
"""
import os
import uuid
import secrets
import string
from datetime import datetime
from functools import wraps

import bleach
import pymysql
from flask import (
    Flask, request, session, redirect, url_for, render_template,
    send_from_directory, abort, flash,
)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from db import get_connection
from chatbot import (
    chatbot_bp, sync_event_md, remove_event_md,
    load_categories, load_system_prompt,
    KNOWLEDGE_DIR, SYSTEM_PROMPT_FILE,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(ROOT, "static", "uploads")
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
os.makedirs(UPLOAD_DIR, exist_ok=True)

# WYSIWYG 內文允許的 HTML 標籤 / 屬性（防 XSS）
ALLOWED_TAGS = [
    "p", "br", "span", "div", "h1", "h2", "h3", "h4",
    "strong", "b", "em", "i", "u", "s", "blockquote",
    "ul", "ol", "li", "a", "img", "pre", "code", "hr",
]
ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
    "span": ["style"],
    "p": ["style"],
    "div": ["style"],
}

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ["SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB 上傳上限
app.register_blueprint(chatbot_bp)  # /api/chat（RAG 問答）

# 活動 id：隨機 base62 短碼（非自增、不可列舉），用於 /events/<id>
_ID_ALPHABET = string.ascii_letters + string.digits


def gen_id(n=12):
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(n))


# ---------- 認證 ----------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        account = request.form.get("account", "").strip()
        pwd = request.form.get("password", "")
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id, account, pwd FROM `user` WHERE account = %s", (account,))
            user = cur.fetchone()
        conn.close()
        if user and check_password_hash(user["pwd"], pwd):
            session["user_id"] = user["id"]
            session["account"] = user["account"]
            return redirect(request.args.get("next") or url_for("admin"))
        flash("帳號或密碼錯誤")
        return render_template("login.html"), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- 公開活動頁 ----------
@app.route("/events")
def events():
    # 向後相容：舊網址 /events?id=xxx → 301 轉到 /events/<id>
    legacy_id = request.args.get("id")
    if legacy_id:
        return redirect(url_for("event_detail", event_id=legacy_id), code=301)
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, image_path, createtime FROM `event` "
            "WHERE published = 1 ORDER BY createtime DESC"
        )
        items = cur.fetchall()
    conn.close()
    return render_template("events_list.html", events=items)


@app.route("/events/<event_id>")
def event_detail(event_id):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM `event` WHERE id = %s AND published = 1", (event_id,)
        )
        event = cur.fetchone()
    conn.close()
    if not event:
        abort(404)
    return render_template("event_detail.html", event=event)


# ---------- 後台 ----------
@app.route("/admin")
@login_required
def admin():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, published, createtime, updatetime FROM `event` "
            "ORDER BY createtime DESC"
        )
        items = cur.fetchall()
    conn.close()
    return render_template("admin/dashboard.html", events=items)


@app.route("/admin/new", methods=["GET", "POST"])
@login_required
def admin_new():
    if request.method == "POST":
        _save_event(None)
        flash("活動已新增")
        return redirect(url_for("admin"))
    return render_template("admin/edit.html", event=None)


@app.route("/admin/edit/<event_id>", methods=["GET", "POST"])
@login_required
def admin_edit(event_id):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM `event` WHERE id = %s", (event_id,))
        event = cur.fetchone()
    conn.close()
    if not event:
        abort(404)
    if request.method == "POST":
        _save_event(event)
        flash("活動已更新")
        return redirect(url_for("admin"))
    return render_template("admin/edit.html", event=event)


@app.route("/admin/delete/<event_id>", methods=["POST"])
@login_required
def admin_delete(event_id):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM `event` WHERE id = %s", (event_id,))
    conn.close()
    remove_event_md(event_id)  # 同步移除知識庫 markdown
    flash("活動已刪除")
    return redirect(url_for("admin"))


# ---------- 後台：知識庫管理 ----------
def _safe_knowledge_path(category, filename, must_exist=False):
    """把 category/filename 解析為 knowledge/ 內的安全路徑；非法則回 None。"""
    valid = {c["id"] for c in load_categories() if c["id"] != "events"}
    if category not in valid:
        return None
    fname = secure_filename(filename or "")
    if not fname:
        return None
    if not fname.endswith(".md"):
        fname += ".md"
    folder = os.path.join(KNOWLEDGE_DIR, category)
    path = os.path.abspath(os.path.join(folder, fname))
    # 確保仍在該類別資料夾內（防目錄穿越）
    if os.path.commonpath([path, os.path.abspath(folder)]) != os.path.abspath(folder):
        return None
    if must_exist and not os.path.isfile(path):
        return None
    return path


@app.route("/admin/knowledge")
@login_required
def admin_knowledge():
    cats = []
    for c in load_categories():
        folder = os.path.join(KNOWLEDGE_DIR, c["id"])
        files = sorted(f for f in os.listdir(folder) if f.endswith(".md")) \
            if os.path.isdir(folder) else []
        cats.append({**c, "files": files, "readonly": c["id"] == "events"})
    return render_template("admin/knowledge.html", categories=cats)


@app.route("/admin/knowledge/edit", methods=["GET", "POST"])
@login_required
def admin_knowledge_edit():
    if request.method == "POST":
        category = request.form.get("category", "")
        filename = request.form.get("filename", "")
        content = request.form.get("content", "")
        path = _safe_knowledge_path(category, filename)
        if not path:
            flash("無效的類別或檔名")
            return redirect(url_for("admin_knowledge"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        flash("知識文件已儲存")
        return redirect(url_for("admin_knowledge"))

    category = request.args.get("category", "")
    filename = request.args.get("filename", "")
    content = ""
    if filename:
        path = _safe_knowledge_path(category, filename, must_exist=True)
        if path:
            with open(path, encoding="utf-8") as f:
                content = f.read()
    return render_template(
        "admin/knowledge_edit.html",
        category=category, filename=filename, content=content,
        categories=[c for c in load_categories() if c["id"] != "events"],
    )


@app.route("/admin/knowledge/delete", methods=["POST"])
@login_required
def admin_knowledge_delete():
    path = _safe_knowledge_path(
        request.form.get("category", ""), request.form.get("filename", ""),
        must_exist=True,
    )
    if path:
        os.remove(path)
        flash("知識文件已刪除")
    else:
        flash("找不到要刪除的文件")
    return redirect(url_for("admin_knowledge"))


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        content = request.form.get("system_prompt", "")
        with open(SYSTEM_PROMPT_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        flash("System Prompt 已更新")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html", system_prompt=load_system_prompt())


# ---------- 啟動時補生成既有已發布活動的 markdown ----------
def backfill_event_md():
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, content, createtime FROM `event` WHERE published = 1"
            )
            rows = cur.fetchall()
        conn.close()
        for row in rows:
            sync_event_md(row)
    except Exception as e:  # noqa: BLE001 - 啟動補檔失敗不應擋住伺服器
        print(f"[chatbot] backfill_event_md skipped: {e}", flush=True)


def _save_event(existing):
    """處理新增 / 編輯活動的表單，含圖片上傳與內文清洗。"""
    title = request.form.get("title", "").strip()
    raw_content = request.form.get("content", "")
    content = bleach.clean(
        raw_content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True
    )
    published = 1 if request.form.get("published") else 0

    image_path = existing["image_path"] if existing else None
    file = request.files.get("image")
    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_EXT:
            flash("圖片格式不支援（僅 jpg/png/webp/gif）")
        else:
            fname = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(UPLOAD_DIR, secure_filename(fname)))
            image_path = f"uploads/{fname}"

    conn = get_connection()
    event_id = existing["id"] if existing else None
    with conn.cursor() as cur:
        if existing:
            cur.execute(
                "UPDATE `event` SET title=%s, content=%s, image_path=%s, published=%s "
                "WHERE id=%s",
                (title, content, image_path, published, existing["id"]),
            )
        else:
            # 隨機 id，極罕見碰撞時重試
            for _ in range(5):
                event_id = gen_id()
                try:
                    cur.execute(
                        "INSERT INTO `event` (id, title, content, image_path, published, author_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (event_id, title, content, image_path, published, session.get("user_id")),
                    )
                    break
                except pymysql.err.IntegrityError:
                    event_id = None
                    continue
    conn.close()

    # 同步知識庫：已發布 → 生成 events markdown；未發布 → 移除
    if event_id:
        if published:
            createtime = existing["createtime"] if existing else datetime.now()
            sync_event_md({
                "id": event_id, "title": title,
                "content": content, "createtime": createtime,
            })
        else:
            remove_event_md(event_id)


# ---------- 既有靜態頁 ----------
@app.route("/")
def home():
    return send_from_directory(ROOT, "index.html")


@app.route("/courses.html")
def courses():
    return send_from_directory(ROOT, "courses.html")


@app.route("/tour.html")
def tour():
    return send_from_directory(ROOT, "tour.html")


@app.route("/index.html")
def index_html():
    return send_from_directory(ROOT, "index.html")


@app.route("/en/<path:filename>")
def en_pages(filename):
    return send_from_directory(os.path.join(ROOT, "en"), filename)


@app.route("/image/<path:filename>")
def images(filename):
    return send_from_directory(os.path.join(ROOT, "image"), filename)


if __name__ == "__main__":
    backfill_event_md()  # 確保既有已發布活動可被 chatbot 查詢
    app.run(host="0.0.0.0", port=5000, debug=True)
