import unittest

import numpy as np

from sturdy.constants import *
from sturdy.pools import (
    BasePoolModel,
    generate_assets_and_pools,
    generate_initial_allocations_for_pools,
)
from sturdy.utils.ethmath import wei_mul


class TestPoolAndAllocGeneration(unittest.TestCase):
    def test_generate_assets_and_pools(self) -> None:
        # same seed on every test run
        np.random.seed(69)
        # run test multiple times to to ensure the number generated are
        # within the correct ranges
        for _ in range(100):
            result = generate_assets_and_pools(np.random.RandomState(69))

            pools: dict[str, BasePoolModel] = result["pools"]
            total_borrows = sum([pool.borrow_amount for pool in pools.values()])

            # Assert total assets
            self.assertTrue(
                total_borrows + MIN_TOTAL_ASSETS_OFFSET <= result["total_assets"] <= total_borrows + MAX_TOTAL_ASSETS_OFFSET
            )

            # Assert number of pools
            self.assertEqual(len(result["pools"]), NUM_POOLS)

            # Assert properties of each pool
            for pool_info in result["pools"].values():
                self.assertTrue(hasattr(pool_info, "base_rate"))
                self.assertTrue(
                    MIN_BASE_RATE <= pool_info.base_rate <= MAX_BASE_RATE
                )

                self.assertTrue(hasattr(pool_info, "base_slope"))
                self.assertTrue(MIN_SLOPE <= pool_info.base_slope <= MAX_SLOPE)

                self.assertTrue(hasattr(pool_info, "kink_slope"))
                self.assertTrue(
                    MIN_KINK_SLOPE <= pool_info.kink_slope <= MAX_KINK_SLOPE
                )

                self.assertTrue(hasattr(pool_info, "optimal_util_rate"))
                self.assertTrue(
                    MIN_OPTIMAL_RATE
                    <= pool_info.optimal_util_rate
                    <= MAX_OPTIMAL_RATE
                )

                self.assertTrue(hasattr(pool_info, "reserve_size"))
                self.assertEqual(pool_info.reserve_size, POOL_RESERVE_SIZE)

                self.assertTrue(hasattr(pool_info, "borrow_amount"))
                self.assertTrue(
                    wei_mul(MIN_UTIL_RATE, POOL_RESERVE_SIZE)
                    <= pool_info.borrow_amount
                    <= wei_mul(MAX_UTIL_RATE, POOL_RESERVE_SIZE)
                )

    def test_generate_initial_allocations_for_pools(self) -> None:
        # same seed on every test run
        np.random.seed(69)
        # run test multiple times to to ensure the number generated are
        # within the correct ranges
        for _ in range(100):
            assets_and_pools = generate_assets_and_pools(np.random.RandomState(69))
            max_alloc = assets_and_pools["total_assets"]
            pools = assets_and_pools["pools"]
            result = generate_initial_allocations_for_pools(assets_and_pools)
            result = dict(result.items())

            # Assert number of allocations
            self.assertEqual(len(result), len(pools))


if __name__ == "__main__":
    unittest.main()
