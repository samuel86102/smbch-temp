# 石門浸信會官網 Shihmen Baptist Church

教會官方網站。前台為靜態行銷頁(首頁、裝備課程、環境導覽、英文版),並內建一套
**類 WordPress 的活動發布後台**:管理員登入後可發布「標題 + 所見即所得內文 + 圖片」的活動,
公開網址為 `/events?id=xxx`。

整站由 **Python (Flask)** 統一服務 —— 既有靜態頁與動態活動頁皆由同一個應用程式提供。

---

## 技術棧

| 層 | 技術 |
|---|---|
| 後端 | Python 3 + Flask |
| 資料庫 | MariaDB / MySQL(獨立資料庫 `smbc_website`) |
| 資料庫驅動 | PyMySQL |
| 前端 | 靜態 HTML + Tailwind CSS (CDN) + Font Awesome |
| 內文編輯器 | Quill 2 (WYSIWYG) |
| 內文清洗 | bleach(防 XSS) |
| 密碼雜湊 | Werkzeug `scrypt` |
| 設定管理 | python-dotenv (`.env`) |

---

## 專案結構

```
.
├── app.py              # Flask 主程式:路由(靜態頁 / events / login / admin)
├── db.py               # 資料庫連線 helper(讀 .env)
├── create_admin.py     # CLI:建立 / 重設後台管理員帳號
├── schema.sql          # 資料表定義(user + event)
├── requirements.txt    # Python 相依套件
├── .env                # 環境設定(不進 git)
├── templates/          # Jinja2 模板(動態頁)
│   ├── base.html           # 共用版型 + 導覽列 + footer
│   ├── events_list.html    # /events 活動列表
│   ├── event_detail.html   # /events?id=xxx 單篇活動
│   ├── login.html          # /login 後台登入
│   └── admin/
│       ├── dashboard.html  # /admin 管理列表
│       └── edit.html       # 新增 / 編輯活動(Quill 編輯器)
├── static/uploads/     # 活動上傳圖片(不進 git)
│
├── index.html          # 既有靜態頁:中文首頁
├── courses.html        # 既有靜態頁:裝備課程
├── tour.html           # 既有靜態頁:環境導覽
├── en/                 # 既有靜態頁:英文版 (index / courses)
├── image/              # 網站圖片資產(logo、牧者照、導覽照…)
└── compress_images.py  # 工具:壓縮 image/tour/ 下過大的圖片(需 Pillow)
```

---

## 資料庫

獨立於教會內部管理系統(`smbc_db`)的**網站專用資料庫** `smbc_website`,僅含兩張表:

### `user` — 後台登入帳號
| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int PK | |
| `account` | varchar(50) UNIQUE | 登入帳號 |
| `pwd` | varchar(255) | Werkzeug scrypt 雜湊 |
| `updatetime` | datetime | |

### `event` — 活動發布
| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int PK | 活動編號(對應 `/events?id=`) |
| `title` | varchar(255) | 標題 |
| `content` | longtext | WYSIWYG 內文(已清洗的 HTML) |
| `image_path` | varchar(255) | 封面圖相對路徑(`uploads/xxx.jpg`) |
| `published` | tinyint(1) | 1=已發布 0=草稿 |
| `author_id` | int FK→user.id | 發布者 |
| `createtime` | datetime | 建立時間 |
| `updatetime` | datetime | 最後更新 |

> 建表 SQL 見 `schema.sql`(使用 `CREATE TABLE IF NOT EXISTS`,可安全重跑)。

---

## 環境設定 `.env`

```dotenv
DB_URL=資料庫主機位址
DB_PORT=3306
DB_USER=資料庫使用者
DB_PASSWD=資料庫密碼
DB_NAME=smbc_website
SECRET_KEY=Flask session 加密金鑰
```

`SECRET_KEY` 產生方式:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> ⚠️ `.env` 含機密,已列入 `.gitignore`,**請勿提交至版本庫**。

---

## 安裝與啟動

```bash
# 1. 建立虛擬環境並安裝套件
python -m venv venv
./venv/bin/pip install -r requirements.txt

# 2. 建立資料表(若尚未建立)
./venv/bin/python -c "from db import get_connection; \
  conn=get_connection(); cur=conn.cursor(); \
  [cur.execute(s) for s in open('schema.sql').read().split(';') if s.strip()]; \
  conn.close()"
# 或直接用 mysql/mariadb 客戶端匯入 schema.sql

# 3. 建立第一個管理員帳號(互動式輸入帳密)
./venv/bin/python create_admin.py
#   也可指定帳號:./venv/bin/python create_admin.py admin

# 4. 啟動開發伺服器
./venv/bin/python app.py
```

啟動後開啟 <http://localhost:5000/>。

> 連線 MariaDB 時若用 `mariadb` 客戶端,該伺服器不支援 SSL,需加 `--skip-ssl`。
> PyMySQL 預設不啟用 SSL,故應用程式端無需特別設定。

---

## 路由總覽

| 路徑 | 方法 | 權限 | 說明 |
|---|---|---|---|
| `/` | GET | 公開 | 首頁(index.html) |
| `/courses.html`、`/tour.html`、`/en/...`、`/image/...` | GET | 公開 | 既有靜態頁 / 資產 |
| `/events` | GET | 公開 | 已發布活動列表 |
| `/events?id=<id>` | GET | 公開 | 單篇活動(未發布或不存在回 404) |
| `/login` | GET/POST | 公開 | 後台登入 |
| `/logout` | GET | — | 登出 |
| `/admin` | GET | 需登入 | 活動管理列表 |
| `/admin/new` | GET/POST | 需登入 | 新增活動 |
| `/admin/edit/<id>` | GET/POST | 需登入 | 編輯活動 |
| `/admin/delete/<id>` | POST | 需登入 | 刪除活動 |

---

## 發布活動流程

1. 前往 `/login` 以管理員帳號登入。
2. 進入 `/admin`,點「新增活動」。
3. 填寫**標題**、用 **Quill 編輯器**撰寫內文、上傳**封面圖片**。
4. 勾選「立即發布」(取消勾選則存為草稿)後儲存。
5. 公開頁面即出現於 `/events` 列表,單篇網址為 `/events?id=<id>`。

**安全性**:內文以 `bleach` 白名單清洗(`app.py` 的 `ALLOWED_TAGS` / `ALLOWED_ATTRS`),
`<script>` 等危險標籤會被移除;圖片僅允許 `jpg/png/webp/gif`,檔名以 UUID 重新命名,上傳上限 16MB。

---

## 正式部署(建議)

開發伺服器(`app.py` 的 `app.run`)**不可用於正式環境**。建議:

```bash
./venv/bin/pip install gunicorn
./venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
```

前面再以 Nginx 反向代理並處理 TLS。注意事項:

- `static/uploads/` 需可寫,且應納入備份。
- `.env` 部署到伺服器,權限設為僅應用程式可讀。
- `SECRET_KEY` 正式環境務必使用獨立且保密的值。

---

## 圖片壓縮工具

`compress_images.py` 會把 `image/tour/` 下超過 1MB 的圖片壓縮至 1MB 以內(需 `Pillow`):

```bash
pip install Pillow
python compress_images.py
```
