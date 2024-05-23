import unittest
from unittest import IsolatedAsyncioTestCase
import copy

from neurons.validator import Validator
from sturdy.validator.simulator import Simulator

from sturdy.validator.forward import query_and_score_miners


class TestValidator(IsolatedAsyncioTestCase):
    maxDiff = 4000

    @classmethod
    def setUpClass(cls):
        # dont log this in wandb
        config = {
            "mock": True,
            "wandb": {"off": True},
            "mock_n": 16,
            "neuron": {"dont_save_events": True},
            "netuid": 69,
        }
        cls.validator = Validator(config=config)
        # simulator with preset seed
        cls.validator.simulator = Simulator(seed=69)

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
            "total_assets": 1.0,
        }

        cls.allocations = {
            "0": 0.04,
            "1": 0.1025,
            "2": 0.0533,
            "3": 0.2948,
            "4": 0.0216,
            "5": 0.1989,
            "6": 0.1237,
            "7": 0.0119,
            "8": 0.0401,
            "9": 0.1132,
        }

    async def test_query_and_score_miners(self):
        # use simulator generated assets and pools
        await query_and_score_miners(self.validator)
        self.assertIsNotNone(self.validator.simulator.assets_and_pools)
        self.assertIsNotNone(self.validator.simulator.allocations)

        # use user-defined generated assets and pools
        simulator_copy = copy.deepcopy(self.validator.simulator)
        await query_and_score_miners(
            self.validator, assets_and_pools=self.assets_and_pools
        )
        simulator_copy.initialize()
        simulator_copy.init_data(
            init_assets_and_pools=copy.deepcopy(self.assets_and_pools),
        )
        simulator_copy.update_reserves_with_allocs()
        assets_pools_should_be = simulator_copy.assets_and_pools

        assets_pools2 = self.validator.simulator.assets_and_pools
        self.assertEqual(assets_pools2, assets_pools_should_be)
        self.assertIsNotNone(self.validator.simulator.allocations)

    async def test_forward(self):
        await self.validator.forward()


if __name__ == "__main__":
    unittest.main()
