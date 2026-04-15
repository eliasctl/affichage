import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "data" / "affichage.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
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

        conn.commit()


# ── Slides ───────────────────────────────────────────────────

def _parse_slide(row):
    s = dict(row)
    s["images"] = json.loads(s.get("images") or "[]")
    s["extra"]  = json.loads(s.get("extra")  or "{}")
    return s


def get_slides(active_only=True):
    with get_conn() as conn:
        q = ("SELECT * FROM slides WHERE active=1 ORDER BY position,id" if active_only
             else "SELECT * FROM slides ORDER BY position,id")
        return [_parse_slide(r) for r in conn.execute(q).fetchall()]


def get_slide(slide_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM slides WHERE id=?", (slide_id,)).fetchone()
    return _parse_slide(row) if row else None


def create_slide(title, content, slide_type="intervention", layout="annonce",
                 images=None, extra=None, duration=None):
    with get_conn() as conn:
        max_pos = conn.execute("SELECT COALESCE(MAX(position),0) FROM slides").fetchone()[0]
        conn.execute(
            "INSERT INTO slides (title,content,type,layout,images,extra,duration,position) VALUES (?,?,?,?,?,?,?,?)",
            (title, content, slide_type, layout,
             json.dumps(images or []), json.dumps(extra or {}), duration, max_pos + 1),
        )
        conn.commit()


def update_slide(slide_id, title, content, slide_type, layout, images, extra, duration):
    with get_conn() as conn:
        conn.execute(
            "UPDATE slides SET title=?,content=?,type=?,layout=?,images=?,extra=?,duration=? WHERE id=?",
            (title, content, slide_type, layout,
             json.dumps(images), json.dumps(extra or {}), duration, slide_id),
        )
        conn.commit()


def delete_slide(slide_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM slides WHERE id=?", (slide_id,))
        conn.commit()


def toggle_slide(slide_id):
    with get_conn() as conn:
        conn.execute("UPDATE slides SET active=1-active WHERE id=?", (slide_id,))
        conn.commit()


def reorder_slides(ids):
    with get_conn() as conn:
        for pos, sid in enumerate(ids):
            conn.execute("UPDATE slides SET position=? WHERE id=?", (pos, sid))
        conn.commit()


def move_slide(slide_id, direction):
    with get_conn() as conn:
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


# ── Settings ─────────────────────────────────────────────────

def get_setting(key, default=""):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))
        conn.commit()


# ── Icons ─────────────────────────────────────────────────────

def get_icons():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM icons ORDER BY position,id").fetchall()]


def add_icon(filename, label):
    with get_conn() as conn:
        max_pos = conn.execute("SELECT COALESCE(MAX(position),0) FROM icons").fetchone()[0]
        conn.execute("INSERT INTO icons (filename,label,position) VALUES (?,?,?)",
                     (filename, label, max_pos + 1))
        conn.commit()


def delete_icon(icon_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM icons WHERE id=?", (icon_id,))
        conn.commit()


def move_icon(icon_id, direction):
    with get_conn() as conn:
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
    with get_conn() as conn:
        q = ("SELECT * FROM ticker WHERE active=1 ORDER BY position,id" if active_only
             else "SELECT * FROM ticker ORDER BY position,id")
        return [dict(r) for r in conn.execute(q).fetchall()]


def create_ticker(text):
    with get_conn() as conn:
        max_pos = conn.execute("SELECT COALESCE(MAX(position),0) FROM ticker").fetchone()[0]
        conn.execute("INSERT INTO ticker (text,position) VALUES (?,?)", (text, max_pos + 1))
        conn.commit()


def update_ticker(tid, text):
    with get_conn() as conn:
        conn.execute("UPDATE ticker SET text=? WHERE id=?", (text, tid))
        conn.commit()


def delete_ticker(tid):
    with get_conn() as conn:
        conn.execute("DELETE FROM ticker WHERE id=?", (tid,))
        conn.commit()


def toggle_ticker(tid):
    with get_conn() as conn:
        conn.execute("UPDATE ticker SET active=1-active WHERE id=?", (tid,))
        conn.commit()


def move_ticker(tid, direction):
    with get_conn() as conn:
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
