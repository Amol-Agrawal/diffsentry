import sqlite3


def get_user(conn: sqlite3.Connection, user_id: int):
    cur = conn.execute("SELECT id, email FROM users WHERE id = ?", (user_id,))
    return cur.fetchone()
