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
    flash("活動已刪除")
    return redirect(url_for("admin"))


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
                try:
                    cur.execute(
                        "INSERT INTO `event` (id, title, content, image_path, published, author_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (gen_id(), title, content, image_path, published, session.get("user_id")),
                    )
                    break
                except pymysql.err.IntegrityError:
                    continue
    conn.close()


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
    app.run(host="0.0.0.0", port=5000, debug=True)
