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

import bittensor as bt
import numpy as np
import torch
from typing import List, Dict, Tuple, Any, Union
import copy

from sturdy.constants import QUERY_TIMEOUT, SIMILARITY_THRESHOLD
from sturdy.utils.misc import supply_rate, check_allocations
from sturdy.protocol import AllocInfo


def get_response_times(uids: List[int], responses, timeout: float) -> Dict[str, float]:
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
        str(uids[idx]): (
            response.dendrite.process_time
            if response.dendrite.process_time is not None
            else timeout
        )
        for idx, response in enumerate(responses)
    }
    # Sorting in ascending order since lower process time is better
    return axon_times


def format_allocations(
    allocations: Dict[str, float],
    assets_and_pools: Dict[str, Union[Dict[str, float], float]],
):
    # TODO: better way to do this?
    if allocations is None:
        allocations = {}
    allocs = allocations.copy()
    pools = assets_and_pools["pools"]

    # pad the allocations
    for pool_id in pools.keys():
        if pool_id not in allocs:
            allocs[pool_id] = 0.0

    # sort the allocations by pool id
    formatted_allocs = {pool_id: allocs[pool_id] for pool_id in sorted(allocs.keys())}

    return formatted_allocs


def reward_miner_apy(
    query: int,
    max_apy: float,
    miner_apy: float,
) -> float:
    # Define a small epsilon to avoid division by zero
    epsilon = 1e-10

    # Check if max_apy is very close to sys.float_info.min
    if abs(max_apy - sys.float_info.min) < epsilon:
        # If max_apy is too close to sys.float_info.min, return a default value
        return 0.0

    # Calculate the adjusted APY reward, avoiding division by zero
    return (miner_apy - sys.float_info.min) / (max_apy - sys.float_info.min + epsilon)


def calculate_penalties(
    similarity_matrix: Dict[str, Dict[str, float]],
    axon_times: Dict[str, float],
    similarity_threshold: float = SIMILARITY_THRESHOLD,
):
    penalties = {miner: 0 for miner in similarity_matrix}

    for miner_a, similarities in similarity_matrix.items():
        for miner_b, similarity in similarities.items():
            if similarity <= similarity_threshold:
                if axon_times[miner_a] <= axon_times[miner_b]:
                    penalties[miner_b] += 1

    return penalties


def calculate_rewards_with_adjusted_penalties(miners, rewards_apy, penalties):
    rewards = torch.zeros(len(miners))
    max_penalty = max(penalties.values()) + 1  # Add 1 to avoid division by zero

    for idx, miner_id in enumerate(miners):
        # Calculate penalty adjustment
        penalty_factor = (max_penalty - penalties[miner_id]) / max_penalty

        # Calculate the final reward
        reward = rewards_apy[idx] * penalty_factor
        rewards[idx] = reward

    return rewards


def get_similarity_matrix(
    apys_and_allocations: Dict[str, Dict[str, Union[Dict[str, float], float]]],
    assets_and_pools: Dict[str, Union[Dict[str, float], float]],
):
    similarity_matrix = {}
    total_assets = assets_and_pools["total_assets"]
    for miner_a, info_a in apys_and_allocations.items():
        _alloc_a = info_a["allocations"]
        alloc_a = np.array(
            list(format_allocations(_alloc_a, assets_and_pools).values())
        )
        similarity_matrix[miner_a] = {}
        for miner_b, info_b in apys_and_allocations.items():
            if miner_a != miner_b:
                _alloc_b = info_b["allocations"]
                alloc_b = np.array(
                    list(format_allocations(_alloc_b, assets_and_pools).values())
                )
                similarity_matrix[miner_a][miner_b] = (
                    np.linalg.norm(alloc_a - alloc_b) / np.sqrt(2 * total_assets**2)
                )

    return similarity_matrix


def adjust_rewards_for_plagiarism(
    rewards_apy: torch.FloatTensor,
    apys_and_allocations: Dict[str, Dict[str, Union[Dict[str, float], float]]],
    assets_and_pools: Dict[str, Union[Dict[str, float], float]],
    uids: List,
    axon_times: Dict[str, float],
) -> torch.FloatTensor:
    """
    Adjusts the annual percentage yield (APY) rewards for miners based on the similarity of their allocations
    to others and their arrival times, penalizing plagiarized or overly similar strategies.

    This function calculates the similarity between each pair of miners' allocation strategies and applies a penalty
    to those whose allocations are too similar to others, considering the order in which they arrived. Miners who
    arrived earlier with unique strategies are given preference, and those with similar strategies arriving later
    are penalized. The final APY rewards are adjusted accordingly.

    Args:
        rewards_apy (torch.FloatTensor): The initial APY rewards for the miners, before adjustments.
        apys_and_allocations (Dict[str, Dict[str, Union[Dict[str, float], float]]]):
            A dictionary containing APY values and allocation strategies for each miner. The keys are miner identifiers,
            and the values are dictionaries that include their allocations and APYs.
        assets_and_pools (Dict[str, Union[Dict[str, float], float]]):
            A dictionary representing the available assets and their corresponding pools.
        uids (List): A list of unique identifiers for the miners.
        axon_times (Dict[str, float]): A dictionary that tracks the arrival times of each miner, with the keys being
            miner identifiers and the values being their arrival times. Earlier times are lower values.

    Returns:
        torch.FloatTensor: The adjusted APY rewards for the miners, accounting for penalties due to similarity with
        other miners' strategies and their arrival times.
    Notes:
        - This function relies on the helper functions `calculate_penalties` and `calculate_rewards_with_adjusted_penalties`
          which are defined separately.
        - The `format_allocations` function used in the similarity calculation converts the allocation dictionaries
          to a consistent format suitable for comparison.
    """
    # Step 1: Calculate pairwise similarity (e.g., using Euclidean distance)
    similarity_matrix = get_similarity_matrix(apys_and_allocations, assets_and_pools)

    # Step 2: Apply penalties considering axon times
    penalties = calculate_penalties(similarity_matrix, axon_times)

    # Step 3: Calculate final rewards with adjusted penalties
    rewards = calculate_rewards_with_adjusted_penalties(uids, rewards_apy, penalties)

    return rewards


def _get_rewards(
    self,
    query: int,
    max_apy: float,
    apys_and_allocations: Dict[str, Dict[str, Union[Dict[str, float], float]]],
    assets_and_pools: Dict[str, Union[Dict[str, float], float]],
    uids: List[int],
    axon_times: List[float],
) -> float:
    """
    Rewards miner responses to request. This method returns a reward
    value for the miner, which is used to update the miner's score.

    Returns:
    - adjusted_rewards: The reward values for the miners.
    """

    rewards_apy = torch.FloatTensor(
        [
            reward_miner_apy(
                query,
                max_apy=max_apy,
                miner_apy=apys_and_allocations[uid]["apy"],
            )
            for uid in uids
        ]
    ).to(self.device)

    adjusted_rewards = adjust_rewards_for_plagiarism(
        rewards_apy, apys_and_allocations, assets_and_pools, uids, axon_times
    )

    return adjusted_rewards


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
    if timesteps == 0:
        return pct_yield * 365
    aggregate_apy = (
        pct_yield / timesteps
    ) * 365  # for simplicity each timestep is a day in the simulator

    return aggregate_apy


def get_rewards(
    self,
    query: int,
    uids: List[str],
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

    bt.logging.debug(
        f"Running simulator for {self.simulator.timesteps} timesteps for each allocation..."
    )
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
        self.simulator.init_data(
            init_assets_and_pools=copy.deepcopy(init_assets_and_pools),
            init_allocations=allocations,
        )

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
            allocs[uids[idx]] = {
                "apy": sys.float_info.min,
                "allocations": None,
            }
        else:
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
    bt.logging.debug(f"allocs:\n{allocs}")

    # Get all the reward results by iteratively calling your reward() function.
    return (
        _get_rewards(
            self,
            query,
            max_apy,
            apys_and_allocations=allocs,
            assets_and_pools=init_assets_and_pools,
            uids=uids,
            axon_times=axon_times,
        ),
        allocs,
    )
