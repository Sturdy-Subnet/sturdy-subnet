import os
import sqlite3
import unittest
import uuid
from copy import copy
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import bittensor as bt
import numpy as np
import torch
from dotenv import load_dotenv
from freezegun import freeze_time
from web3 import Web3

from neurons.validator import Validator
from sturdy.algo import naive_algorithm
from sturdy.mock import MockDendrite
from sturdy.pool_registry.pool_registry import POOL_REGISTRY
from sturdy.pools import assets_pools_for_challenge_data
from sturdy.protocol import REQUEST_TYPES, AllocateAssets
from sturdy.validator.forward import get_metadata, query_multiple_miners
from sturdy.validator.reward import filter_allocations, get_rewards
from sturdy.validator.sql import get_active_allocs, get_db_connection, get_request_info, log_allocations

load_dotenv()
EXTERNAL_WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL")
os.environ["WEB_PROVIDER_URL"] = "http://127.0.0.1:8545"

TEST_DB = "test.db"


def init_db(conn: sqlite3.Connection) -> None:
    query = """CREATE TABLE IF NOT EXISTS allocation_requests (
        request_uid TEXT PRIMARY KEY,
        assets_and_pools TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE active_allocs (
        request_uid TEXT PRIMARY KEY,
        scoring_period_end TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (request_uid) REFERENCES allocation_requests (request_uid)
    );

    CREATE TABLE IF NOT EXISTS allocations (
        request_uid TEXT,
        miner_uid TEXT,
        allocation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (request_uid, miner_uid),
        FOREIGN KEY (request_uid) REFERENCES allocation_requests (request_uid)
    );

    -- This alter statement adds a new column to the allocations table if it exists
    ALTER TABLE allocation_requests
    ADD COLUMN request_type TEXT NOT NULL DEFAULT 1;
    ALTER TABLE allocation_requests
    ADD COLUMN metadata TEXT;
    ALTER TABLE allocations
    ADD COLUMN axon_time FLOAT NOT NULL DEFAULT 99999.0; -- large number for now"""

    conn.executescript(query)


# TODO: more comprehensive integration testing - with in-mem sql db and everythin'
class TestValidator(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        np.random.seed(69)  # noqa: NPY002
        cls.config = {
            "mock": True,
            "wandb": {"off": True},
            "mock_n": 16,
            "neuron": {"dont_save_events": True},
            "db_dir": TEST_DB,
        }

        cls.w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        assert cls.w3.is_connected()

        cls.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": EXTERNAL_WEB3_PROVIDER_URL,
                        "blockNumber": 21147890,
                    },
                },
            ],
        )

        selected_entry = POOL_REGISTRY["Sturdy Crvusd Aggregator"]
        cls.generated_data = assets_pools_for_challenge_data(selected_entry, cls.w3)
        print(f"assets and pools: {cls.generated_data}")
        cls.assets_and_pools = cls.generated_data["assets_and_pools"]

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=copy(cls.assets_and_pools),
        )

        cls.allocations = naive_algorithm(cls, synapse)
        cls.user_address = cls.generated_data["user_address"]

        cls.contract_addresses: list[str] = list(cls.assets_and_pools["pools"].keys())  # type: ignore[]

    @classmethod
    def tearDownClass(cls) -> None:
        # run this after tests to restore original forked state
        w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))

        w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": EXTERNAL_WEB3_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

    def setUp(self) -> None:
        # purge sql db
        path = Path(TEST_DB)
        if path.exists():
            path.unlink()

        self.snapshot_id = self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

        self.validator = Validator(config=self.config)
        self.validator.w3 = self.w3
        assert self.validator.w3.is_connected()

        # init sql db
        with get_db_connection(TEST_DB, True) as conn:
            init_db(conn)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [dict(t) for t in cur.fetchall()]
            print(f"tables init: {tables}")

    def tearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

        # purge sql db
        path = Path(TEST_DB)
        if path.exists():
            path.unlink()

    async def test_get_rewards(self) -> None:
        print("----==== test_get_rewards ====----")

        freezer = freeze_time("2024-01-11 00:00:00.124513")
        freezer.start()

        request_uuid = str(uuid.uuid4()).replace("-", "")

        with get_db_connection(self.validator.config.db_dir, True) as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [dict(t) for t in cur.fetchall()]
            print(f"tables: {tables}")

        assets_and_pools = copy(self.assets_and_pools)
        allocations = copy(self.allocations)

        validator = self.validator
        validator.dendrite = MockDendrite(wallet=validator.wallet, custom_allocs=True)

        # ====

        active_uids = [str(uid) for uid in range(validator.metagraph.n.item()) if validator.metagraph.axons[uid].is_serving]

        np.random.shuffle(active_uids)

        print(f"active_uids: {active_uids}")

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=assets_and_pools,
            user_address=self.user_address,
        )

        # query all miners
        responses = await query_multiple_miners(
            validator,
            synapse,
            active_uids,
        )

        allocations = {uid: responses[idx].allocations for idx, uid in enumerate(active_uids)}  # type: ignore[]

        for response in responses:
            # TODO: is this necessary?
            # self.assertEqual(response.assets_and_pools, self.assets_and_pools)
            self.assertLessEqual(sum(response.allocations.values()), assets_and_pools["total_assets"])

        # Log the results for monitoring purposes.
        print(f"Assets and pools: {synapse.assets_and_pools}")
        print(f"Received allocations (uid -> allocations): {allocations}")

        pools = assets_and_pools["pools"]
        metadata = get_metadata(pools, validator.w3)

        # axon_times = get_response_times(uids=active_uids, responses=responses, timeout=QUERY_TIMEOUT)
        # scoring period is ~12 hours
        scoring_period = 43200

        axon_times, filtered_allocs = filter_allocations(
            self,
            query=validator.step,
            uids=active_uids,
            responses=responses,
            assets_and_pools=assets_and_pools,
        )

        # log allocations
        with get_db_connection(validator.config.db_dir) as conn:
            log_allocations(
                conn,
                request_uuid,
                assets_and_pools,
                metadata,
                filtered_allocs,
                axon_times,
                REQUEST_TYPES.SYNTHETIC,
                scoring_period,
            )

        freezer.stop()

        # fast forward ~12 hrs

        freezer = freeze_time("2024-01-11 12:01:00.136136")
        freezer.start()

        validator.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": EXTERNAL_WEB3_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

        curr_pools = assets_and_pools["pools"]
        for pool in curr_pools.values():
            pool.sync(validator.w3)

        # score previously suggested miner allocations based on how well they are performing now
        # get all the request ids for the pools we should be scoring from the db
        active_alloc_rows = []
        with get_db_connection(validator.config.db_dir, True) as conn:
            active_alloc_rows = get_active_allocs(conn)

        print(f"Active allocs: {active_alloc_rows}")

        with get_db_connection(validator.config.db_dir, True) as conn:
            all_requests = get_request_info(conn)
            print(f"all requests: {all_requests}")

        for active_alloc in active_alloc_rows:
            # calculate rewards for previous active allocations
            miner_uids, rewards = get_rewards(validator, active_alloc)

            rewards_dict = {active_uids[k]: v for k, v in enumerate(list(rewards))}
            sorted_rewards = dict(sorted(rewards_dict.items(), key=lambda item: item[1], reverse=True))  # type: ignore[]

            print(f"sorted rewards: {sorted_rewards}")
            # bt.logging.debug(f"miner rewards: {rewards}")
            print(f"sim penalities: {validator.similarity_penalties}")

            # rewards should not all be the same
            to_compare = torch.empty(rewards.shape)
            torch.fill(to_compare, rewards[0])
            self.assertFalse(torch.equal(rewards, to_compare))

        freezer.stop()


if __name__ == "__main__":
    unittest.main()
