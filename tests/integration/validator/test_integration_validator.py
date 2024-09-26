import copy
import unittest
from unittest import IsolatedAsyncioTestCase

import numpy as np

from neurons.validator import Validator
from sturdy.pools import generate_assets_and_pools
from sturdy.validator.forward import query_and_score_miners
from sturdy.validator.simulator import Simulator


class TestValidator(IsolatedAsyncioTestCase):
    maxDiff = 4000

    @classmethod
    def setUpClass(cls) -> None:
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

        assets_and_pools = generate_assets_and_pools(np.random.RandomState(seed=420)) # type: ignore[]

        cls.assets_and_pools = {
            "pools": assets_and_pools["pools"],
            "total_assets": int(1000e18),
        }

        cls.contract_addresses = list(assets_and_pools["pools"].keys()) # type: ignore[]

        cls.allocations = {
            cls.contract_addresses[0]: 100e18,
            cls.contract_addresses[1]: 100e18,
            cls.contract_addresses[2]: 200e18,
            cls.contract_addresses[3]: 50e18,
            cls.contract_addresses[4]: 200e18,
            cls.contract_addresses[5]: 25e18,
            cls.contract_addresses[6]: 25e18,
            cls.contract_addresses[7]: 50e18,
            cls.contract_addresses[8]: 50e18,
            cls.contract_addresses[9]: 200e18,
        }

    async def test_query_and_score_miners(self) -> None:
        # use simulator generated assets and pools
        await query_and_score_miners(self.validator)
        self.assertIsNotNone(self.validator.simulator.assets_and_pools)
        self.assertIsNotNone(self.validator.simulator.allocations)
        self.maxDiff = None

        # use user-defined generated assets and pools
        simulator_copy = copy.deepcopy(self.validator.simulator)
        await query_and_score_miners(
            self.validator, assets_and_pools=copy.deepcopy(self.assets_and_pools),
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

    async def test_forward(self) -> None:
        await self.validator.forward()


if __name__ == "__main__":
    unittest.main()
