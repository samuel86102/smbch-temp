# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Official website for 石門浸信會 (Shihmen Baptist Church). A single Flask app serves
three things from one process:

1. **Existing static marketing pages** — `index.html`, `courses.html`, `tour.html`, and
   the English versions under `en/`. These are hand-written full-page HTML files served
   verbatim via `send_from_directory` (not Jinja templates).
2. **A WordPress-like events backend** — admins log in and publish events (title +
   WYSIWYG body + cover image). Public URLs are `/events/<id>` where `id` is a random
   base62 short code (non-enumerable).
3. **A markdown-file RAG chatbot** — `/api/chat`, backed by markdown files in
   `knowledge/`, calling LLMs through OpenRouter.

UI text, comments, and commit messages are in Traditional Chinese; keep that convention.

## Commands

```bash
# Setup
python -m venv venv
./venv/bin/pip install -r requirements.txt

# Create / reset an admin login (interactive password prompt)
./venv/bin/python create_admin.py [account]

# Run (dev server — do NOT use in production)
./venv/bin/python app.py            # serves on 0.0.0.0:5000, debug=True

# Run (production)
./venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app

# Compress oversized tour images in-place (>1MB → <1MB, needs Pillow)
./venv/bin/python compress_images.py
```

There is no test suite, linter, or build step. Dependencies: Flask, PyMySQL,
python-dotenv, bleach, requests (see `requirements.txt`; `gunicorn` and `Pillow` are
extras installed on demand).

## Configuration (`.env`, not in git)

`db.py` and `chatbot.py` read from `.env` via `python-dotenv`:

- `DB_URL`, `DB_PORT`, `DB_USER`, `DB_PASSWD`, `DB_NAME` — MariaDB connection.
- `SECRET_KEY` — Flask session key (`app.secret_key` reads it unconditionally, so the
  app **will not start** without it). Generate: `python -c "import secrets; print(secrets.token_hex(32))"`.
- `OPENROUTER_API_KEY` — chatbot; if unset, `/api/chat` returns 503 but the rest of the
  site works.
- `OPENROUTER_MODEL` (default `google/gemini-2.0-flash`), optional
  `OPENROUTER_CLASSIFY_MODEL`.

## Database

Dedicated database `smbc_website`, **separate from** the church's internal admin DB
(`smbc_db`). Only two tables (`schema.sql`, uses `CREATE TABLE IF NOT EXISTS` so it's
safe to re-run):

- `user` — admin logins; `pwd` is a Werkzeug scrypt hash.
- `event` — `id` is a `varchar(16)` random short code (not auto-increment);
  `content` is cleaned HTML; `published` (1/0) is the draft flag; `author_id` → `user.id`.

`db.py`'s `get_connection()` returns a PyMySQL connection with `DictCursor` and
`autocommit=True`, so query results are dicts and there are no explicit commits.
The server (MariaDB 10.11) has no SSL — PyMySQL's default (off) is correct.

## Architecture notes

**Two apps in one file split.** `app.py` owns HTTP routing, auth, the events CRUD, and
the knowledge-file admin. `chatbot.py` is a Flask **blueprint** (`chatbot_bp`, registered
in `app.py`) owning `/api/chat` plus all knowledge/RAG logic. `app.py` imports several
helpers from `chatbot.py` (`sync_event_md`, `remove_event_md`, `load_categories`,
`load_system_prompt`, `KNOWLEDGE_DIR`, `SYSTEM_PROMPT_FILE`) — the dependency direction is
one-way: `app.py` → `chatbot.py`.

**Events ↔ knowledge-base sync is the key cross-cutting invariant.** The chatbot's
knowledge for "latest events" is not read from the DB — it reads markdown files in
`knowledge/events/`. So every write path to an event must keep those `.md` files in sync:

- Saving a **published** event → `sync_event_md()` writes `knowledge/events/<id>.md`
  (HTML stripped to plain text via `_html_to_text`).
- Unpublishing or deleting → `remove_event_md()`.
- On startup, `app.py`'s `backfill_event_md()` regenerates `.md` for all published events
  (so the chatbot works even for events created before this feature / edited out-of-band).
  **Note it runs only under `if __name__ == "__main__"`, i.e. the dev server — not under
  gunicorn.** If you add a new event write path, wire in the sync calls yourself.

**RAG flow (`chatbot.py`), no vector DB.** For each question: (1) `classify()` asks the
LLM to pick 1–2 category ids from `knowledge/categories.json`; on any failure it falls
back to *all* categories. (2) `read_categories()` concatenates every `.md` in the chosen
category folders, capped at `MAX_CONTEXT_CHARS` (8000). (3) `answer_stream()` streams the
answer. `/api/chat` responds as **SSE** (`text/event-stream`) with `{categories}`, then
`{delta}` chunks, then `{done}` — the frontend is `static/chatbot.js`.

**Knowledge categories are fixed by `categories.json`.** Each entry's `id` is a folder
name under `knowledge/`. The `events` category is special: read-only in the admin UI
(auto-generated), and sorted newest-first by file mtime while other categories sort by
filename. Admins edit the other categories' `.md` files and the `_system_prompt.md`
through `/admin/knowledge` and `/admin/settings`.

**Security-sensitive spots to preserve when editing:**
- Event body HTML is sanitized with `bleach` against the `ALLOWED_TAGS`/`ALLOWED_ATTRS`
  whitelist in `app.py` before storage. Uploads are restricted to jpg/png/webp/gif,
  renamed to a UUID, and capped at 16MB (`MAX_CONTENT_LENGTH`).
- Knowledge-file admin routes resolve paths through `_safe_knowledge_path()` in `app.py`,
  which validates the category, `secure_filename`s the name, and checks `commonpath` to
  block directory traversal. Route new knowledge file operations through it.
- `login_required` (in `app.py`) gates every `/admin/*` route via the session.

## Templates vs static pages

`templates/` (Jinja) is only for the dynamic surfaces: events list/detail, login, and the
`admin/` dashboard/editor/knowledge/settings pages. `base.html` / `base_admin.html` are
the shared layouts. The marketing pages (`index.html`, `courses.html`, `tour.html`,
`en/*`) are standalone HTML at the repo root using Tailwind (CDN) + Font Awesome, served
directly — edit those files, not templates, for marketing content. The event editor uses
the Quill 2 WYSIWYG editor.
