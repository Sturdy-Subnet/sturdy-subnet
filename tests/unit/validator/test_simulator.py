import unittest
from sturdy.utils.ethmath import wei_div
from sturdy.validator.simulator import Simulator
from sturdy.constants import *
from sturdy.utils.misc import borrow_rate
import numpy as np
import copy


def chk_eq_state(init_state, new_state):
    return (
        init_state[0] == new_state[0]  # Compare the type of PRNG
        and np.array_equal(init_state[1], new_state[1])  # Compare the state of the PRNG
        and init_state[2] == new_state[2]  # Compare the position in the PRNG's state
        and init_state[3] == new_state[3]  # Compare the position in the PRNG's buffer
        and init_state[4] == new_state[4]  # Compare the state of the PRNG's buffer
    )


class TestSimulator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulator = Simulator(reversion_speed=0.05)

    def test_init_data(self):
        self.simulator.rng_state_container = np.random.RandomState(69)
        self.simulator.init_rng = np.random.RandomState(69)
        self.simulator.init_data()
        self.assertIsNotNone(self.simulator.assets_and_pools)
        self.assertIsNotNone(self.simulator.allocations)
        self.assertIsNotNone(self.simulator.pool_history)
        self.assertEqual(len(self.simulator.pool_history), 1)

        initial_pool_data = self.simulator.pool_history[0]
        self.assertEqual(len(initial_pool_data), NUM_POOLS)

        for pool in initial_pool_data.values():
            self.assertTrue(hasattr(pool, "borrow_amount"))
            self.assertTrue(hasattr(pool, "reserve_size"))
            self.assertTrue(hasattr(pool, "borrow_rate"))
            self.assertGreaterEqual(pool.borrow_amount, 0)
            self.assertGreaterEqual(pool.reserve_size, pool.borrow_amount)
            self.assertGreaterEqual(pool.borrow_rate, 0)

        self.simulator = Simulator(
            reversion_speed=0.05,
        )

        # should raise error
        self.assertRaises(RuntimeError, self.simulator.init_data)

    def test_update_reserves_with_allocs(self):
        self.simulator.rng_state_container = np.random.RandomState(69)
        self.simulator.init_rng = np.random.RandomState(69)
        self.simulator.init_data()

        init_pools = copy.deepcopy(self.simulator.assets_and_pools["pools"])

        contract_addresses = [addr for addr in self.simulator.assets_and_pools["pools"]]

        allocations = {
            contract_addresses[i]: self.simulator.assets_and_pools["total_assets"]
            / len(init_pools)
            for i in range(len(init_pools))
        }

        self.simulator.update_reserves_with_allocs(allocations)

        for uid, init_pool in init_pools.items():
            # check pools
            new_pool = self.simulator.assets_and_pools["pools"][uid]
            reserve_should_be = allocations[uid] + init_pool.reserve_size
            self.assertEqual(reserve_should_be, new_pool.reserve_size)

            # check init pool_history datapoint
            new_pool_hist_init = self.simulator.pool_history[0][uid]
            b_rate_should_be = borrow_rate(
                wei_div(
                    new_pool_hist_init.borrow_amount, new_pool_hist_init.reserve_size
                ),
                new_pool,
            )
            self.assertEqual(reserve_should_be, new_pool_hist_init.reserve_size)
            self.assertEqual(b_rate_should_be, new_pool_hist_init.borrow_rate)

    # we shouldn't need to list out all the pools we are allocating to
    # the ones that are not lists will not be allocated to at all
    def test_update_reserves_with_allocs_partial(self):
        self.simulator.rng_state_container = np.random.RandomState(69)
        self.simulator.init_rng = np.random.RandomState(69)
        self.simulator.init_data()

        init_pools = copy.deepcopy(self.simulator.assets_and_pools["pools"])
        total_assets = self.simulator.assets_and_pools["total_assets"]

        contract_addresses = [addr for addr in self.simulator.assets_and_pools["pools"]]

        allocs = {
            contract_addresses[0]: total_assets / 10
        }  # should be 0.1 if total assets is 1

        self.simulator.update_reserves_with_allocs(allocs)

        for uid, alloc in allocs.items():
            # for uid, init_pool in init_pools.items():
            # check pools
            init_pool = init_pools[uid]
            new_pool = self.simulator.assets_and_pools["pools"][uid]
            reserve_should_be = alloc + init_pool.reserve_size
            self.assertEqual(reserve_should_be, new_pool.reserve_size)

            # check init pool_history datapoint
            new_pool_hist_init = self.simulator.pool_history[0][uid]
            b_rate_should_be = borrow_rate(
                wei_div(
                    new_pool_hist_init.borrow_amount, new_pool_hist_init.reserve_size
                ),
                new_pool,
            )
            self.assertEqual(reserve_should_be, new_pool_hist_init.reserve_size)
            self.assertEqual(b_rate_should_be, new_pool_hist_init.borrow_rate)

    def test_initialization(self):
        self.simulator.initialize(timesteps=50)
        self.assertIsNotNone(self.simulator.init_rng)
        self.assertIsNotNone(self.simulator.rng_state_container)
        init_state_container = copy.deepcopy(self.simulator.init_rng)
        init_state = init_state_container.get_state()
        rng_state = self.simulator.rng_state_container.get_state()
        states_equal = chk_eq_state(init_state, rng_state)
        self.assertTrue(states_equal)

        # should reinit with fresh rng state
        self.simulator.initialize(timesteps=50)
        new_state_container = copy.deepcopy(self.simulator.rng_state_container)

        new_state = new_state_container.get_state()
        are_states_equal = chk_eq_state(init_state, new_state)

        self.assertFalse(are_states_equal)

    def test_reset(self):
        self.simulator.initialize(timesteps=50)
        self.simulator.init_data()
        init_state_container = copy.deepcopy(self.simulator.init_rng)
        init_state = init_state_container.get_state()
        init_assets_pools = copy.deepcopy(self.simulator.assets_and_pools)
        init_allocs = copy.deepcopy(self.simulator.allocations)
        # use the rng
        for i in range(10):
            self.simulator.rng_state_container.rand()

        after_container = self.simulator.rng_state_container
        new_state = after_container.get_state()

        are_states_equal = chk_eq_state(init_state, new_state)
        self.assertFalse(are_states_equal)

        self.simulator.reset()

        new_init_state_container = self.simulator.init_rng
        new_state_container = self.simulator.rng_state_container
        new_init_state = new_init_state_container.get_state()
        new_state = new_state_container.get_state()

        are_states_equal = chk_eq_state(init_state, new_init_state)
        self.assertTrue(are_states_equal)

        are_states_equal = chk_eq_state(new_state, new_init_state)
        self.assertTrue(are_states_equal)

        new_assets_pools = copy.deepcopy(self.simulator.assets_and_pools)
        new_allocs = copy.deepcopy(self.simulator.allocations)

        self.assertEqual(init_allocs, new_allocs)
        self.assertEqual(init_assets_pools, new_assets_pools)

        self.simulator = Simulator(
            reversion_speed=0.05,
        )

        # should raise error
        self.assertRaises(RuntimeError, self.simulator.reset)

    def test_sim_run(self):
        self.simulator.initialize(timesteps=50)
        self.simulator.init_data()
        self.simulator.run()

        self.assertEqual(len(self.simulator.pool_history), self.simulator.timesteps)

        # test to see if we're recording the right things

        for t in range(1, self.simulator.timesteps):
            pool_data = self.simulator.pool_history[t]
            self.assertEqual(len(pool_data), NUM_POOLS)

            for contract_addr, pool in pool_data.items():
                self.assertTrue(hasattr(pool, "borrow_amount"))
                self.assertTrue(hasattr(pool, "reserve_size"))
                self.assertTrue(hasattr(pool, "borrow_rate"))
                self.assertGreaterEqual(pool.borrow_amount, 0)
                self.assertGreaterEqual(pool.reserve_size, pool.borrow_amount)
                self.assertGreaterEqual(pool.borrow_rate, 0)

        for contract_addr, _ in self.simulator.assets_and_pools["pools"].items():
            borrow_amounts = [
                self.simulator.pool_history[T][contract_addr].borrow_amount
                for T in range(1, self.simulator.timesteps)
            ]
            borrow_rates = [
                self.simulator.pool_history[T][contract_addr].borrow_rate
                for T in range(1, self.simulator.timesteps)
            ]

            self.assertTrue(
                borrow_amounts.count(borrow_amounts[0]) < len(borrow_amounts)
            )
            self.assertTrue(borrow_rates.count(borrow_rates[0]) < len(borrow_rates))

        # check if simulation runs the same across "reset()s"
        # first run
        self.simulator.initialize(timesteps=50)
        self.simulator.init_data()
        self.simulator.run()
        pool_history0 = copy.deepcopy(self.simulator.pool_history)
        # second run - after reset
        self.simulator.reset()
        self.simulator.init_data()
        self.simulator.run()
        pool_history1 = self.simulator.pool_history
        self.assertEqual(pool_history0, pool_history1)

        self.simulator = Simulator(
            reversion_speed=0.05,
        )

        # should raise error
        self.assertRaises(RuntimeError, self.simulator.run)

        # pp.pprint(f"assets and pools: \n {self.validator.assets_and_pools}")
        # pp.pprint(f"pool history: \n {self.validator.pool_history}")


if __name__ == "__main__":
    unittest.main()
