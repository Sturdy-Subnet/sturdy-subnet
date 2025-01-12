import json
import sqlite3
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sturdy.protocol import REQUEST_TYPES
from sturdy.validator.sql import (
    add_api_key,
    delete_api_key,
    get_all_api_keys,
    get_all_logs_for_key,
    get_api_key_info,
    get_db_connection,
    get_miner_responses,
    get_request_info,
    log_allocations,
    log_request,
    update_api_key_balance,
    update_api_key_name,
    update_api_key_rate_limit,
)
from tests.helpers import create_tables

TEST_DB = "test.db"


class TestSQLFunctions(unittest.TestCase):
    def setUp(self) -> None:
        # purge sql db
        path = Path(TEST_DB)
        if path.exists():
            path.unlink()
        # Create an in-memory SQLite database
        with get_db_connection(TEST_DB) as conn:
            create_tables(conn)

    def tearDown(self) -> None:
        # purge sql db
        path = Path(TEST_DB)
        if path.exists():
            path.unlink()

    def test_add_and_get_api_key(self) -> None:
        with get_db_connection(TEST_DB) as conn:
            # Add an API key
            add_api_key(conn, "test_key", 100.0, 60, "Test Key")
            # Retrieve the API key information
            info = get_api_key_info(conn, "test_key")
            self.assertIsNotNone(info)
            self.assertEqual(info["key"], "test_key")
            self.assertEqual(info["balance"], 100.0)
            self.assertEqual(info["rate_limit_per_minute"], 60)
            self.assertEqual(info["name"], "Test Key")

    def test_update_api_key_balance(self) -> None:
        with get_db_connection(TEST_DB) as conn:
            # Add an API key
            add_api_key(conn, "test_key", 100.0, 60, "Test Key")
            # Update the balance
            update_api_key_balance(conn, "test_key", 200.0)
            # Retrieve the updated information
            info = get_api_key_info(conn, "test_key")
            self.assertEqual(info["balance"], 200.0)

    def test_update_api_key_rate_limit(self) -> None:
        with get_db_connection(TEST_DB) as conn:
            # Add an API key
            add_api_key(conn, "test_key", 100.0, 60, "Test Key")
            # Update the rate limit
            update_api_key_rate_limit(conn, "test_key", 120)
            # Retrieve the updated information
            info = get_api_key_info(conn, "test_key")
            self.assertEqual(info["rate_limit_per_minute"], 120)

    def test_update_api_key_name(self) -> None:
        with get_db_connection(TEST_DB) as conn:
            # Add an API key
            add_api_key(conn, "test_key", 100.0, 60, "Test Key")
            # Update the name
            update_api_key_name(conn, "test_key", "Updated Test Key")
            # Retrieve the updated information
            info = get_api_key_info(conn, "test_key")
            self.assertEqual(info["name"], "Updated Test Key")

    def test_delete_api_key(self) -> None:
        with get_db_connection(TEST_DB) as conn:
            # Add an API key
            add_api_key(conn, "test_key", 100.0, 60, "Test Key")
            # Delete the API key
            delete_api_key(conn, "test_key")
            # Attempt to retrieve the deleted key
            info = get_api_key_info(conn, "test_key")
            self.assertIsNone(info)

    def test_get_all_api_keys(self) -> None:
        with get_db_connection(TEST_DB) as conn:
            # Add multiple API keys
            add_api_key(conn, "key1", 100.0, 60, "Key 1")
            add_api_key(conn, "key2", 200.0, 120, "Key 2")
            # Retrieve all API keys
            keys = get_all_api_keys(conn)
            self.assertEqual(len(keys), 2)
            self.assertEqual(keys[0]["key"], "key1")
            self.assertEqual(keys[1]["key"], "key2")

    def test_log_request_and_get_logs(self) -> None:
        with get_db_connection(TEST_DB) as conn:
            # Add an API key
            add_api_key(conn, "test_key", 100.0, 60, "Test Key")
            # Log a request
            api_key_info = get_api_key_info(conn, "test_key")
            log_request(conn, api_key_info, "/test_endpoint", 1.0)
            # Retrieve logs for the API key
            logs = get_all_logs_for_key(conn, "test_key")
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["key"], "test_key")
            self.assertEqual(logs[0]["endpoint"], "/test_endpoint")
            self.assertEqual(logs[0]["cost"], 1.0)

    def test_get_db_connection(self) -> None:
        # Test the get_db_connection function
        with get_db_connection(TEST_DB) as conn:
            self.assertIsNotNone(conn)
            # Ensure tables are created
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            self.assertGreater(len(tables), 0)

    def test_log_allocations(self) -> None:
        with get_db_connection(TEST_DB) as conn:
            request_uid = "sturdyrox"

            selected_entry = {
                "user_address": "0xcFB23D05f32eA0BE0dBb5078d189Cca89688945E",
                "assets_and_pools": {
                    "total_assets": 69420,
                    "pools": {
                        "0x0669091F451142b3228171aE6aD794cF98288124": {
                            "pool_type": "STURDY_SILO",
                            "contract_address": "0x0669091F451142b3228171aE6aD794cF98288124",
                        },
                        "0xFa68707be4b58FB9F10748E30e25A15113EdEE1D": {
                            "pool_type": "STURDY_SILO",
                            "contract_address": "0xFa68707be4b58FB9F10748E30e25A15113EdEE1D",
                        },
                    },
                },
            }

            allocations = {
                "0": {
                    "0x0669091F451142b3228171aE6aD794cF98288124": 3,
                    "0xFa68707be4b58FB9F10748E30e25A15113EdEE1D": 7,
                },
                "1": {
                    "0x0669091F451142b3228171aE6aD794cF98288124": 2,
                    "0xFa68707be4b58FB9F10748E30e25A15113EdEE1D": 8,
                },
                "2": {
                    "0x0669091F451142b3228171aE6aD794cF98288124": 6,
                    "0xFa68707be4b58FB9F10748E30e25A15113EdEE1D": 4,
                },
            }

            assets_and_pools = selected_entry["assets_and_pools"]

            log_allocations(
                conn,
                request_uid,
                ["asdf", "sdfsdg", "asdal"],
                assets_and_pools,
                extra_metadata={"yo": "wassup"},
                allocations=allocations,
                axon_times={"0": 6.9, "1": 4.2, "2": 1.0},
                request_type=REQUEST_TYPES.SYNTHETIC,
                scoring_period=69,
            )

            # Validate `allocation_requests` table
            cur = conn.execute("SELECT * FROM allocation_requests WHERE request_uid = ?", (request_uid,))
            allocation_request = dict(cur.fetchone())
            self.assertIsNotNone(allocation_request)
            self.assertEqual(allocation_request["request_uid"], request_uid)
            self.assertEqual(allocation_request["metadata"], '{"yo":"wassup"}')
            self.assertEqual(allocation_request["request_type"], str(int(REQUEST_TYPES.SYNTHETIC)))

            # Validate `active_allocs` table
            cur = conn.execute("SELECT * FROM active_allocs WHERE request_uid = ?", (request_uid,))
            active_alloc = cur.fetchone()
            self.assertIsNotNone(active_alloc)
            self.assertEqual(active_alloc["request_uid"], request_uid)
            self.assertEqual(json.loads(active_alloc["miners"]), ["asdf", "sdfsdg", "asdal"])

            # Validate `allocations` table
            cur = conn.execute("SELECT * FROM allocations WHERE request_uid = ?", (request_uid,))
            allocation_rows = cur.fetchall()
            self.assertEqual(len(allocation_rows), len(allocations))
            for miner_uid, miner_allocation in allocations.items():
                for pool_id, allocation_value in miner_allocation.items():
                    row = next(
                        (
                            r
                            for r in allocation_rows
                            if r["miner_uid"] == miner_uid and json.loads(r["allocation"]).get(pool_id) == allocation_value
                        ),
                        None,
                    )
                    self.assertIsNotNone(row)
                    self.assertEqual(row["request_uid"], request_uid)
                    self.assertIn(pool_id, row["allocation"])
                    self.assertEqual(json.loads(row["allocation"])[pool_id], allocation_value)


class TestMinerResponseRequestInfo(unittest.TestCase):
    def setUp(self) -> None:
        # Initialize an in-memory SQLite database
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        create_tables(self.conn)

        # Seed test data for allocations
        self.request_uid = "test_request_1"
        self.miner_uid = "miner_1"
        created_at = datetime.utcnow()
        self.conn.execute(
            "INSERT INTO allocations (request_uid, miner_uid, allocation, created_at, axon_time) VALUES (?, ?, json(?), ?, ?)",
            (self.request_uid, self.miner_uid, '{"pool_1": 100}', created_at, 1.2),
        )
        self.conn.execute(
            "INSERT INTO allocations (request_uid, miner_uid, allocation, created_at, axon_time) VALUES (?, ?, json(?), ?, ?)",
            (self.request_uid, "miner_2", '{"pool_2": 200}', created_at + timedelta(minutes=1), 2.3),
        )

        # Seed test data for allocation requests
        self.conn.execute(
            "INSERT INTO allocation_requests (request_uid, assets_and_pools, created_at, request_type, metadata) VALUES (?, json(?), ?, ?, json(?))",
            (
                self.request_uid,
                '{"asset": {"pool": "data"}}',
                created_at,
                "TEST",
                '{"meta": "data"}',
            ),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_get_miner_responses_with_request_uid(self) -> None:
        responses = get_miner_responses(self.conn, request_uid=self.request_uid)
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["miner_uid"], "miner_1")
        self.assertEqual(responses[0]["request_uid"], self.request_uid)
        self.assertEqual(responses[1]["miner_uid"], "miner_2")

    def test_get_miner_responses_with_miner_uid(self) -> None:
        responses = get_miner_responses(self.conn, miner_uid="miner_2")
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["miner_uid"], "miner_2")
        self.assertEqual(json.loads(responses[0]["allocation"])["pool_2"], 200)

    def test_get_miner_responses_with_time_range(self) -> None:
        now = datetime.utcnow()
        from_ts = int((now - timedelta(minutes=5)).timestamp() * 1000)
        to_ts = int((now + timedelta(minutes=5)).timestamp() * 1000)

        responses = get_miner_responses(self.conn, from_ts=from_ts, to_ts=to_ts)
        self.assertEqual(len(responses), 2)

    def test_get_request_info_with_request_uid(self) -> None:
        info = get_request_info(self.conn, request_uid=self.request_uid)
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["request_uid"], self.request_uid)
        self.assertEqual(info[0]["request_type"], "TEST")
        self.assertEqual(json.loads(info[0]["metadata"])["meta"], "data")

    def test_get_request_info_with_time_range(self) -> None:
        now = datetime.utcnow()
        from_ts = int((now - timedelta(minutes=5)).timestamp() * 1000)
        to_ts = int((now + timedelta(minutes=5)).timestamp() * 1000)

        info = get_request_info(self.conn, from_ts=from_ts, to_ts=to_ts)
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["request_uid"], self.request_uid)

    def test_get_request_info_no_results(self) -> None:
        from_ts = int((datetime.utcnow() + timedelta(days=1)).timestamp() * 1000)
        to_ts = int((datetime.utcnow() + timedelta(days=2)).timestamp() * 1000)

        info = get_request_info(self.conn, from_ts=from_ts, to_ts=to_ts)
        self.assertEqual(len(info), 0)


if __name__ == "__main__":
    unittest.main()
