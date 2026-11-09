import sqlite3


def get_user(conn: sqlite3.Connection, user_id: int):
    cur = conn.execute("SELECT id, email FROM users WHERE id = ?", (user_id,))
    return cur.fetchone()


def find_users_by_email(conn: sqlite3.Connection, email: str):
    query = f"SELECT id, email FROM users WHERE email LIKE '%{email}%'"
    return conn.execute(query).fetchall()
