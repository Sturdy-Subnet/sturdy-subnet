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

import copy
from typing import Any, cast

import bittensor as bt
import numpy as np
import torch

from sturdy.constants import QUERY_TIMEOUT, SIMILARITY_THRESHOLD
from sturdy.pools import POOL_TYPES, BasePoolModel, ChainBasedPoolModel, check_allocations
from sturdy.protocol import REQUEST_TYPES, AllocationsDict, AllocInfo
from sturdy.utils.ethmath import wei_div, wei_mul


def get_response_times(uids: list[str], responses, timeout: float) -> dict[str, float]:
    """
    Returns a list of axons based on their response times.

    This function pairs each uid with its corresponding axon's response time.
    Lower response times are considered better.

    Args:
        uids (list[int]): list of unique identifiers for each axon.
        responses (list[Response]): list of Response objects corresponding to each axon.

    Returns:
        list[Tuple[int, float]]: A sorted list of tuples, where each tuple contains an axon's uid and its response time.

    Example:
        >>> get_sorted_response_times(
        ...     [1, 2, 3],
        ...     [
        ...         response1,
        ...         response2,
        ...         response3,
        ...     ],
        ... )
        [(2, 0.1), (1, 0.2), (3, 0.3)]
    """
    return {
        str(uids[idx]): (response.dendrite.process_time if response.dendrite.process_time is not None else timeout)
        for idx, response in enumerate(responses)
    }
    # Sorting in ascending order since lower process time is better


def format_allocations(
    allocations: AllocationsDict,
    assets_and_pools: dict,
) -> AllocationsDict:
    # TODO: better way to do this?
    if allocations is None:
        allocations = {}
    allocs = allocations.copy()
    pools: Any = assets_and_pools["pools"]

    # pad the allocations
    for contract_addr in pools:
        if contract_addr not in allocs:
            allocs[contract_addr] = 0

    # sort the allocations by contract address
    return {contract_addr: allocs[contract_addr] for contract_addr in sorted(allocs.keys())}


def dynamic_normalize_zscore(rewards: torch.Tensor, z_threshold: float = 1.0, epsilon: float = 1e-8) -> torch.Tensor:
    mean = rewards.mean()
    std_dev = rewards.std()

    # Calculate z-scores
    z_scores = (rewards - mean) / std_dev

    lower_q_range = torch.quantile(rewards, 0.05) - rewards.min()
    rest_range = rewards.max() - torch.quantile(rewards, 0.05)

    # Set a lower bound based on z-score threshold if the lower quartile range is larger than the rest
    lower_bound = rewards[z_scores > -z_threshold].min() if lower_q_range > rest_range else rewards.min()

    # No upper bound, only clip the lower bound
    clipped_data = torch.clip(rewards, lower_bound)

    return (clipped_data - clipped_data.min()) / (clipped_data.max() - clipped_data.min() + epsilon)


def calculate_penalties(
    similarity_matrix: dict[str, dict[str, float]],
    axon_times: dict[str, float],
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> dict[str, int]:
    penalties = {miner: 0 for miner in similarity_matrix}

    for miner_a, similarities in similarity_matrix.items():
        for miner_b, similarity in similarities.items():
            if similarity <= similarity_threshold and axon_times[miner_a] <= axon_times[miner_b]:
                penalties[miner_b] += 1

    return penalties


def calculate_rewards_with_adjusted_penalties(miners, rewards_apy, penalties) -> torch.Tensor:
    rewards = torch.zeros(len(miners))
    max_penalty = max(penalties.values())
    if max_penalty == 0:
        return rewards_apy

    for idx, miner_id in enumerate(miners):
        # Calculate penalty adjustment
        penalty_factor = (max_penalty - penalties[miner_id]) / max_penalty

        # Calculate the final reward
        reward = rewards_apy[idx] * penalty_factor
        rewards[idx] = reward

    return rewards


def get_similarity_matrix(
    apys_and_allocations: dict[str, dict[str, AllocationsDict | int]],
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel | BasePoolModel] | int],
) -> dict[str, dict[str, float]]:
    """
    Calculates the similarity matrix for the allocation strategies of miners using normalized Euclidean distance.

    This function computes a similarity matrix based on the Euclidean distance between the allocation vectors of miners,
    normalized by the maximum possible distance in the given asset space. Each miner's allocation is compared with every
    other miner's allocation, resulting in a matrix where each element (i, j) represents the normalized Euclidean distance
    between the allocations of miner_i and miner_j.

    The similarity metric is scaled between 0 and 1, where 0 indicates identical allocations and 1 indicates the maximum
    possible distance between the allocation 'vectors'.

    Args:
        apys_and_allocations (dict[str, dict[str, Union[AllocationsDict, int]]]):
            A dictionary containing the APY and allocation strategies for each miner. The keys are miner identifiers,
            and the values are dictionaries with their respective allocations and APYs.
        assets_and_pools (dict[str, Union[AllocationsDict, int]]):
            A dictionary representing the assets available to the miner as well as the pools they can allocate to

    Returns:
        dict[str, dict[str, float]]:
            A nested dictionary where each key is a miner identifier, and the value is another dictionary containing the
            normalized Euclidean distances to every other miner. The distances are scaled between 0 and 1.
    """

    similarity_matrix = {}
    total_assets = cast(int, assets_and_pools["total_assets"])
    for miner_a, info_a in apys_and_allocations.items():
        _alloc_a = cast(AllocationsDict, info_a["allocations"])
        alloc_a = np.array(
            list(format_allocations(_alloc_a, assets_and_pools).values()),
            dtype=np.float32,
        )
        similarity_matrix[miner_a] = {}
        for miner_b, info_b in apys_and_allocations.items():
            if miner_a != miner_b:
                _alloc_b = cast(AllocationsDict, info_b["allocations"])
                if _alloc_a is None or _alloc_b is None:
                    similarity_matrix[miner_a][miner_b] = float("inf")
                    continue
                alloc_b = np.array(
                    list(format_allocations(_alloc_b, assets_and_pools).values()),
                    dtype=np.float32,
                )
                similarity_matrix[miner_a][miner_b] = np.linalg.norm(alloc_a - alloc_b) / np.sqrt(float(2 * total_assets**2))

    return similarity_matrix


def adjust_rewards_for_plagiarism(
    rewards_apy: torch.Tensor,
    apys_and_allocations: dict[str, dict[str, AllocationsDict | int]],
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel | BasePoolModel] | int],
    uids: list,
    axon_times: dict[str, float],
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> torch.Tensor:
    """
    Adjusts the annual percentage yield (APY) rewards for miners based on the similarity of their allocations
    to others and their arrival times, penalizing plagiarized or overly similar strategies.

    This function calculates the similarity between each pair of miners' allocation strategies and applies a penalty
    to those whose allocations are too similar to others, considering the order in which they arrived. Miners who
    arrived earlier with unique strategies are given preference, and those with similar strategies arriving later
    are penalized. The final APY rewards are adjusted accordingly.

    Args:
        rewards_apy (torch.Tensor): The initial APY rewards for the miners, before adjustments.
        apys_and_allocations (dict[str, dict[str, Union[AllocationsDict, int]]]):
            A dictionary containing APY values and allocation strategies for each miner. The keys are miner identifiers,
            and the values are dictionaries that include their allocations and APYs.
        assets_and_pools (dict[str, Union[dict[str, int], int]]):
            A dictionary representing the available assets and their corresponding pools.
        uids (List): A list of unique identifiers for the miners.
        axon_times (dict[str, float]): A dictionary that tracks the arrival times of each miner, with the keys being
            miner identifiers and the values being their arrival times. Earlier times are lower values.

    Returns:
        torch.Tensor: The adjusted APY rewards for the miners, accounting for penalties due to similarity with
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
    penalties = calculate_penalties(similarity_matrix, axon_times, similarity_threshold)

    # Step 3: Calculate final rewards with adjusted penalties
    return calculate_rewards_with_adjusted_penalties(uids, rewards_apy, penalties)


def _get_rewards(
    self,
    apys_and_allocations: dict[str, dict[str, AllocationsDict | int]],
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel | BasePoolModel] | int],
    uids: list[str],
    axon_times: dict[str, float],
) -> torch.Tensor:
    """
    Rewards miner responses to request. This method returns a reward
    value for the miner, which is used to update the miner's score.

    Returns:
    - adjusted_rewards: The reward values for the miners.
    """

    raw_apys = torch.Tensor([apys_and_allocations[uid]["apy"] for uid in uids])

    rewards_apy = dynamic_normalize_zscore(raw_apys).to(self.device)

    return adjust_rewards_for_plagiarism(rewards_apy, apys_and_allocations, assets_and_pools, uids, axon_times)


def calculate_apy(
    allocations: AllocationsDict,
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel | BasePoolModel] | int],
) -> int:
    """
    Calculates immediate projected yields given intial assets and pools, pool history, and number of timesteps
    """

    # calculate projected yield
    initial_balance = cast(int, assets_and_pools["total_assets"])
    pools = cast(dict[str, ChainBasedPoolModel], assets_and_pools["pools"])
    pct_yield = 0
    for uid, pool in pools.items():
        allocation = allocations[uid]
        match pool.pool_type:
            case POOL_TYPES.STURDY_SILO:
                pool_yield = wei_mul(allocation, pool.supply_rate(amount=allocation))
            case POOL_TYPES.DAI_SAVINGS:
                pool_yield = wei_mul(allocation, pool.supply_rate())
            case POOL_TYPES.COMPOUND_V3:
                pool_yield = wei_mul(allocation, pool.supply_rate(amount=allocation))
            case _:
                pool_yield = wei_mul(allocation, pool.supply_rate(user_addr=pool.user_address, amount=allocation))
        pct_yield += pool_yield

    return wei_div(pct_yield, initial_balance)


def calculate_aggregate_apy(
    allocations: AllocationsDict,
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel | BasePoolModel] | int],
    timesteps: int,
    pool_history: list[dict[str, Any]],
) -> int:
    """
    Calculates aggregate yields given intial assets and pools, pool history, and number of timesteps
    """

    # calculate aggregate yield
    initial_balance = cast(int, assets_and_pools["total_assets"])
    pct_yield = 0
    for pools in pool_history:
        curr_yield = 0
        for uid, allocs in allocations.items():
            pool_data = pools[uid]
            pool_yield = wei_mul(allocs, pool_data.supply_rate)
            curr_yield += pool_yield
        pct_yield += curr_yield

    pct_yield = wei_div(pct_yield, initial_balance)
    return int(pct_yield // timesteps)  # for simplicity each timestep is a day in the simulator


def get_rewards(
    self,
    query: int,  # noqa: ARG001
    uids: list[str],
    responses: list,
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel | BasePoolModel] | int],
) -> tuple[torch.Tensor, dict[str, AllocInfo]]:
    """
    Returns a tensor of rewards for the given query and responses.

    Args:
    - query (int): The query sent to the miner.
    - responses (list[float]): A list of responses from the miner.

    Returns:
    - torch.Tensor: A tensor of rewards for the given query and responses.
    - allocs: miner allocations along with their respective yields
    """

    # maximum yield to scale all rewards by
    # total apys of allocations per miner
    max_apy = 0
    apys = {}

    init_assets_and_pools = copy.deepcopy(assets_and_pools)

    bt.logging.debug(f"Running simulator for {self.simulator.timesteps} timesteps for each allocation...")

    # TODO: assuming that we are only getting immediate apy for organic chainbasedpool requests
    pools_to_scan = cast(dict, init_assets_and_pools["pools"])
    # update reserves given allocations
    for pool in pools_to_scan.values():
        match pool.pool_type:
            case T if T in (POOL_TYPES.AAVE, POOL_TYPES.DAI_SAVINGS, POOL_TYPES.COMPOUND_V3):
                pool.sync(self.w3)
            case POOL_TYPES.STURDY_SILO:
                pool.sync(pool.user_address, self.w3)
            case _:
                pass

    resulting_apy = 0
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
            bt.logging.error(e)  # type: ignore[]

        # score response very low if miner is cheating somehow or returns allocations with incorrect format
        if cheating:
            miner_uid = uids[response_idx]
            bt.logging.warning(f"CHEATER DETECTED  - MINER WITH UID {miner_uid} - PUNISHING 👊😠")
            apys[miner_uid] = 0
            continue

        try:
            if response.request_type == REQUEST_TYPES.SYNTHETIC:
                # miner does not appear to be cheating - so we init simulator data
                self.simulator.init_data(
                    init_assets_and_pools=copy.deepcopy(init_assets_and_pools),
                    init_allocations=allocations,
                )
                self.simulator.update_reserves_with_allocs()

                self.simulator.run()

                resulting_apy = calculate_aggregate_apy(
                    allocations,
                    init_assets_and_pools,
                    self.simulator.timesteps,
                    self.simulator.pool_history,
                )

            else:
                resulting_apy = calculate_apy(
                    allocations,
                    init_assets_and_pools,
                )
        except Exception as e:
            bt.logging.error(e)  # type: ignore[]
            bt.logging.error("Failed to calculate apy - PENALIZING MINER")
            miner_uid = uids[response_idx]
            apys[miner_uid] = 0
            continue

        if resulting_apy > max_apy:
            max_apy = resulting_apy

        apys[uids[response_idx]] = resulting_apy

    axon_times = get_response_times(uids=uids, responses=responses, timeout=QUERY_TIMEOUT)

    # set apys for miners that took longer than the timeout to minimum
    # TODO: cleaner way to do this?
    for uid in uids:
        if axon_times[uid] >= QUERY_TIMEOUT:
            apys[uid] = 0

    # TODO: should probably move some things around later down the road
    allocs = {}
    filtered_allocs = {}
    for idx in range(len(responses)):
        # TODO: cleaner way to do this?
        if responses[idx].allocations is None or axon_times[uids[idx]] >= QUERY_TIMEOUT:
            allocs[uids[idx]] = {
                "apy": 0,
                "allocations": None,
            }
        else:
            allocs[uids[idx]] = {
                "apy": apys[uids[idx]],
                "allocations": responses[idx].allocations,
            }

            filtered_allocs[uids[idx]] = {
                "apy": apys[uids[idx]],
                "allocations": responses[idx].allocations,
            }

    sorted_filtered_allocs = dict(sorted(filtered_allocs.items(), key=lambda item: item[1]["apy"], reverse=True))

    sorted_apys = dict(sorted(apys.items(), key=lambda item: item[1], reverse=True))

    sorted_axon_times = dict(sorted(axon_times.items(), key=lambda item: item[1]))

    bt.logging.debug(f"sorted apys: {sorted_apys}")
    bt.logging.debug(f"sorted axon times: {sorted_axon_times}")
    bt.logging.debug(f"sorted filtered allocs:\n{sorted_filtered_allocs}")

    # Get all the reward results by iteratively calling your reward() function.
    return (
        _get_rewards(
            self,
            apys_and_allocations=allocs,
            assets_and_pools=init_assets_and_pools,  # type: ignore[]
            uids=uids,
            axon_times=axon_times,
        ),
        sorted_filtered_allocs,
    )
