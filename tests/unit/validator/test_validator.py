import unittest
from unittest import IsolatedAsyncioTestCase
import sys

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
                "0": {
                    "base_rate": 0.03,
                    "base_slope": 0.072,
                    "borrow_amount": 0.85,
                    "kink_slope": 0.347,
                    "optimal_util_rate": 0.9,
                    "pool_id": "0",
                    "reserve_size": 1.0,
                },
                "1": {
                    "base_rate": 0.01,
                    "base_slope": 0.011,
                    "borrow_amount": 0.55,
                    "kink_slope": 0.187,
                    "optimal_util_rate": 0.9,
                    "pool_id": "1",
                    "reserve_size": 1.0,
                },
                "2": {
                    "base_rate": 0.02,
                    "base_slope": 0.067,
                    "borrow_amount": 0.7,
                    "kink_slope": 0.662,
                    "optimal_util_rate": 0.9,
                    "pool_id": "2",
                    "reserve_size": 1.0,
                },
                "3": {
                    "base_rate": 0.01,
                    "base_slope": 0.044,
                    "borrow_amount": 0.7,
                    "kink_slope": 0.386,
                    "optimal_util_rate": 0.9,
                    "pool_id": "3",
                    "reserve_size": 1.0,
                },
                "4": {
                    "base_rate": 0.03,
                    "base_slope": 0.044,
                    "borrow_amount": 0.75,
                    "kink_slope": 0.163,
                    "optimal_util_rate": 0.65,
                    "pool_id": "4",
                    "reserve_size": 1.0,
                },
                "5": {
                    "base_rate": 0.05,
                    "base_slope": 0.021,
                    "borrow_amount": 0.85,
                    "kink_slope": 0.232,
                    "optimal_util_rate": 0.75,
                    "pool_id": "5",
                    "reserve_size": 1.0,
                },
                "6": {
                    "base_rate": 0.01,
                    "base_slope": 0.062,
                    "borrow_amount": 0.7,
                    "kink_slope": 0.997,
                    "optimal_util_rate": 0.8,
                    "pool_id": "6",
                    "reserve_size": 1.0,
                },
                "7": {
                    "base_rate": 0.02,
                    "base_slope": 0.098,
                    "borrow_amount": 0.9,
                    "kink_slope": 0.543,
                    "optimal_util_rate": 0.75,
                    "pool_id": "7",
                    "reserve_size": 1.0,
                },
                "8": {
                    "base_rate": 0.01,
                    "base_slope": 0.028,
                    "borrow_amount": 0.55,
                    "kink_slope": 0.352,
                    "optimal_util_rate": 0.8,
                    "pool_id": "8",
                    "reserve_size": 1.0,
                },
                "9": {
                    "base_rate": 0.04,
                    "base_slope": 0.066,
                    "borrow_amount": 0.7,
                    "kink_slope": 0.617,
                    "optimal_util_rate": 0.8,
                    "pool_id": "9",
                    "reserve_size": 1.0,
                },
            },
            "total_assets": 2.0,
        }

        cls.allocations = {
            "0": 0.71358786,
            "1": 0.0,
            "2": 0.32651705,
            "3": 0.14316355,
            "4": 0.28526227,
            "5": 0.22716462,
            "6": 0.07140061,
            "7": 0.23290404,
            "8": 0.0,
            "9": 0.0,
        }

        cls.validator.simulator.initialize()

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
            uid
            for uid in range(validator.metagraph.n.item())
            if validator.metagraph.axons[uid].is_serving
        ]

        active_axons = [validator.metagraph.axons[uid] for uid in active_uids]

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

        # rewards should all be the same (1)
        self.assertEqual(any(rewards), 1)

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
        # increase one of the allocations by +1  -> clearly this means the miner is cheating!!!
        allocations["0"] += 1.0

        validator.simulator.reset()
        validator.simulator.init_data(
            init_assets_and_pools=copy.deepcopy(assets_and_pools),
            init_allocations=copy.deepcopy(allocations),
        )

        active_uids = [
            uid
            for uid in range(validator.metagraph.n.item())
            if validator.metagraph.axons[uid].is_serving
        ]

        active_axons = [validator.metagraph.axons[uid] for uid in active_uids]

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
            self.assertAlmostEqual(allocInfo["apy"], sys.float_info.min, places=18)

        # rewards should all be the same (1)
        self.assertEqual(any(rewards), 1)

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
            uid
            for uid in range(validator.metagraph.n.item())
            if validator.metagraph.axons[uid].is_serving
        ]

        active_axons = [validator.metagraph.axons[uid] for uid in active_uids]

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
            self.assertAlmostEqual(allocInfo["apy"], sys.float_info.min, places=18)

        # rewards should all be the same (1)
        self.assertEqual(any(rewards), 1)

        rewards_dict = {k: v for k, v in enumerate(list(rewards))}
        sorted_rewards = {
            k: v
            for k, v in sorted(
                rewards_dict.items(), key=lambda item: item[1], reverse=True
            )
        }

        print(f"sorted rewards: {sorted_rewards}")


if __name__ == "__main__":
    print("hello")
    unittest.main()
