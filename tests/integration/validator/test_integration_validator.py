import unittest
from unittest import IsolatedAsyncioTestCase
import copy

from neurons.validator import Validator
from sturdy.pools import BasePool
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
                "0": BasePool(
                    base_rate=int(0.03e18),
                    base_slope=int(0.072e18),
                    borrow_amount=int(385e18),
                    kink_slope=int(0.347e18),
                    optimal_util_rate=int(0.9e18),
                    pool_id="0",
                    reserve_size=500e18,
                ),
                "1": BasePool(
                    base_rate=int(0.01e18),
                    base_slope=int(0.011e18),
                    borrow_amount=int(55e18),
                    kink_slope=int(0.187e18),
                    optimal_util_rate=int(0.9e18),
                    pool_id="1",
                    reserve_size=500e18,
                ),
                "2": BasePool(
                    base_rate=int(0.02e18),
                    base_slope=int(0.067e18),
                    borrow_amount=int(270e18),
                    kink_slope=int(0.662e18),
                    optimal_util_rate=int(0.9e18),
                    pool_id="2",
                    reserve_size=500e18,
                ),
                "3": BasePool(
                    base_rate=int(0.01e18),
                    base_slope=int(0.044e18),
                    borrow_amount=int(70e18),
                    kink_slope=int(0.386e18),
                    optimal_util_rate=int(0.9e18),
                    pool_id="3",
                    reserve_size=500e18,
                ),
                "4": BasePool(
                    base_rate=int(0.03e18),
                    base_slope=int(0.044e18),
                    borrow_amount=int(75e18),
                    kink_slope=int(0.163e18),
                    optimal_util_rate=int(0.65e18),
                    pool_id="4",
                    reserve_size=500e18,
                ),
                "5": BasePool(
                    base_rate=int(0.05e18),
                    base_slope=int(0.021e18),
                    borrow_amount=int(185e18),
                    kink_slope=int(0.232e18),
                    optimal_util_rate=int(0.75e18),
                    pool_id="5",
                    reserve_size=500e18,
                ),
                "6": BasePool(
                    base_rate=int(0.01e18),
                    base_slope=int(0.062e18),
                    borrow_amount=int(170e18),
                    kink_slope=int(0.997e18),
                    optimal_util_rate=int(0.8e18),
                    pool_id="6",
                    reserve_size=500e18,
                ),
                "7": BasePool(
                    base_rate=int(0.02e18),
                    base_slope=int(0.098e18),
                    borrow_amount=int(290e18),
                    kink_slope=int(0.543e18),
                    optimal_util_rate=int(0.75e18),
                    pool_id="7",
                    reserve_size=500e18,
                ),
                "8": BasePool(
                    base_rate=int(0.01e18),
                    base_slope=int(0.028e18),
                    borrow_amount=int(355e18),
                    kink_slope=int(0.352e18),
                    optimal_util_rate=int(0.8e18),
                    pool_id="8",
                    reserve_size=500e18,
                ),
                "9": BasePool(
                    base_rate=int(0.04e18),
                    base_slope=int(0.066e18),
                    borrow_amount=int(170e18),
                    kink_slope=int(0.617e18),
                    optimal_util_rate=int(0.8e18),
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
