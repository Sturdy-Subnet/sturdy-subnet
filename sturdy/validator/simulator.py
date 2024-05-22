import numpy as np
from typing import Dict, Union

from sturdy.utils.misc import borrow_rate, check_allocations
from sturdy.pools import (
    generate_assets_and_pools,
    generate_initial_allocations_for_pools,
)
from sturdy.constants import *
import copy


class Simulator(object):
    def __init__(
        self,
        # config,
        timesteps=TIMESTEPS,
        reversion_speed=REVERSION_SPEED,
        stochasticity=STOCHASTICITY,
        seed=None,
    ):
        self.timesteps = timesteps
        self.reversion_speed = reversion_speed
        self.stochasticity = stochasticity
        self.assets_and_pools = {}
        self.allocations = {}
        self.pool_history = []
        self.init_rng = None
        self.rng_state_container = None
        self.seed = seed

    # initializes data - by default these are randomly generated
    def init_data(
        self,
        init_assets_and_pools: Dict[str, Union[Dict[str, float], float]] = None,
        init_allocations: Dict[str, float] = None,
    ):
        if self.rng_state_container is None or self.init_rng is None:
            raise RuntimeError(
                "You must have first initialize()-ed the simulation if you'd like to initialize some data"
            )

        if init_assets_and_pools is None:
            self.assets_and_pools = generate_assets_and_pools(
                rng_gen=self.rng_state_container
            )
        else:
            self.assets_and_pools = init_assets_and_pools

        if init_allocations is None:
            self.allocations = generate_initial_allocations_for_pools(
                self.assets_and_pools, rng_gen=self.rng_state_container
            )
        else:
            self.allocations = init_allocations

        # initialize pool history
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
        self.init_rng = np.random.RandomState(self.seed)
        self.rng_state_container = copy.copy(self.init_rng)

    # reset sim to initial params for rng
    def reset(self):
        if self.rng_state_container is None or self.init_rng is None:
            raise RuntimeError(
                "You must have first initialize()-ed the simulation if you'd like to reset it"
            )
        self.rng_state_container = copy.copy(self.init_rng)

    # update the reserves in the pool with given allocations
    def update_reserves_with_allocs(self, allocs=None):
        if (
            len(self.pool_history) != 1
            or len(self.assets_and_pools) <= 0
            or len(self.allocations) <= 0
        ):
            raise RuntimeError(
                "You must first initialize() and init_data() before running the simulation!!!"
            )

        if allocs is None:
            allocations = self.allocations
        else:
            allocations = allocs

        check_allocations(self.assets_and_pools, allocations)

        if len(self.pool_history) != 1:
            raise RuntimeError(
                "You must have first init data for the simulation if you'd like to update reserves"
            )

        for uid, alloc in allocations.items():
            pool = self.assets_and_pools["pools"][uid]
            pool_history_start = self.pool_history[0]
            pool["reserve_size"] += alloc
            pool_from_history = pool_history_start[uid]
            pool_from_history["reserve_size"] += allocations[uid]
            pool_from_history["borrow_rate"] = borrow_rate(
                pool["borrow_amount"] / pool["reserve_size"], pool
            )

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
        noise = self.rng_state_container.normal(
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
            raise RuntimeError(
                "You must first initialize() and init_data() before running the simulation!!!"
            )
        for _ in range(1, self.timesteps):
            new_info = self.generate_new_pool_data()
            # TODO: do we need to copy?
            self.pool_history.append(new_info.copy())
