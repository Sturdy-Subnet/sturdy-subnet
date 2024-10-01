import copy
from typing import Any

import numpy as np

from sturdy.constants import *
from sturdy.pools import (
    BasePoolModel,
    ChainBasedPoolModel,
    check_allocations,
    generate_assets_and_pools,
    generate_initial_allocations_for_pools,
)
from sturdy.protocol import AllocationsDict
from sturdy.utils.ethmath import wei_mul_arrays


class Simulator:
    def __init__(
        self,
        reversion_speed: float = REVERSION_SPEED,
        seed=None,
    ) -> None:
        self.reversion_speed = reversion_speed
        self.assets_and_pools = {}
        self.allocations = {}
        self.pool_history = []
        self.init_rng = None
        self.rng_state_container: Any = None
        self.seed = seed

    # initializes data - by default these are randomly generated
    def init_data(
        self,
        init_assets_and_pools: dict[str, dict[str, ChainBasedPoolModel | BasePoolModel] | int] | None = None,
        init_allocations: AllocationsDict | None = None,
    ) -> None:
        if self.rng_state_container is None or self.init_rng is None:
            raise RuntimeError("You must have first initialize()-ed the simulation if you'd like to initialize some data")

        if init_assets_and_pools is None:
            self.assets_and_pools: Any = generate_assets_and_pools(
                rng_gen=self.rng_state_container,
            )
        else:
            self.assets_and_pools = init_assets_and_pools

        if init_allocations is None:
            self.allocations = generate_initial_allocations_for_pools(
                self.assets_and_pools,
            )
        else:
            self.allocations = init_allocations

        # initialize pool history
        self.pool_history = [
            {
                uid: copy.deepcopy(pool)
                for uid, pool in self.assets_and_pools["pools"].items()  #
            },
        ]

    # initialize fresh simulation instance
    def initialize(self, timesteps: int | None = None, stochasticity: float | None = None) -> None:
        # create fresh rng state
        self.init_rng = np.random.RandomState(self.seed)
        self.rng_state_container = copy.copy(self.init_rng)

        if timesteps is None:
            self.timesteps = self.rng_state_container.choice(
                np.arange(
                    MIN_TIMESTEPS,
                    MAX_TIMESTEPS + TIMESTEPS_STEP,
                    TIMESTEPS_STEP,
                ),
            )
        else:
            self.timesteps = timesteps

        if stochasticity is None:
            self.stochasticity = self.rng_state_container.choice(
                np.arange(
                    MIN_STOCHASTICITY,
                    MAX_STOCHASTICITY + STOCHASTICITY_STEP,
                    STOCHASTICITY_STEP,
                ),
            )
        else:
            self.stochasticity = stochasticity

        self.rng_state_container = copy.copy(self.init_rng)

    # reset sim to initial params for rng
    def reset(self) -> None:
        if self.rng_state_container is None or self.init_rng is None:
            raise RuntimeError(
                "You must have first initialize()-ed the simulation if you'd like to reset it",
            )
        self.rng_state_container = copy.copy(self.init_rng)

    # update the reserves in the pool with given allocations
    def update_reserves_with_allocs(self, allocs=None) -> None:
        if len(self.pool_history) <= 0 or len(self.assets_and_pools) <= 0 or len(self.allocations) <= 0:
            raise RuntimeError(
                "You must first initialize() and init_data() before updating reserves!!!",
            )

        allocations = self.allocations if allocs is None else allocs

        if len(self.pool_history) != 1:
            raise RuntimeError(
                "You must have first init data for the simulation if you'd like to update reserves",
            )

        for uid, alloc in allocations.items():
            pool = self.assets_and_pools["pools"][uid]
            pool_history_start = self.pool_history[0]
            pool.reserve_size += int(alloc)
            pool.reserve_size = int(pool.reserve_size)
            pool_from_history = pool_history_start[uid]
            pool_from_history.reserve_size += allocations[uid]

    # initialize pools
    # Function to update borrow amounts and other pool params based on reversion rate and stochasticity
    def generate_new_pool_data(self) -> dict:
        latest_pool_data = self.pool_history[-1]
        curr_borrow_rates = np.array([pool.borrow_rate for _, pool in latest_pool_data.items()])
        curr_borrow_amounts = np.array([pool.borrow_amount for _, pool in latest_pool_data.items()])
        curr_reserve_sizes = np.array([pool.reserve_size for _, pool in latest_pool_data.items()])

        median_rate = np.median(curr_borrow_rates)  # Calculate the median borrow rate
        noise = self.rng_state_container.normal(0, self.stochasticity * 1e18, len(curr_borrow_rates))  # Add some random noise
        rate_changes = (-self.reversion_speed * (curr_borrow_rates - median_rate)) + noise  # Mean reversion principle
        new_borrow_amounts = curr_borrow_amounts + wei_mul_arrays(
            rate_changes, curr_borrow_amounts,
        )  # Update the borrow amounts
        amounts = np.clip(new_borrow_amounts, 0, curr_reserve_sizes)  # Ensure borrow amounts do not exceed reserves
        pool_uids = list(latest_pool_data.keys())

        new_pools = [copy.deepcopy(pool) for pool in self.assets_and_pools["pools"].values()]

        for idx, pool in enumerate(new_pools):
            pool.borrow_amount = amounts[idx]

        return {pool_uids[uid]: pool for uid, pool in enumerate(new_pools)}


    # run simulation
    def run(self) -> None:
        if len(self.pool_history) != 1:
            raise RuntimeError("You must first initialize() and init_data() before running the simulation!!!")
        for _ in range(1, self.timesteps):
            new_info = self.generate_new_pool_data()
            self.pool_history.append(new_info.copy())
