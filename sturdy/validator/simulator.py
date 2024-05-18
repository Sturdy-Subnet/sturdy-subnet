import numpy as np

from sturdy.utils.misc import borrow_rate, supply_rate
from sturdy.pools import generate_assets_and_pools
from sturdy.constants import *
import bittensor as bt


class Simulator(object):
    def __init__(
        self,
        # config,
        timesteps=TIMESTEPS,
        reversion_speed=REVERSION_SPEED,
        stochasticity=STOCHASTICITY,
    ):
        self.timesteps = timesteps
        self.reversion_speed = reversion_speed
        self.stochasticity = stochasticity
        self.assets_and_pools = {}
        self.pool_history = []
        self.rng_state_container = None

    def init_data(self):
        self.assets_and_pools = generate_assets_and_pools(self.rng_state_container)
        # initial pool borrow amounts
        # TODO: use a dictionary instead? use timestep as keys in the dict?
        self.pool_history = [
            {
                uid: {
                    "borrow_amount": pool["borrow_amount"],
                    "reserve_size": pool["reserve_size"],
                    "borrow_rate": borrow_rate(
                        pool["borrow_amount"] / pool["reserve_size"], pool
                    ),
                }
                for uid, pool in self.assets_and_pools["pools"].items()
            }
        ]

    # initialize fresh simulation instance
    def initialize(self):
        # create fresh rng state
        self.rng_state_container = np.random.RandomState()
        self.init_data()

    # reset sim to initial params for rng
    def reset(self):
        if self.rng_state_container is None:
            bt.logging.error(
                "You must have first initialize()-ed the simulation if you'd like to reset it"
            )
        np.random.set_state(self.rng_state_container.get_state())  # type: ignore
        self.init_data()

    # initialize pools
    # Function to update borrow amounts and other pool params based on reversion rate and stochasticity
    def generate_new_pool_data(self):
        latest_pool_data = self.pool_history[-1]
        curr_borrow_rates = np.array(
            [pool["borrow_rate"] for _, pool in latest_pool_data.items()]
        )
        curr_borrow_amounts = np.array(
            [pool["borrow_amount"] for _, pool in latest_pool_data.items()]
        )
        curr_reserve_sizes = np.array(
            [pool["reserve_size"] for _, pool in latest_pool_data.items()]
        )

        median_rate = np.median(curr_borrow_rates)  # Calculate the median borrow rate
        noise = np.random.normal(
            0, self.stochasticity, len(curr_borrow_rates)
        )  # Add some random noise
        rate_changes = (
            -self.reversion_speed * (curr_borrow_rates - median_rate) + noise
        )  # Mean reversion principle
        new_borrow_amounts = (
            curr_borrow_amounts + rate_changes * curr_borrow_amounts
        )  # Update the borrow amounts
        amounts = np.clip(
            new_borrow_amounts, 0, curr_reserve_sizes
        )  # Ensure borrow amounts do not exceed reserves
        pool_uids = list(latest_pool_data.keys())

        new_pool_data = {
            pool_uids[i]: {
                "borrow_amount": amounts[i],
                "reserve_size": curr_reserve_sizes[i],
                "borrow_rate": borrow_rate(
                    amounts[i] / curr_reserve_sizes[i],
                    self.assets_and_pools["pools"][pool_uids[i]],
                ),
            }
            for i in range(len(amounts))
        }

        return new_pool_data

    # run simulation
    def run(self):
        if len(self.pool_history) != 1:
            bt.logging.error("You need to reset() the simulator")
            return
        for _ in range(1, self.timesteps):
            new_info = self.generate_new_pool_data()
            # TODO: do we need to copy?
            self.pool_history.append(new_info.copy())
