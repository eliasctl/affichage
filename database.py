import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "data" / "affichage.db"))

# ── Connexion thread-local (réutilisée au lieu d'en recréer une à chaque appel) ──
_local = threading.local()


def get_conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")  # 8 Mo
        _local.conn = conn
    return conn


# ── Cache de hash pour éviter des requêtes inutiles ──────────
_hash_cache = {"hash": None, "ts": 0}


def get_content_hash():
    """Hash léger du contenu (slides + ticker). Mis en cache 5s."""
    import time
    now = time.time()
    if _hash_cache["hash"] and now - _hash_cache["ts"] < 5:
        return _hash_cache["hash"]
    conn = get_conn()
    slides = conn.execute(
        "SELECT id,title,content,type,layout,images,duration,position,active,extra "
        "FROM slides WHERE active=1 ORDER BY position,id"
    ).fetchall()
    ticker = conn.execute(
        "SELECT id,text,active,position FROM ticker WHERE active=1 ORDER BY position,id"
    ).fetchall()
    raw = json.dumps({
        "s": [dict(r) for r in slides],
        "t": [dict(r) for r in ticker],
    }, sort_keys=True)
    h = hashlib.md5(raw.encode()).hexdigest()
    _hash_cache["hash"] = h
    _hash_cache["ts"] = now
    return h


def invalidate_cache():
    """Invalide le cache de hash après une modification."""
    _hash_cache["hash"] = None
    _hash_cache["ts"] = 0


def init_db():
    conn = get_conn()
    # ── slides ──────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS slides (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT    NOT NULL DEFAULT '',
            content    TEXT    NOT NULL DEFAULT '',
            images     TEXT    NOT NULL DEFAULT '[]',
            duration   INTEGER,
            position   INTEGER NOT NULL DEFAULT 0,
            active     INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    cols = [r[1] for r in conn.execute("PRAGMA table_info(slides)").fetchall()]

    if "image" in cols and "images" not in cols:
        conn.execute("ALTER TABLE slides ADD COLUMN images TEXT NOT NULL DEFAULT '[]'")
        for row in conn.execute("SELECT id, image FROM slides WHERE image IS NOT NULL").fetchall():
            conn.execute("UPDATE slides SET images=? WHERE id=?",
                         (json.dumps([row["image"]]), row["id"]))

    if "type" not in cols:
        conn.execute("ALTER TABLE slides ADD COLUMN type TEXT NOT NULL DEFAULT 'intervention'")

    if "layout" not in cols:
        conn.execute("ALTER TABLE slides ADD COLUMN layout TEXT NOT NULL DEFAULT 'annonce'")

    if "extra" not in cols:
        conn.execute("ALTER TABLE slides ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'")

    # ── settings ────────────────────────────────────────
    conn.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT ''
    )""")
    conn.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('ci_name','CIS Fontainebleau')")

    # ── icons ────────────────────────────────────────────
    conn.execute("""CREATE TABLE IF NOT EXISTS icons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0
    )""")

    # ── ticker ───────────────────────────────────────────
    conn.execute("""CREATE TABLE IF NOT EXISTS ticker (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text     TEXT    NOT NULL DEFAULT '',
        active   INTEGER NOT NULL DEFAULT 1,
        position INTEGER NOT NULL DEFAULT 0
    )""")

    # ── Index pour accélérer les requêtes fréquentes ─────
    conn.execute("CREATE INDEX IF NOT EXISTS idx_slides_active_pos ON slides(active, position)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ticker_active_pos ON ticker(active, position)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_icons_pos ON icons(position)")

    conn.commit()


# ── Slides ───────────────────────────────────────────────────

def _parse_slide(row):
    s = dict(row)
    s["images"] = json.loads(s.get("images") or "[]")
    s["extra"]  = json.loads(s.get("extra")  or "{}")
    return s


def get_slides(active_only=True):
    conn = get_conn()
    q = ("SELECT * FROM slides WHERE active=1 ORDER BY position,id" if active_only
         else "SELECT * FROM slides ORDER BY position,id")
    return [_parse_slide(r) for r in conn.execute(q).fetchall()]


def get_slide(slide_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM slides WHERE id=?", (slide_id,)).fetchone()
    return _parse_slide(row) if row else None


def create_slide(title, content, slide_type="intervention", layout="annonce",
                 images=None, extra=None, duration=None):
    conn = get_conn()
    max_pos = conn.execute("SELECT COALESCE(MAX(position),0) FROM slides").fetchone()[0]
    conn.execute(
        "INSERT INTO slides (title,content,type,layout,images,extra,duration,position) VALUES (?,?,?,?,?,?,?,?)",
        (title, content, slide_type, layout,
         json.dumps(images or []), json.dumps(extra or {}), duration, max_pos + 1),
    )
    conn.commit()
    invalidate_cache()


def update_slide(slide_id, title, content, slide_type, layout, images, extra, duration):
    conn = get_conn()
    conn.execute(
        "UPDATE slides SET title=?,content=?,type=?,layout=?,images=?,extra=?,duration=? WHERE id=?",
        (title, content, slide_type, layout,
         json.dumps(images), json.dumps(extra or {}), duration, slide_id),
    )
    conn.commit()
    invalidate_cache()


def delete_slide(slide_id):
    conn = get_conn()
    conn.execute("DELETE FROM slides WHERE id=?", (slide_id,))
    conn.commit()
    invalidate_cache()


def toggle_slide(slide_id):
    conn = get_conn()
    conn.execute("UPDATE slides SET active=1-active WHERE id=?", (slide_id,))
    conn.commit()
    invalidate_cache()


def reorder_slides(ids):
    conn = get_conn()
    for pos, sid in enumerate(ids):
        conn.execute("UPDATE slides SET position=? WHERE id=?", (pos, sid))
    conn.commit()
    invalidate_cache()


def move_slide(slide_id, direction):
    conn = get_conn()
    slide = conn.execute("SELECT * FROM slides WHERE id=?", (slide_id,)).fetchone()
    if not slide:
        return
    pos = slide["position"]
    other = conn.execute(
        "SELECT * FROM slides WHERE position<? ORDER BY position DESC LIMIT 1" if direction == "up"
        else "SELECT * FROM slides WHERE position>? ORDER BY position ASC LIMIT 1",
        (pos,)
    ).fetchone()
    if other:
        conn.execute("UPDATE slides SET position=? WHERE id=?", (other["position"], slide_id))
        conn.execute("UPDATE slides SET position=? WHERE id=?", (pos, other["id"]))
        conn.commit()
        invalidate_cache()


# ── Settings ─────────────────────────────────────────────────

def get_setting(key, default=""):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))
    conn.commit()


# ── Icons ─────────────────────────────────────────────────────

def get_icons():
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM icons ORDER BY position,id").fetchall()]


def add_icon(filename, label):
    conn = get_conn()
    max_pos = conn.execute("SELECT COALESCE(MAX(position),0) FROM icons").fetchone()[0]
    conn.execute("INSERT INTO icons (filename,label,position) VALUES (?,?,?)",
                 (filename, label, max_pos + 1))
    conn.commit()


def delete_icon(icon_id):
    conn = get_conn()
    conn.execute("DELETE FROM icons WHERE id=?", (icon_id,))
    conn.commit()


def move_icon(icon_id, direction):
    conn = get_conn()
    icon = conn.execute("SELECT * FROM icons WHERE id=?", (icon_id,)).fetchone()
    if not icon:
        return
    pos = icon["position"]
    other = conn.execute(
        "SELECT * FROM icons WHERE position<? ORDER BY position DESC LIMIT 1" if direction == "up"
        else "SELECT * FROM icons WHERE position>? ORDER BY position ASC LIMIT 1",
        (pos,)
    ).fetchone()
    if other:
        conn.execute("UPDATE icons SET position=? WHERE id=?", (other["position"], icon_id))
        conn.execute("UPDATE icons SET position=? WHERE id=?", (pos, other["id"]))
        conn.commit()


# ── Ticker ────────────────────────────────────────────────────

def get_ticker(active_only=True):
    conn = get_conn()
    q = ("SELECT * FROM ticker WHERE active=1 ORDER BY position,id" if active_only
         else "SELECT * FROM ticker ORDER BY position,id")
    return [dict(r) for r in conn.execute(q).fetchall()]


def create_ticker(text):
    conn = get_conn()
    max_pos = conn.execute("SELECT COALESCE(MAX(position),0) FROM ticker").fetchone()[0]
    conn.execute("INSERT INTO ticker (text,position) VALUES (?,?)", (text, max_pos + 1))
    conn.commit()
    invalidate_cache()


def update_ticker(tid, text):
    conn = get_conn()
    conn.execute("UPDATE ticker SET text=? WHERE id=?", (text, tid))
    conn.commit()
    invalidate_cache()


def delete_ticker(tid):
    conn = get_conn()
    conn.execute("DELETE FROM ticker WHERE id=?", (tid,))
    conn.commit()
    invalidate_cache()


def toggle_ticker(tid):
    conn = get_conn()
    conn.execute("UPDATE ticker SET active=1-active WHERE id=?", (tid,))
    conn.commit()
    invalidate_cache()


def move_ticker(tid, direction):
    conn = get_conn()
    item = conn.execute("SELECT * FROM ticker WHERE id=?", (tid,)).fetchone()
    if not item:
        return
    pos = item["position"]
    other = conn.execute(
        "SELECT * FROM ticker WHERE position<? ORDER BY position DESC LIMIT 1" if direction == "up"
        else "SELECT * FROM ticker WHERE position>? ORDER BY position ASC LIMIT 1",
        (pos,)
    ).fetchone()
    if other:
        conn.execute("UPDATE ticker SET position=? WHERE id=?", (other["position"], tid))
        conn.execute("UPDATE ticker SET position=? WHERE id=?", (pos, other["id"]))
        conn.commit()
        invalidate_cache()
