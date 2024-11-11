import os
import unittest
from copy import copy
from unittest import IsolatedAsyncioTestCase

import numpy as np
import torch
from dotenv import load_dotenv
from web3 import Web3

from neurons.validator import Validator
from sturdy.algo import naive_algorithm
from sturdy.constants import QUERY_TIMEOUT
from sturdy.mock import MockDendrite
from sturdy.pools import generate_challenge_data
from sturdy.protocol import REQUEST_TYPES, AllocateAssets
from sturdy.validator.forward import query_and_score_miners
from sturdy.validator.reward import get_rewards

load_dotenv()
EXTERNAL_WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL")
os.environ["WEB_PROVIDER_URL"] = "http://127.0.0.1:8545"


# TODO: more comprehensive integration testing - with in-mem sql db and everythin'
class TestValidator(IsolatedAsyncioTestCase):
    maxDiff = 4000

    @classmethod
    def setUpClass(cls) -> None:
        np.random.seed(69)  # noqa: NPY002
        config = {
            "mock": True,
            "wandb": {"off": True},
            "mock_n": 16,
            "neuron": {"dont_save_events": True},
        }

        cls.validator = Validator(config=config)
        w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        cls.validator.w3 = w3
        assert cls.validator.w3.is_connected()

        cls.validator.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": EXTERNAL_WEB3_PROVIDER_URL,
                        "blockNumber": 21080765,
                    },
                },
            ],
        )

        generated_data = generate_challenge_data(cls.validator.w3, np.random.RandomState(seed=420))
        cls.assets_and_pools = generated_data["assets_and_pools"]

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=copy(cls.assets_and_pools),
        )

        cls.allocations = naive_algorithm(cls.validator, synapse)

        cls.contract_addresses: list[str] = list(cls.assets_and_pools["pools"].keys())  # type: ignore[]

    async def test_get_rewards(self) -> None:
        print("----==== test_get_rewards ====----")

        assets_and_pools = copy(self.assets_and_pools)
        allocations = copy(self.allocations)

        validator = self.validator

        active_uids = [str(uid) for uid in range(validator.metagraph.n.item()) if validator.metagraph.axons[uid].is_serving]  # type: ignore[]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=copy(assets_and_pools),
            allocations=copy(allocations),
        )

        validator.dendrite = MockDendrite(wallet=validator.wallet, custom_allocs=True)
        responses = await validator.dendrite(
            # Send the query to selected miner axons in the network.
            axons=active_axons,
            # Construct a dummy query. This simply contains a single integer.
            synapse=synapse,
            deserialize=False,
            timeout=QUERY_TIMEOUT,
        )

        for response in responses:
            # TODO: is this necessary?
            # self.assertEqual(response.assets_and_pools, self.assets_and_pools)
            self.assertLessEqual(sum(response.allocations.values()), assets_and_pools["total_assets"])

        rewards, allocs = get_rewards(
            validator,
            validator.step,
            active_uids,
            responses=responses,
            assets_and_pools=assets_and_pools,
        )

        print(f"allocs: {allocs}")

        rewards_dict = {active_uids[k]: v for k, v in enumerate(list(rewards))}
        sorted_rewards = dict(sorted(rewards_dict.items(), key=lambda item: item[1], reverse=True))  # type: ignore[]

        print(f"sorted rewards: {sorted_rewards}")

        # rewards should not all be the same
        to_compare = torch.empty(rewards.shape)
        torch.fill(to_compare, rewards[0])
        self.assertFalse(torch.equal(rewards, to_compare))

    async def test_get_rewards_punish(self) -> None:
        print("----==== test_get_rewards_punish ====----")
        validator = self.validator
        assets_and_pools = copy(self.assets_and_pools)

        allocations = copy(self.allocations)
        # increase one of the allocations by +10000  -> clearly this means the miner is cheating!!!
        allocations[self.contract_addresses[0]] += int(10000e18)

        active_uids = [str(uid) for uid in range(validator.metagraph.n.item()) if validator.metagraph.axons[uid].is_serving]  # type: ignore[]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=copy(assets_and_pools),
            allocations=copy(allocations),
        )

        validator.dendrite = MockDendrite(wallet=validator.wallet)
        responses = await validator.dendrite(
            # Send the query to selected miner axons in the network.
            axons=active_axons,
            # Construct a dummy query. This simply contains a single integer.
            synapse=synapse,
            deserialize=False,
            timeout=QUERY_TIMEOUT,
        )

        for response in responses:
            # TODO: is this necessary?
            # self.assertEqual(response.assets_and_pools, assets_and_pools)
            self.assertEqual(response.allocations, allocations)

        rewards, allocs = get_rewards(
            validator,
            validator.step,
            active_uids,
            responses=responses,
            assets_and_pools=assets_and_pools,
        )

        for allocInfo in allocs.values():
            self.assertEqual(allocInfo["apy"], 0)

        # rewards should all be the same (0)
        self.assertEqual(all(rewards), 0)

        rewards_dict = dict(enumerate(list(rewards)))
        sorted_rewards = dict(sorted(rewards_dict.items(), key=lambda item: item[1], reverse=True))  # type: ignore[]

        print(f"sorted rewards: {sorted_rewards}")

        assets_and_pools = copy(self.assets_and_pools)

        allocations = copy(self.allocations)
        # set one of the allocations to be negative! This should not be allowed!
        allocations[self.contract_addresses[0]] = -1

        active_uids = [str(uid) for uid in range(validator.metagraph.n.item()) if validator.metagraph.axons[uid].is_serving]  # type: ignore[]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=copy(assets_and_pools),
            allocations=copy(allocations),
        )

        validator.dendrite = MockDendrite(wallet=validator.wallet)
        responses = await validator.dendrite(
            # Send the query to selected miner axons in the network.
            axons=active_axons,
            # Construct a dummy query. This simply contains a single integer.
            synapse=synapse,
            deserialize=False,
            timeout=QUERY_TIMEOUT,
        )

        for response in responses:
            # TODO: is this necessary?
            # self.assertEqual(response.assets_and_pools, assets_and_pools)
            self.assertEqual(response.allocations, allocations)

        rewards, allocs = get_rewards(
            validator,
            validator.step,
            active_uids,
            responses=responses,
            assets_and_pools=assets_and_pools,
        )

        for allocInfo in allocs.values():
            self.assertEqual(allocInfo["apy"], 0)

        # rewards should all be the same (0)
        self.assertEqual(all(rewards), 0)

        rewards_dict = dict(enumerate(list(rewards)))
        sorted_rewards = dict(sorted(rewards_dict.items(), key=lambda item: item[1], reverse=True))  # type: ignore[]

        print(f"sorted rewards: {sorted_rewards}")

    async def test_query_and_score_miners(self) -> None:
        await query_and_score_miners(self.validator, assets_and_pools=self.assets_and_pools)

    async def test_forward(self) -> None:
        await self.validator.forward()


if __name__ == "__main__":
    unittest.main()
