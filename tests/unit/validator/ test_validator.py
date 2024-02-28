import unittest
from unittest import TestCase

from sturdy.protocol import AllocateAssets
from neurons.validator import Validator
from sturdy.validator.reward import get_rewards


class TestGreedyAlgorithm(TestCase):
    def test_get_rewards(self):
        # TODO: use config.mock? create a config json file for mock validator?
        config = {"mock": True}
        validator = Validator(config=config)
        assets_and_pools = {
            "total_assets": 1.0,
            "pools": {
                0: {
                    "pool_id": 0,
                    "base_rate": 0.0,
                    "base_slope": 0.011,
                    "kink_slope": 2.0140000000000002,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.032,
                },
                1: {
                    "pool_id": 1,
                    "base_rate": 0.01,
                    "base_slope": 0.012,
                    "kink_slope": 1.3,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.02,
                },
                2: {
                    "pool_id": 2,
                    "base_rate": 0.01,
                    "base_slope": 0.015,
                    "kink_slope": 0.502,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.006,
                },
                3: {
                    "pool_id": 3,
                    "base_rate": 0.0,
                    "base_slope": 0.048,
                    "kink_slope": 1.233,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.08,
                },
                4: {
                    "pool_id": 4,
                    "base_rate": 0.0,
                    "base_slope": 0.032,
                    "kink_slope": 2.5060000000000002,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.006,
                },
                5: {
                    "pool_id": 5,
                    "base_rate": 0.01,
                    "base_slope": 0.020999999999999998,
                    "kink_slope": 2.633,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.081,
                },
                6: {
                    "pool_id": 6,
                    "base_rate": 0.0,
                    "base_slope": 0.032,
                    "kink_slope": 2.716,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.068,
                },
                7: {
                    "pool_id": 7,
                    "base_rate": 0.0,
                    "base_slope": 0.019000000000000003,
                    "kink_slope": 0.8180000000000001,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.007,
                },
                8: {
                    "pool_id": 8,
                    "base_rate": 0.0,
                    "base_slope": 0.037,
                    "kink_slope": 2.934,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.023,
                },
                9: {
                    "pool_id": 9,
                    "base_rate": 0.01,
                    "base_slope": 0.011,
                    "kink_slope": 1.609,
                    "optimal_util_rate": 0.8,
                    "borrow_amount": 0.09,
                },
            },
        }
        allocations = {
            0: 0.04,
            1: 0.1025,
            2: 0.0533,
            3: 0.2948,
            4: 0.0216,
            5: 0.1989,
            6: 0.1237,
            7: 0.0119,
            8: 0.0401,
            9: 0.1132,
        }
        responses = [AllocateAssets(assets_and_pools=assets_and_pools, allocations=allocations)]

        sorted_responses = {k: v for k, v in sorted(allocations.items(), key=lambda item: item[1], reverse=True)}

        print(f"sorted responses: {sorted_responses}")
        rewards = get_rewards(
            validator,
            validator.step,
            assets_and_pools=assets_and_pools,
            responses=responses
        )

        rewards_dict = {k:v for k,v in enumerate(list(rewards))}  
        sorted_rewards = {k: v for k, v in sorted(rewards_dict.items(), key=lambda item: item[1], reverse=True)}

        print(f"sorted rewards: {sorted_rewards}")

if __name__ == "__main__":
    unittest.main()