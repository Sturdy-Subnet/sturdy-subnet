import unittest
from sturdy.validator.simulator import Simulator
from sturdy.constants import *
import numpy as np


class TestSimulator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simulator = Simulator(
            timesteps=300, reversion_speed=0.05, stochasticity=0.01
        )

    def test_init_data(self):
        self.simulator.init_data()
        self.assertIsNotNone(self.simulator.assets_and_pools)
        self.assertIsNotNone(self.simulator.pool_history)
        self.assertEqual(len(self.simulator.pool_history), 1)

        initial_pool_data = self.simulator.pool_history[0]
        self.assertEqual(len(initial_pool_data), NUM_POOLS)

        for pool in initial_pool_data.values():
            self.assertIn("borrow_amount", pool)
            self.assertIn("reserve_size", pool)
            self.assertIn("borrow_rate", pool)
            self.assertGreaterEqual(pool["borrow_amount"], 0)
            self.assertGreaterEqual(pool["reserve_size"], pool["borrow_amount"])
            self.assertGreaterEqual(pool["borrow_rate"], 0)


    def test_initialization(self):
        self.simulator.initialize()
        self.assertIsNotNone(self.simulator.rng_state_container)
        init_state_container = self.simulator.rng_state_container
        self.assertIsNotNone(self.simulator.assets_and_pools)
        self.assertIsNotNone(self.simulator.pool_history)
        self.assertEqual(len(self.simulator.pool_history), 1)

        initial_pool_data = self.simulator.pool_history[0]
        self.assertEqual(len(initial_pool_data), NUM_POOLS)

        for pool in initial_pool_data.values():
            self.assertIn("borrow_amount", pool)
            self.assertIn("reserve_size", pool)
            self.assertIn("borrow_rate", pool)
            self.assertGreaterEqual(pool["borrow_amount"], 0)
            self.assertGreaterEqual(pool["reserve_size"], pool["borrow_amount"])
            self.assertGreaterEqual(pool["borrow_rate"], 0)

        # should reinit with fresh rng state
        self.simulator.initialize()
        new_state_container = self.simulator.rng_state_container

        init_state = init_state_container.get_state()
        new_state = new_state_container.get_state()
        are_states_equal = (
            init_state[0] == new_state[0] and  # Compare the type of PRNG
            np.array_equal(init_state[1], new_state[1]) and  # Compare the state of the PRNG
            init_state[2] == new_state[2] and  # Compare the position in the PRNG's state
            init_state[3] == new_state[3] and  # Compare the position in the PRNG's buffer
            init_state[4] == new_state[4]      # Compare the state of the PRNG's buffer
        )

        self.assertFalse(are_states_equal)

    def test_reset(self):
        init_state_container = self.simulator.rng_state_container
        self.simulator.reset()
        new_state_container = self.simulator.rng_state_container
        init_state = init_state_container.get_state()
        new_state = new_state_container.get_state()
        are_states_equal = (
            init_state[0] == new_state[0] and  # Compare the type of PRNG
            np.array_equal(init_state[1], new_state[1]) and  # Compare the state of the PRNG
            init_state[2] == new_state[2] and  # Compare the position in the PRNG's state
            init_state[3] == new_state[3] and  # Compare the position in the PRNG's buffer
            init_state[4] == new_state[4]      # Compare the state of the PRNG's buffer
        )

        self.assertTrue(are_states_equal)

    def test_sim_run(self):
        self.simulator.initialize()
        self.simulator.run()

        self.assertEqual(len(self.simulator.pool_history), self.simulator.timesteps)

        for t in range(1, self.simulator.timesteps):
            pool_data = self.simulator.pool_history[t]
            self.assertEqual(len(pool_data), NUM_POOLS)

            for pool_id, pool in pool_data.items():
                self.assertIn("borrow_amount", pool)
                self.assertIn("reserve_size", pool)
                self.assertIn("borrow_rate", pool)
                self.assertGreaterEqual(pool["borrow_amount"], 0)
                self.assertGreaterEqual(pool["reserve_size"], pool["borrow_amount"])
                self.assertGreaterEqual(pool["borrow_rate"], 0)

                previous_pool = self.simulator.pool_history[t - 1][pool_id]
                self.assertNotEqual(
                    pool["borrow_amount"], previous_pool["borrow_amount"]
                )
                self.assertNotEqual(pool["borrow_rate"], previous_pool["borrow_rate"])

        # pp.pprint(f"assets and pools: \n {self.validator.assets_and_pools}")
        # pp.pprint(f"pool history: \n {self.validator.pool_history}")


if __name__ == "__main__":
    unittest.main()
