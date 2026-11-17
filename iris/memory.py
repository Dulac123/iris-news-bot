"""SQLite memorija: razgovor tekućeg dana, poslate priče, već skenirani linkovi, i meta (vremena poslednjih poslova)."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime

from . import config


def danas() -> str:
    return datetime.now(config.TZ).date().isoformat()


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init():
    with _db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, ts REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_msg_day ON messages(day, id);
            CREATE TABLE IF NOT EXISTS stories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL, url TEXT NOT NULL UNIQUE, title TEXT, topic TEXT,
                source TEXT, text TEXT, ts REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_story_day ON stories(day, id);
            CREATE TABLE IF NOT EXISTS scanned(url TEXT PRIMARY KEY, ts REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
            """
        )
        now = time.time()
        c.execute("DELETE FROM messages WHERE ts < ?", (now - 3 * 86400,))
        c.execute("DELETE FROM stories WHERE ts < ?", (now - 7 * 86400,))
        c.execute("DELETE FROM scanned WHERE ts < ?", (now - 3 * 86400,))


# ---- meta -----------------------------------------------------------------
def get_meta(k: str, default: str = "") -> str:
    with _db() as c:
        r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_meta(k: str, v) -> None:
    with _db() as c:
        c.execute("INSERT INTO meta(k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def meta_ts(k: str) -> float:
    try:
        return float(get_meta(k, "0"))
    except ValueError:
        return 0.0


# ---- razgovor -------------------------------------------------------------
def add_message(role: str, content: str):
    with _db() as c:
        c.execute(
            "INSERT INTO messages(day, role, content, ts) VALUES (?,?,?,?)",
            (danas(), role, content, time.time()),
        )


def today_messages(limit: int = config.MAX_CHAT_MESSAGES) -> list[dict]:
    with _db() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE day=? ORDER BY id DESC LIMIT ?",
            (danas(), limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_today():
    with _db() as c:
        c.execute("DELETE FROM messages WHERE day=?", (danas(),))


# ---- poslate priče --------------------------------------------------------
def sent_urls() -> set[str]:
    with _db() as c:
        return {r["url"] for r in c.execute("SELECT url FROM stories")}


def save_story(url: str, title: str, topic: str, source: str, text: str):
    with _db() as c:
        c.execute(
            "INSERT OR IGNORE INTO stories(day, url, title, topic, source, text, ts) VALUES (?,?,?,?,?,?,?)",
            (danas(), url, title, topic, source, text[:4000], time.time()),
        )


def today_stories(limit: int | None = None) -> list[dict]:
    q = "SELECT url, title, topic, source, text FROM stories WHERE day=? ORDER BY id DESC"
    args: tuple = (danas(),)
    if limit:
        q += " LIMIT ?"
        args += (limit,)
    with _db() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def today_titles() -> list[str]:
    return [s["title"] for s in today_stories() if s.get("title")]


# ---- skenirani linkovi (hitne vesti) --------------------------------------
def scanned_urls() -> set[str]:
    with _db() as c:
        return {r["url"] for r in c.execute("SELECT url FROM scanned")}


def mark_scanned(urls):
    with _db() as c:
        c.executemany("INSERT OR IGNORE INTO scanned(url, ts) VALUES (?,?)", [(u, time.time()) for u in urls])
