import unittest
from unittest import TestCase

from sturdy.protocol import AllocateAssets
from sturdy.pools import generate_assets_and_pools
from sturdy.utils.misc import greedy_allocation_algorithm
from sturdy.constants import (
    NUM_POOLS,
    MIN_BASE_RATE,
    MAX_BASE_RATE,
    BASE_RATE_STEP,
    MIN_SLOPE,
    MAX_SLOPE,
    MIN_KINK_SLOPE,
    MAX_KINK_SLOPE,
    SLOPE_STEP,
    OPTIMAL_UTIL_RATE,
    OPTIMAL_UTIL_STEP,
    TOTAL_ASSETS,
    MIN_BORROW_AMOUNT,
    MAX_BORROW_AMOUNT,
    BORROW_AMOUNT_STEP,
)


class TestGreedyAlgorithm(TestCase):
    def test_greedy_allocation_algorithm(self):
        assets_and_pools = generate_assets_and_pools()
        # print(f'pools: {assets_and_pools["pools"]}')
        synapse = AllocateAssets(assets_and_pools=assets_and_pools)
        allocations = greedy_allocation_algorithm(synapse=synapse)
        # Assert that all allocated amounts are more than equal to the minimum borrow amounts
        self.assertTrue(
            all(
                amount >= assets_and_pools["pools"][pool_id]["borrow_amount"]
                for pool_id, amount in allocations.items()
            )
        )
        # Assert that the total allocated amount equals the total assets given to the miner
        self.assertAlmostEqual(sum(allocations.values()), TOTAL_ASSETS, places=6)


if __name__ == "__main__":
    unittest.main()
