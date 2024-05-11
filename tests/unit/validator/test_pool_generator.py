import unittest
import random
from sturdy.pools import generate_assets_and_pools
from sturdy.constants import *


class TestGenerateAssetsAndPools(unittest.TestCase):
    def test_generate_assets_and_pools(self):
        # same seed on every test run
        random.seed(69)
        # run test multiple times to to ensure the number generated are
        # within the correct ranges
        for i in range(0, 100):
            result = generate_assets_and_pools()

            # Assert total assets
            self.assertEqual(result["total_assets"], TOTAL_ASSETS)

            # Assert number of pools
            self.assertEqual(len(result["pools"]), NUM_POOLS)

            # Assert properties of each pool
            for pool_id, pool_info in result["pools"].items():
                self.assertTrue("base_rate" in pool_info)
                self.assertTrue(
                    MIN_BASE_RATE <= pool_info["base_rate"] <= MAX_BASE_RATE
                )

                self.assertTrue("base_slope" in pool_info)
                self.assertTrue(MIN_SLOPE <= pool_info["base_slope"] <= MAX_SLOPE)

                self.assertTrue("kink_slope" in pool_info)
                self.assertTrue(
                    MIN_KINK_SLOPE <= pool_info["kink_slope"] <= MAX_KINK_SLOPE
                )

                self.assertTrue("optimal_util_rate" in pool_info)
                self.assertTrue(
                    MIN_OPTIMAL_UTIL_RATE <= pool_info["optimal_util_rate"] <= MAX_OPTIMAL_UTIL_RATE
                )

                self.assertTrue("borrow_amount" in pool_info)
                self.assertTrue(
                    MIN_BORROW_AMOUNT <= pool_info["borrow_amount"] <= MAX_BORROW_AMOUNT
                )


if __name__ == "__main__":
    unittest.main()
