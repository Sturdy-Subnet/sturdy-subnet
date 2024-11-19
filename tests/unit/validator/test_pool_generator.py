import os
import unittest

import numpy as np
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

from sturdy.constants import *
from sturdy.pool_registry.pool_registry import POOL_REGISTRY
from sturdy.pools import (
    assets_pools_for_challenge_data,
)

load_dotenv()
WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL")


class TestPoolAndAllocGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # runs tests on local mainnet fork at block: 21080765
        cls.w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        assert cls.w3.is_connected()

        cls.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": WEB3_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

        cls.contract_address = "0x0669091F451142b3228171aE6aD794cF98288124"
        # Create a funded account for testing
        cls.account = Account.create()
        cls.w3.eth.send_transaction(
            {
                "to": cls.account.address,
                "from": cls.w3.eth.accounts[0],
                "value": cls.w3.to_wei(200000, "ether"),
            }
        )

        cls.snapshot_id = cls.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {cls.snapshot_id}")

    @classmethod
    def tearDownClass(cls) -> None:
        # run this after tests to restore original forked state
        w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))

        w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": WEB3_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

    def setUp(self) -> None:
        self.snapshot_id = self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    def tearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    def test_generate_assets_and_pools(self) -> None:
        # same seed on every test run
        np.random.seed(69)
        # run test multiple times to to ensure the number generated are
        # within the correct ranges
        keys = list(POOL_REGISTRY.keys())
        for idx in range(len(keys)):
            key = keys[idx]
            print(key)
            selected_entry = POOL_REGISTRY[key]
            generated = assets_pools_for_challenge_data(selected_entry, self.w3)
            print(generated)

            pools = generated["assets_and_pools"]["pools"]
            total_assets = generated["assets_and_pools"]["total_assets"]

            # check the member variables of the returned value
            self.assertEqual(list(pools.keys()), list(pools.keys()))
            # check returned total assets
            self.assertGreater(total_assets, 0)


if __name__ == "__main__":
    unittest.main()
