import unittest
from unittest import IsolatedAsyncioTestCase

from neurons.validator import Validator
from sturdy.validator.simulator import Simulator

# from sturdy.validator.forward import query_and_score_miners


class TestValidator(IsolatedAsyncioTestCase):
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

        # init data and set that as the default allocations

    # TODO: more tests
    # async def test_query_and_score_miners(self):
    #     self.validator.simulator.initialize()
    #     self.validator.simulator.init_data()
    #     assets_pools = self.validator.simulator.assets_and_pools
    #     allocs = self.validator.simulator.allocations
    #     # use simulator generated assets and pools
    #     query_and_score_miners(self.validator)
    #     self.validator.simulator.initialize()
    #     self.validator.simulator.init_data(init_assets_and_pools=cls.assets_and_pools, init_allocations=cls.allocations)

    async def test_forward(self):
        await self.validator.forward()


if __name__ == "__main__":
    unittest.main()
