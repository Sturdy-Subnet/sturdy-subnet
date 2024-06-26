import unittest
from unittest import IsolatedAsyncioTestCase
import torch

from sturdy.pools import BasePool
from sturdy.protocol import AllocateAssets
from neurons.validator import Validator
from sturdy.validator.reward import get_rewards
from sturdy.constants import QUERY_TIMEOUT
import copy


class TestValidator(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        config = {
            "mock": True,
            "wandb": {"off": True},
            "mock_n": 16,
            "neuron": {"dont_save_events": True},
        }
        cls.validator = Validator(config=config)
        # TODO: this doesn't work?
        # cls.validator.simulator = Simulator(69)

        cls.assets_and_pools = {
            "pools": {
                "0": BasePool(
                    base_rate=0.03,
                    base_slope=0.072,
                    borrow_amount=int(0.85e18),
                    kink_slope=0.347,
                    optimal_util_rate=0.9,
                    pool_id="0",
                    reserve_size=500e18,
                ),
                "1": BasePool(
                    base_rate=0.01,
                    base_slope=0.011,
                    borrow_amount=int(0.55e18),
                    kink_slope=0.187,
                    optimal_util_rate=0.9,
                    pool_id="1",
                    reserve_size=500e18,
                ),
                "2": BasePool(
                    base_rate=0.02,
                    base_slope=0.067,
                    borrow_amount=int(0.7e18),
                    kink_slope=0.662,
                    optimal_util_rate=0.9,
                    pool_id="2",
                    reserve_size=500e18,
                ),
                "3": BasePool(
                    base_rate=0.01,
                    base_slope=0.044,
                    borrow_amount=int(0.7e18),
                    kink_slope=0.386,
                    optimal_util_rate=0.9,
                    pool_id="3",
                    reserve_size=500e18,
                ),
                "4": BasePool(
                    base_rate=0.03,
                    base_slope=0.044,
                    borrow_amount=int(0.75e18),
                    kink_slope=0.163,
                    optimal_util_rate=0.65,
                    pool_id="4",
                    reserve_size=500e18,
                ),
                "5": BasePool(
                    base_rate=0.05,
                    base_slope=0.021,
                    borrow_amount=int(0.85e18),
                    kink_slope=0.232,
                    optimal_util_rate=0.75,
                    pool_id="5",
                    reserve_size=500e18,
                ),
                "6": BasePool(
                    base_rate=0.01,
                    base_slope=0.062,
                    borrow_amount=int(0.7e18),
                    kink_slope=0.997,
                    optimal_util_rate=0.8,
                    pool_id="6",
                    reserve_size=500e18,
                ),
                "7": BasePool(
                    base_rate=0.02,
                    base_slope=0.098,
                    borrow_amount=int(0.9e18),
                    kink_slope=0.543,
                    optimal_util_rate=0.75,
                    pool_id="7",
                    reserve_size=500e18,
                ),
                "8": BasePool(
                    base_rate=0.01,
                    base_slope=0.028,
                    borrow_amount=int(0.55e18),
                    kink_slope=0.352,
                    optimal_util_rate=0.8,
                    pool_id="8",
                    reserve_size=500e18,
                ),
                "9": BasePool(
                    base_rate=0.04,
                    base_slope=0.066,
                    borrow_amount=int(0.7e18),
                    kink_slope=0.617,
                    optimal_util_rate=0.8,
                    pool_id="9",
                    reserve_size=500e18,
                ),
            },
            "total_assets": int(1000e18),
        }

        cls.allocations = {
            "0": 100e18,
            "1": 100e18,
            "2": 200e18,
            "3": 50e18,
            "4": 200e18,
            "5": 25e18,
            "6": 25e18,
            "7": 50e18,
            "8": 50e18,
            "9": 200e18,
        }

        cls.validator.simulator.initialize(timesteps=50)

    async def test_get_rewards(self):
        print("----==== test_get_rewards ====----")

        assets_and_pools = copy.deepcopy(self.assets_and_pools)
        allocations = copy.deepcopy(self.allocations)

        validator = self.validator

        validator.simulator.init_data(
            init_assets_and_pools=copy.deepcopy(assets_and_pools),
            init_allocations=copy.deepcopy(allocations),
        )

        active_uids = [
            str(uid)
            for uid in range(validator.metagraph.n.item())
            if validator.metagraph.axons[uid].is_serving
        ]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            assets_and_pools=copy.deepcopy(assets_and_pools),
            allocations=copy.deepcopy(allocations),
        )

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

        # TODO: better testing?
        rewards, allocs = get_rewards(
            validator,
            validator.step,
            active_uids,
            responses=responses,
        )

        print(f"allocs: {allocs}")

        # rewards should not all be the same
        to_compare = torch.empty(rewards.shape)
        torch.fill(to_compare, rewards[0])
        self.assertFalse(torch.equal(rewards, to_compare))

        rewards_dict = {active_uids[k]: v for k, v in enumerate(list(rewards))}
        sorted_rewards = {
            k: v
            for k, v in sorted(
                rewards_dict.items(), key=lambda item: item[1], reverse=True
            )
        }

        print(f"sorted rewards: {sorted_rewards}")

    async def test_get_rewards_punish(self):
        print("----==== test_get_rewards_punish ====----")
        validator = self.validator
        assets_and_pools = copy.deepcopy(self.assets_and_pools)

        allocations = copy.deepcopy(self.allocations)
        # increase one of the allocations by +10000  -> clearly this means the miner is cheating!!!
        allocations["0"] += 10000e18

        validator.simulator.reset()
        validator.simulator.init_data(
            init_assets_and_pools=copy.deepcopy(assets_and_pools),
            init_allocations=copy.deepcopy(allocations),
        )

        active_uids = [
            str(uid)
            for uid in range(validator.metagraph.n.item())
            if validator.metagraph.axons[uid].is_serving
        ]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            assets_and_pools=copy.deepcopy(assets_and_pools),
            allocations=copy.deepcopy(allocations),
        )

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

        # TODO: better testing?
        rewards, allocs = get_rewards(
            validator,
            validator.step,
            active_uids,
            responses=responses,
        )

        for _, allocInfo in allocs.items():
            self.assertEqual(allocInfo["apy"], 0)

        # rewards should all be the same (0)
        self.assertEqual(all(rewards), 0)

        rewards_dict = {k: v for k, v in enumerate(list(rewards))}
        sorted_rewards = {
            k: v
            for k, v in sorted(
                rewards_dict.items(), key=lambda item: item[1], reverse=True
            )
        }

        print(f"sorted rewards: {sorted_rewards}")

        assets_and_pools = copy.deepcopy(self.assets_and_pools)

        allocations = copy.deepcopy(self.allocations)
        # set one of the allocations to be negative! This should not be allowed!
        allocations["0"] = -1.0

        validator.simulator.reset()
        validator.simulator.init_data(
            init_assets_and_pools=copy.deepcopy(assets_and_pools),
            init_allocations=copy.deepcopy(allocations),
        )

        active_uids = [
            str(uid)
            for uid in range(validator.metagraph.n.item())
            if validator.metagraph.axons[uid].is_serving
        ]

        active_axons = [validator.metagraph.axons[int(uid)] for uid in active_uids]

        synapse = AllocateAssets(
            assets_and_pools=copy.deepcopy(assets_and_pools),
            allocations=copy.deepcopy(allocations),
        )

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

        # TODO: better testing?
        rewards, allocs = get_rewards(
            validator,
            validator.step,
            active_uids,
            responses=responses,
        )

        for _, allocInfo in allocs.items():
            self.assertEqual(allocInfo["apy"], 0)

        # rewards should all be the same (0)
        self.assertEqual(all(rewards), 0)

        rewards_dict = {k: v for k, v in enumerate(list(rewards))}
        sorted_rewards = {
            k: v
            for k, v in sorted(
                rewards_dict.items(), key=lambda item: item[1], reverse=True
            )
        }

        print(f"sorted rewards: {sorted_rewards}")


if __name__ == "__main__":
    unittest.main()
