# db_queries.py

import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Dict, List, Optional, Union
import json

from fastapi.encoders import jsonable_encoder

from sturdy.protocol import AllocInfo, PoolModel


BALANCE = "balance"
KEY = "key"
NAME = "name"

RATE_LIMIT_PER_MINUTE = "rate_limit_per_minute"
API_KEYS_TABLE = "api_keys"
LOGS_TABLE = "logs"
ENDPOINT = "endpoint"
CREATED_AT = "created_at"

# allocations table
ALLOCATION_REQUESTS_TABLE = "allocation_requests"
ALLOCATIONS_TABLE = "allocations"
REQUEST_UID = "request_uid"
MINER_UID = "miner_uid"
USER_ADDRESS = "user_address"
ALLOCATION = "allocation"


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


def to_json_string(input_data):
    """
    Convert a dictionary or a string to a valid JSON string.

    :param input_data: dict or str - The input data to be converted to JSON.
    :return: str - The JSON string representation of the input data.
    :raises: ValueError - If the input_data is not a valid dict or JSON string.
    """
    if isinstance(input_data, dict):
        return json.dumps(input_data)
    elif isinstance(input_data, str):
        try:
            # Check if the string is already a valid JSON string
            json.loads(input_data)
            return input_data
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON string provided.")
    else:
        raise ValueError("Input must be a dictionary or a valid JSON string.")


def log_allocations(
    conn: sqlite3.Connection,
    request_uid: str,
    assets_and_pools: Dict[str, Union[Dict[str, PoolModel], int]],
    allocations: Dict[str, AllocInfo],
) -> bool:
    ts_now = datetime.utcnow().timestamp()
    conn.execute(
        f"INSERT INTO {ALLOCATION_REQUESTS_TABLE} VALUES (?, json(?), ?)",
        (
            request_uid,
            json.dumps(jsonable_encoder(assets_and_pools)),
            datetime.fromtimestamp(ts_now),
        ),
    )

    to_insert = []
    ts_now = datetime.utcnow().timestamp()
    for miner_uid, miner_allocation in allocations.items():
        row = (
            request_uid,
            miner_uid,
            to_json_string(miner_allocation),
            datetime.fromtimestamp(ts_now),
        )
        to_insert.append(row)

    conn.executemany(
        f"INSERT INTO {ALLOCATIONS_TABLE} VALUES (?, ?, json(?), ?)", to_insert
    )

    conn.commit()


def get_filtered_allocations(
    conn: sqlite3.Connection,
    request_uid: Optional[str],
    miner_uid: Optional[str],
    from_ts: Optional[int],
    to_ts: Optional[int],
) -> List[Dict]:
    query = f"""
    SELECT * FROM {ALLOCATIONS_TABLE}
    WHERE 1=1
    """
    params = []

    if request_uid:
        query += " AND request_uid = ?"
        params.append(request_uid)

    if miner_uid:
        query += " AND miner_uid = ?"
        params.append(miner_uid)

    if from_ts:
        query += " AND created_at >= ?"
        params.append(datetime.fromtimestamp(from_ts / 1000))

    if to_ts:
        query += " AND created_at <= ?"
        params.append(datetime.fromtimestamp(to_ts / 1000))

    cur = conn.execute(query, params)
    rows = cur.fetchall()
    return [dict(row) for row in rows]


def get_request_info(
    conn: sqlite3.Connection,
    request_uid: Optional[str],
    from_ts: Optional[int],
    to_ts: Optional[int],
) -> List[Dict]:
    query = f"""
    SELECT * FROM {ALLOCATION_REQUESTS_TABLE}
    WHERE 1=1
    """
    params = []

    if request_uid:
        query += " AND request_uid = ?"
        params.append(request_uid)

    if from_ts:
        query += " AND created_at >= ?"
        params.append(datetime.fromtimestamp(from_ts / 1000))

    if to_ts:
        query += " AND created_at <= ?"
        params.append(datetime.fromtimestamp(to_ts / 1000))

    cur = conn.execute(query, params)
    rows = cur.fetchall()
    return [dict(row) for row in rows]
