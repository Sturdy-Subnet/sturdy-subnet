import unittest
from unittest import TestCase

from sturdy.protocol import AllocateAssets
from sturdy.pools import generate_assets_and_pools
from sturdy.utils.misc import greedy_allocation_algorithm


class TestGreedyAlgorithm(TestCase):
    def test_greedy_allocation_algorithm(self):
        assets_and_pools = generate_assets_and_pools()
        total_assets = assets_and_pools["total_assets"]
        # print(f'pools: {assets_and_pools["pools"]}')
        synapse = AllocateAssets(assets_and_pools=assets_and_pools)
        allocations = greedy_allocation_algorithm(synapse=synapse)
        self.assertLessEqual(sum(allocations.values()), total_assets)


if __name__ == "__main__":
    unittest.main()
