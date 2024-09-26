import copy
import unittest
from unittest import IsolatedAsyncioTestCase

import numpy as np
import torch

from neurons.validator import Validator
from sturdy.constants import QUERY_TIMEOUT
from sturdy.mock import MockDendrite
from sturdy.pools import generate_assets_and_pools
from sturdy.protocol import REQUEST_TYPES, AllocateAssets, AllocationsDict
from sturdy.validator.reward import get_rewards


class TestValidator(IsolatedAsyncioTestCase):
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
        # TODO: this doesn't work?
        # cls.validator.simulator = Simulator(69)

        assets_and_pools = generate_assets_and_pools(np.random.RandomState(seed=420))

        cls.assets_and_pools = {
            "pools": assets_and_pools["pools"],
            "total_assets": int(1000e18),
        }

        cls.contract_addresses: list[str] = list(assets_and_pools["pools"].keys())  # type: ignore[]

        cls.allocations: AllocationsDict = {
            cls.contract_addresses[0]: int(100e18),
            cls.contract_addresses[1]: int(100e18),
            cls.contract_addresses[2]: int(200e18),
            cls.contract_addresses[3]: int(50e18),
            cls.contract_addresses[4]: int(200e18),
            cls.contract_addresses[5]: int(25e18),
            cls.contract_addresses[6]: int(25e18),
            cls.contract_addresses[7]: int(50e18),
            cls.contract_addresses[8]: int(50e18),
            cls.contract_addresses[9]: int(200e18),
        }

        cls.validator.simulator.initialize(timesteps=50)

    async def test_get_rewards(self) -> None:
        print("----==== test_get_rewards ====----")

        assets_and_pools = copy.deepcopy(self.assets_and_pools)
        allocations = copy.deepcopy(self.allocations)

        validator = self.validator

        validator.simulator.init_data(
            init_assets_and_pools=copy.deepcopy(assets_and_pools),
            init_allocations=copy.deepcopy(allocations),
        )

        active_uids = [str(uid) for uid in range(validator.metagraph.n.item()) if validator.metagraph.axons[uid].is_serving]  # type: ignore[]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=copy.deepcopy(assets_and_pools),
            allocations=copy.deepcopy(allocations),
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
            self.assertEqual(response.assets_and_pools, assets_and_pools)
            self.assertLessEqual(sum(response.allocations.values()), assets_and_pools["total_assets"])

        rewards, allocs = get_rewards(
            validator,
            validator.step,
            active_uids,
            responses=responses,
            assets_and_pools=assets_and_pools,
        )

        print(f"allocs: {allocs}")

        # rewards should not all be the same
        to_compare = torch.empty(rewards.shape)
        torch.fill(to_compare, rewards[0])
        self.assertFalse(torch.equal(rewards, to_compare))

        rewards_dict = {active_uids[k]: v for k, v in enumerate(list(rewards))}
        sorted_rewards = dict(sorted(rewards_dict.items(), key=lambda item: item[1], reverse=True))  # type: ignore[]

        print(f"sorted rewards: {sorted_rewards}")

    async def test_get_rewards_punish(self) -> None:
        print("----==== test_get_rewards_punish ====----")
        validator = self.validator
        assets_and_pools = copy.deepcopy(self.assets_and_pools)

        allocations = copy.deepcopy(self.allocations)
        # increase one of the allocations by +10000  -> clearly this means the miner is cheating!!!
        allocations[self.contract_addresses[0]] += int(10000e18)

        validator.simulator.reset()
        validator.simulator.init_data(
            init_assets_and_pools=copy.deepcopy(assets_and_pools),
            init_allocations=copy.deepcopy(allocations),
        )

        active_uids = [str(uid) for uid in range(validator.metagraph.n.item()) if validator.metagraph.axons[uid].is_serving]  # type: ignore[]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=copy.deepcopy(assets_and_pools),
            allocations=copy.deepcopy(allocations),
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
            self.assertEqual(response.assets_and_pools, assets_and_pools)
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

        assets_and_pools = copy.deepcopy(self.assets_and_pools)

        allocations = copy.deepcopy(self.allocations)
        # set one of the allocations to be negative! This should not be allowed!
        allocations[self.contract_addresses[0]] = -1

        validator.simulator.reset()
        validator.simulator.init_data(
            init_assets_and_pools=copy.deepcopy(assets_and_pools),
            init_allocations=copy.deepcopy(allocations),
        )

        active_uids = [str(uid) for uid in range(validator.metagraph.n.item()) if validator.metagraph.axons[uid].is_serving]  # type: ignore[]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=copy.deepcopy(assets_and_pools),
            allocations=copy.deepcopy(allocations),
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
            self.assertEqual(response.assets_and_pools, assets_and_pools)
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


if __name__ == "__main__":
    unittest.main()
