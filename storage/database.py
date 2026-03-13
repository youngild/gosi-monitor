"""SQLite 데이터베이스 관리"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'notices.db')


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source      TEXT NOT NULL,        -- 'mohw' | 'hira'
                notice_id   TEXT NOT NULL,         -- 원본 사이트 게시물 ID
                category    TEXT,                  -- 구분 (고시/훈령/예규/지침)
                title       TEXT NOT NULL,
                issued_no   TEXT,                  -- 발령번호
                posted_date TEXT NOT NULL,         -- 등록일 (YYYY-MM-DD)
                detail_url  TEXT,
                summary     TEXT,                  -- AI 요약
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(source, notice_id)
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id   INTEGER NOT NULL REFERENCES notices(id),
                filename    TEXT NOT NULL,
                file_type   TEXT,                  -- 'pdf' | 'hwp' | 'hwpx' | 'xlsx' 등
                download_url TEXT,
                local_path  TEXT,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            );
        """)


def upsert_notice(source, notice_id, category, title, issued_no, posted_date, detail_url):
    """게시물 저장. 이미 있으면 skip하고 id 반환."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM notices WHERE source=? AND notice_id=?",
            (source, notice_id)
        ).fetchone()
        if row:
            return row['id'], False  # (id, is_new)
        cur = conn.execute(
            """INSERT INTO notices (source, notice_id, category, title, issued_no, posted_date, detail_url)
               VALUES (?,?,?,?,?,?,?)""",
            (source, notice_id, category, title, issued_no, posted_date, detail_url)
        )
        return cur.lastrowid, True


def save_attachment(notice_db_id, filename, file_type, download_url, local_path=None):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO attachments (notice_id, filename, file_type, download_url, local_path)
               VALUES (?,?,?,?,?)""",
            (notice_db_id, filename, file_type, download_url, local_path)
        )


def update_summary(notice_db_id, summary):
    with get_conn() as conn:
        conn.execute(
            "UPDATE notices SET summary=? WHERE id=?",
            (summary, notice_db_id)
        )


def count_notices(source=None, from_date='2026-03-01'):
    sql = "SELECT COUNT(*) FROM notices WHERE posted_date >= ?"
    params = [from_date]
    if source:
        sql += " AND source=?"
        params.append(source)
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()[0]


def get_notices(source=None, from_date='2026-03-01', limit=100, offset=0):
    sql = "SELECT * FROM notices WHERE posted_date >= ?"
    params = [from_date]
    if source:
        sql += " AND source=?"
        params.append(source)
    sql += " ORDER BY posted_date DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_notice_with_attachments(notice_db_id):
    with get_conn() as conn:
        notice = dict(conn.execute("SELECT * FROM notices WHERE id=?", (notice_db_id,)).fetchone())
        attachments = [dict(r) for r in conn.execute(
            "SELECT * FROM attachments WHERE notice_id=?", (notice_db_id,)
        ).fetchall()]
        notice['attachments'] = attachments
        return notice
