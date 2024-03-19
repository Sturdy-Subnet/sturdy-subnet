# db_queries.py

import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager


BALANCE = "balance"
KEY = "key"
NAME = "name"

RATE_LIMIT_PER_MINUTE = "rate_limit_per_minute"
API_KEYS_TABLE = "api_keys"
LOGS_TABLE = "logs"
ENDPOINT = "endpoint"
CREATED_AT = "created_at"


@contextmanager
def get_db_connection():
    conn = sqlite3.connect("validator_database.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def get_api_key_info(conn: sqlite3.Connection, api_key: str) -> sqlite3.Row:
    row = conn.execute(
        f"SELECT * FROM {API_KEYS_TABLE} WHERE {KEY} = ?", (api_key,)
    ).fetchone()
    return dict(row) if row else None


def get_all_api_keys(conn: sqlite3.Connection):
    return conn.execute(f"SELECT * FROM {API_KEYS_TABLE}").fetchall()


def get_all_logs_for_key(conn: sqlite3.Connection, api_key: str):
    return conn.execute(
        f"SELECT * FROM {LOGS_TABLE} WHERE {KEY} = ?", (api_key,)
    ).fetchall()


def get_all_logs(conn: sqlite3.Connection):
    return conn.execute(f"SELECT * FROM {LOGS_TABLE}").fetchall()


def add_api_key(
    conn: sqlite3.Connection,
    api_key: str,
    balance: float,
    rate_limit_per_minute: int,
    name: str,
) -> None:
    conn.execute(
        f"INSERT INTO {API_KEYS_TABLE} VALUES (?, ?, ?, ?, ?)",
        (api_key, name, balance, rate_limit_per_minute, datetime.now()),
    )
    conn.commit()


def update_api_key_balance(conn: sqlite3.Connection, key: str, balance: float):
    conn.execute(
        f"UPDATE {API_KEYS_TABLE} SET {BALANCE} = ? WHERE {KEY} = ?", (balance, key)
    )
    conn.commit()


def update_api_key_rate_limit(conn: sqlite3.Connection, key: str, rate: int):
    conn.execute(
        f"UPDATE {API_KEYS_TABLE} SET {RATE_LIMIT_PER_MINUTE} = ? WHERE {KEY} = ?",
        (rate, key),
    )
    conn.commit()


def update_api_key_name(conn: sqlite3.Connection, key: str, name: str):
    conn.execute(f"UPDATE {API_KEYS_TABLE} SET {NAME} = ? WHERE {KEY} = ?", (name, key))
    conn.commit()


def delete_api_key(conn: sqlite3.Connection, api_key: str) -> None:
    conn.execute(f"DELETE FROM {API_KEYS_TABLE} WHERE {KEY} = ?", (api_key,))
    conn.commit()


def update_requests_and_credits(
    conn: sqlite3.Connection, api_key_info: sqlite3.Row, cost: float
) -> float:

    conn.execute(
        f"UPDATE api_keys SET {BALANCE} = {BALANCE} - {cost} WHERE {KEY} = ?",
        (api_key_info[KEY],),
    )


def log_request(
    conn: sqlite3.Connection, api_key_info: sqlite3.Row, path: str, cost: float
) -> None:
    api_key_info = get_api_key_info(conn, api_key_info[KEY])
    balance = api_key_info[BALANCE]

    conn.execute(
        f"INSERT INTO {LOGS_TABLE} VALUES (?, ?, ?, ?, ?)",
        (api_key_info[KEY], path, cost, balance, datetime.now()),
    )


def rate_limit_exceeded(conn: sqlite3.Connection, api_key_info: sqlite3.Row) -> bool:
    one_minute_ago = datetime.now() - timedelta(minutes=1)

    # Prepare a SQL statement
    query = f"""
        SELECT *
        FROM logs
        WHERE {KEY} = ? AND {CREATED_AT} >= ?
    """

    cur = conn.execute(
        query, (api_key_info[KEY], one_minute_ago.strftime("%Y-%m-%d %H:%M:%S"))
    )
    recent_logs = cur.fetchall()

    return len(recent_logs) >= api_key_info[RATE_LIMIT_PER_MINUTE]
