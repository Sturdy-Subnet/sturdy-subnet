# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 Syeam Bin Abdullah

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import sys
import math

import bittensor as bt
import torch
from typing import List, Dict, Tuple, Any, Union
import copy

from sturdy.constants import QUERY_TIMEOUT, STEEPNESS, DIV_FACTOR, NUM_POOLS
from sturdy.utils.misc import supply_rate, check_allocations
from sturdy.protocol import AllocInfo


def get_response_times(uids: List[int], responses, timeout: float):
    """
    Returns a list of axons based on their response times.

    This function pairs each uid with its corresponding axon's response time.
    Lower response times are considered better.

    Args:
        uids (List[int]): List of unique identifiers for each axon.
        responses (List[Response]): List of Response objects corresponding to each axon.

    Returns:
        List[Tuple[int, float]]: A sorted list of tuples, where each tuple contains an axon's uid and its response time.

    Example:
        >>> get_sorted_response_times([1, 2, 3], [response1, response2, response3])
        [(2, 0.1), (1, 0.2), (3, 0.3)]
    """
    axon_times = {
        uids[idx]: (
            response.dendrite.process_time
            if response.dendrite.process_time is not None
            else timeout
        )
        for idx, response in enumerate(responses)
    }
    # Sorting in ascending order since lower process time is better
    return axon_times


def sigmoid_scale(
    axon_time: float,
    num_pools: int = NUM_POOLS,
    steepness: float = STEEPNESS,
    div_factor: float = DIV_FACTOR,
    timeout: float = QUERY_TIMEOUT,
) -> float:
    offset = -float(num_pools) / div_factor
    return (
        (1 / (1 + math.exp(steepness * axon_time + offset)))
        if axon_time < timeout
        else 0
    )


def reward(
    query: int,
    max_apy: float,
    miner_apy: float,
    axon_time: float,
    num_pools: int = NUM_POOLS,
) -> float:
    """
    Reward the miner response to the dummy request. This method returns a reward
    value for the miner, which is used to update the miner's score.

    Returns:
    - float: The reward value for the miner.
    """
    return (0.2 * sigmoid_scale(axon_time, num_pools=num_pools)) + (
        0.8 * miner_apy / max_apy
    )


def calculate_aggregate_apy(
    allocations: Dict[str, float],
    assets_and_pools: Dict[str, Union[Dict[str, float], float]],
    timesteps: int,
    pool_history: Dict[str, Dict[str, Any]],
):
    """
    Calculates aggregate yields given intial assets and pools, pool history, and number of timesteps
    """

    # calculate aggregate yield
    initial_balance = assets_and_pools["total_assets"]
    pct_yield = 0
    for pools in pool_history:
        curr_yield = 0
        for uid, allocs in allocations.items():
            pool_data = pools[uid]
            util_rate = pool_data["borrow_amount"] / pool_data["reserve_size"]
            pool_yield = allocs * supply_rate(util_rate, assets_and_pools["pools"][uid])
            curr_yield += pool_yield
        pct_yield += curr_yield

    pct_yield /= initial_balance
    aggregate_apy = (
        pct_yield / timesteps
    ) * 365  # for simplicity each timestep is a day in the simulator

    return aggregate_apy


def get_rewards(
    self,
    query: int,
    uids: List,
    responses: List,
) -> Tuple[torch.FloatTensor, Dict[int, AllocInfo]]:
    """
    Returns a tensor of rewards for the given query and responses.

    Args:
    - query (int): The query sent to the miner.
    - responses (List[float]): A list of responses from the miner.

    Returns:
    - torch.FloatTensor: A tensor of rewards for the given query and responses.
    - allocs: miner allocations along with their respective yields
    """

    # maximum yield to scale all rewards by
    # total apys of allocations per miner
    max_apy = sys.float_info.min
    apys = {}

    init_assets_and_pools = copy.deepcopy(self.simulator.assets_and_pools)

    for response_idx, response in enumerate(responses):
        # reset simulator for next run
        self.simulator.reset()

        allocations = response.allocations

        # validator miner allocations before running simulation
        # is the miner cheating w.r.t allocations?
        cheating = True
        try:
            cheating = not check_allocations(init_assets_and_pools, allocations)
        except Exception as e:
            bt.logging.error(e)

        # score response very low if miner is cheating somehow or returns allocations with incorrect format
        if cheating:
            miner_uid = uids[response_idx]
            bt.logging.warning(
                f"CHEATER DETECTED  - MINER WITH UID {miner_uid} - PUNISHING 👊😠"
            )
            apys[miner_uid] = sys.float_info.min
            continue

        # miner does not appear to be cheating - so we init simulator data
        self.simulator.init_data(copy.deepcopy(init_assets_and_pools), allocations)

        # update reserves given allocations
        try:
            self.simulator.update_reserves_with_allocs()
        except Exception as e:
            bt.logging.error(e)
            bt.logging.error(
                "Failed to update reserves with miner allocations - PENALIZING MINER"
            )
            miner_uid = uids[response_idx]
            apys[miner_uid] = sys.float_info.min
            continue

        self.simulator.run()

        aggregate_apy = calculate_aggregate_apy(
            allocations,
            init_assets_and_pools,
            self.simulator.timesteps,
            self.simulator.pool_history,
        )

        if aggregate_apy > max_apy:
            max_apy = aggregate_apy

        apys[uids[response_idx]] = aggregate_apy

    axon_times = get_response_times(
        uids=uids, responses=responses, timeout=QUERY_TIMEOUT
    )

    # set apys for miners that took longer than the timeout to minimum
    # TODO: cleaner way to do this?
    for uid in uids:
        if axon_times[uid] >= QUERY_TIMEOUT:
            apys[uid] = sys.float_info.min

    # TODO: should probably move some things around later down the road
    allocs = {}
    for idx in range(len(responses)):
        # TODO: cleaner way to do this?
        if responses[idx].allocations is None or axon_times[uids[idx]] >= QUERY_TIMEOUT:
            continue

        allocs[uids[idx]] = {
            "apy": apys[uids[idx]],
            "allocations": responses[idx].allocations,
        }

    sorted_apys = {
        k: v for k, v in sorted(apys.items(), key=lambda item: item[1], reverse=True)
    }

    sorted_axon_times = {
        k: v for k, v in sorted(axon_times.items(), key=lambda item: item[1])
    }

    bt.logging.debug(f"sorted apys: {sorted_apys}")
    bt.logging.debug(f"sorted axon times: {sorted_axon_times}")

    # Get all the reward results by iteratively calling your reward() function.
    return (
        torch.FloatTensor(
            [
                reward(
                    query,
                    max_apy=max_apy,
                    miner_apy=apys[uid],
                    axon_time=axon_times[uid],
                    num_pools=len(uids),
                )
                for uid in uids
            ]
        ).to(self.device),
        allocs,
    )
