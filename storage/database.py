"""SQLite 데이터베이스 관리"""
import sqlite3
import os

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
                source      TEXT NOT NULL,
                notice_id   TEXT NOT NULL,
                category    TEXT,
                title       TEXT NOT NULL,
                issued_no   TEXT,
                posted_date TEXT NOT NULL,
                detail_url  TEXT,
                summary     TEXT,
                created_at  TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(source, notice_id)
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id   INTEGER NOT NULL REFERENCES notices(id),
                filename    TEXT NOT NULL,
                file_type   TEXT,
                download_url TEXT,
                local_path  TEXT,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id   INTEGER NOT NULL REFERENCES notices(id),
                is_read     INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            );
        """)


def upsert_notice(source, notice_id, category, title, issued_no, posted_date, detail_url):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM notices WHERE source=? AND notice_id=?",
            (source, notice_id)
        ).fetchone()
        if row:
            return row['id'], False
        cur = conn.execute(
            """INSERT INTO notices (source, notice_id, category, title, issued_no, posted_date, detail_url)
               VALUES (?,?,?,?,?,?,?)""",
            (source, notice_id, category, title, issued_no, posted_date, detail_url)
        )
        return cur.lastrowid, True


def add_alert(notice_db_id):
    with get_conn() as conn:
        conn.execute("INSERT INTO alerts (notice_id) VALUES (?)", (notice_db_id,))


def get_unread_alerts():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT a.id, a.notice_id, a.created_at,
                   n.title, n.source, n.category, n.posted_date
            FROM alerts a
            JOIN notices n ON n.id = a.notice_id
            WHERE a.is_read = 0
            ORDER BY a.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def mark_alerts_read(alert_ids: list):
    if not alert_ids:
        return
    placeholders = ','.join('?' * len(alert_ids))
    with get_conn() as conn:
        conn.execute(f"UPDATE alerts SET is_read=1 WHERE id IN ({placeholders})", alert_ids)


def save_attachment(notice_db_id, filename, file_type, download_url, local_path=None):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO attachments (notice_id, filename, file_type, download_url, local_path)
               VALUES (?,?,?,?,?)""",
            (notice_db_id, filename, file_type, download_url, local_path)
        )


def update_summary(notice_db_id, summary):
    with get_conn() as conn:
        conn.execute("UPDATE notices SET summary=? WHERE id=?", (summary, notice_db_id))


def count_notices(source=None, from_date='2026-03-01', has_summary=None):
    sql = "SELECT COUNT(*) FROM notices WHERE posted_date >= ?"
    params = [from_date]
    if source:
        sql += " AND source=?"
        params.append(source)
    if has_summary is True:
        sql += " AND summary IS NOT NULL"
    elif has_summary is False:
        sql += " AND summary IS NULL"
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()[0]


def get_notices(source=None, from_date='2026-03-01', limit=50, offset=0, has_summary=None):
    sql = "SELECT * FROM notices WHERE posted_date >= ?"
    params = [from_date]
    if source:
        sql += " AND source=?"
        params.append(source)
    if has_summary is True:
        sql += " AND summary IS NOT NULL"
    elif has_summary is False:
        sql += " AND summary IS NULL"
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
