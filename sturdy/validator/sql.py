# db_queries.py

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

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
def get_db_connection():  # noqa: ANN201
    conn = sqlite3.connect("validator_database.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def get_api_key_info(conn: sqlite3.Connection, api_key: str) -> dict | None:
    row = conn.execute(f"SELECT * FROM {API_KEYS_TABLE} WHERE {KEY} = ?", (api_key,)).fetchone()
    return dict(row) if row else None


def get_all_api_keys(conn: sqlite3.Connection) -> list:
    return conn.execute(f"SELECT * FROM {API_KEYS_TABLE}").fetchall()


def get_all_logs_for_key(conn: sqlite3.Connection, api_key: str) -> list:
    return conn.execute(f"SELECT * FROM {LOGS_TABLE} WHERE {KEY} = ?", (api_key,)).fetchall()


def get_all_logs(conn: sqlite3.Connection) -> list:
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
        (api_key, name, balance, rate_limit_per_minute, datetime.now()),  # noqa: DTZ005
    )
    conn.commit()


def update_api_key_balance(conn: sqlite3.Connection, key: str, balance: float) -> None:
    conn.execute(f"UPDATE {API_KEYS_TABLE} SET {BALANCE} = ? WHERE {KEY} = ?", (balance, key))
    conn.commit()


def update_api_key_rate_limit(conn: sqlite3.Connection, key: str, rate: int) -> None:
    conn.execute(
        f"UPDATE {API_KEYS_TABLE} SET {RATE_LIMIT_PER_MINUTE} = ? WHERE {KEY} = ?",
        (rate, key),
    )
    conn.commit()


def update_api_key_name(conn: sqlite3.Connection, key: str, name: str) -> None:
    conn.execute(f"UPDATE {API_KEYS_TABLE} SET {NAME} = ? WHERE {KEY} = ?", (name, key))
    conn.commit()


def delete_api_key(conn: sqlite3.Connection, api_key: str) -> None:
    conn.execute(f"DELETE FROM {API_KEYS_TABLE} WHERE {KEY} = ?", (api_key,))
    conn.commit()


def update_requests_and_credits(conn: sqlite3.Connection, api_key_info: dict, cost: float) -> None:
    conn.execute(
        f"UPDATE api_keys SET {BALANCE} = {BALANCE} - {cost} WHERE {KEY} = ?",
        (api_key_info[KEY],),
    )


def log_request(conn: sqlite3.Connection, api_key_info: dict, path: str, cost: float) -> None:
    info = get_api_key_info(conn, api_key_info[KEY])
    if isinstance(info, dict):
        balance = info[BALANCE]

        conn.execute(
            f"INSERT INTO {LOGS_TABLE} VALUES (?, ?, ?, ?, ?)",
            (info[KEY], path, cost, balance, datetime.now()),  # noqa: DTZ005
        )


def rate_limit_exceeded(conn: sqlite3.Connection, api_key_info: dict) -> bool:
    one_minute_ago = datetime.now() - timedelta(minutes=1)  # noqa: DTZ005

    # Prepare a SQL statement
    query = f"""
        SELECT *
        FROM logs
        WHERE {KEY} = ? AND {CREATED_AT} >= ?
    """

    cur = conn.execute(query, (api_key_info[KEY], one_minute_ago.strftime("%Y-%m-%d %H:%M:%S")))
    recent_logs = cur.fetchall()

    return len(recent_logs) >= api_key_info[RATE_LIMIT_PER_MINUTE]


def to_json_string(input_data) -> str:
    """
    Convert a dictionary or a string to a valid JSON string.

    :param input_data: dict or str - The input data to be converted to JSON.
    :return: str - The JSON string representation of the input data.
    :raises: ValueError - If the input_data is not a valid dict or JSON string.
    """
    if isinstance(input_data, dict):
        return json.dumps(input_data)
    if isinstance(input_data, str):
        try:
            # Check if the string is already a valid JSON string
            json.loads(input_data)
            return input_data  # noqa: TRY300
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON string provided.")  # noqa: B904
    else:
        raise TypeError("Input must be a dictionary or a valid JSON string.")


def log_allocations(
    conn: sqlite3.Connection,
    request_uid: str,
    assets_and_pools: dict[str, dict[str, PoolModel] | int],
    allocations: dict[str, AllocInfo],
) -> None:
    ts_now = datetime.utcnow().timestamp()  # noqa: DTZ003
    conn.execute(
        f"INSERT INTO {ALLOCATION_REQUESTS_TABLE} VALUES (?, json(?), ?)",
        (
            request_uid,
            json.dumps(jsonable_encoder(assets_and_pools)),
            datetime.fromtimestamp(ts_now),  # noqa: DTZ006
        ),
    )

    to_insert = []
    ts_now = datetime.utcnow().timestamp()  # noqa: DTZ003
    for miner_uid, miner_allocation in allocations.items():
        row = (
            request_uid,
            miner_uid,
            to_json_string(miner_allocation),
            datetime.fromtimestamp(ts_now),  # noqa: DTZ006
        )
        to_insert.append(row)

    conn.executemany(f"INSERT INTO {ALLOCATIONS_TABLE} VALUES (?, ?, json(?), ?)", to_insert)

    conn.commit()


def get_filtered_allocations(
    conn: sqlite3.Connection,
    request_uid: str | None,
    miner_uid: str | None,
    from_ts: int | None,
    to_ts: int | None,
) -> list[dict]:
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
        params.append(datetime.fromtimestamp(from_ts / 1000))  # noqa: DTZ006

    if to_ts:
        query += " AND created_at <= ?"
        params.append(datetime.fromtimestamp(to_ts / 1000))  # noqa: DTZ006

    cur = conn.execute(query, params)
    rows = cur.fetchall()
    return [dict(row) for row in rows]


def get_request_info(
    conn: sqlite3.Connection,
    request_uid: str | None,
    from_ts: int | None,
    to_ts: int | None,
) -> list[dict]:
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
        params.append(datetime.fromtimestamp(from_ts / 1000))  # noqa: DTZ006

    if to_ts:
        query += " AND created_at <= ?"
        params.append(datetime.fromtimestamp(to_ts / 1000))  # noqa: DTZ006

    cur = conn.execute(query, params)
    rows = cur.fetchall()
    return [dict(row) for row in rows]
