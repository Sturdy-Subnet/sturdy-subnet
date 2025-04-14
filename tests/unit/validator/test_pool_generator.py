import os
import unittest

import numpy as np
from dotenv import load_dotenv
from eth_account import Account
from web3 import AsyncWeb3

from sturdy.constants import *
from sturdy.pool_registry.pool_registry import POOL_REGISTRY
from sturdy.pools import (
    gen_evm_pools_for_challenge,
)

load_dotenv()
ETHEREUM_MAINNET_PROVIDER_URL = os.getenv("ETHEREUM_MAINNET_PROVIDER_URL")


class TestPoolAndAllocGeneration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 21080765
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

        self.contract_address = "0x0669091F451142b3228171aE6aD794cF98288124"
        # Create a funded account for testing
        self.account = Account.create()
        await self.w3.eth.send_transaction(
            {
                "to": self.account.address,
                "from": (await self.w3.eth.accounts)[0],
                "value": self.w3.to_wei(200000, "ether"),
            }
        )

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    async def asyncTearDown(self) -> None:
        # run this after tests to restore original forked state
        w3 = AsyncWeb3(AsyncWeb3.HTTPProvider("http://127.0.0.1:8545"))

        w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_generate_assets_and_pools(self) -> None:
        # same seed on every test run
        np.random.seed(69)
        # run test multiple times to to ensure the number generated are
        # within the correct ranges
        keys = list(POOL_REGISTRY.keys())
        for idx in range(len(keys)):
            key = keys[idx]
            print(key)
            selected_entry = POOL_REGISTRY[key]
            generated = await gen_evm_pools_for_challenge(selected_entry, self.w3)
            print(generated)

            pools = generated["assets_and_pools"]["pools"]
            total_assets = generated["assets_and_pools"]["total_assets"]

            # check the member variables of the returned value
            self.assertEqual(list(pools.keys()), list(pools.keys()))
            # check returned total assets
            self.assertGreater(total_assets, 0)


if __name__ == "__main__":
    unittest.main()
