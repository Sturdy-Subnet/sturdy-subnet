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
from typing import List, Dict, Tuple, TypedDict
from decimal import Decimal

from sturdy.constants import QUERY_TIMEOUT, STEEPNESS, DIV_FACTOR, NUM_POOLS
from sturdy.utils.misc import calculate_apy
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


def get_rewards(
    self,
    query: int,
    uids: List,
    assets_and_pools: Dict[int, Dict],
    responses: List,
) -> Tuple[torch.FloatTensor, Dict[int, AllocInfo]]:
    """
    Returns a tensor of rewards for the given query and responses.

    Args:
    - query (int): The query sent to the miner.
    - responses (List[float]): A list of responses from the miner.

    Returns:
    - torch.FloatTensor: A tensor of rewards for the given query and responses.
    """

    # maximum yield to scale all rewards by
    # TODO: what to set smallest yield value to?
    # total apys of allocations per miner
    max_apy = sys.float_info.min
    apys = {}

    for response_idx, response in enumerate(responses):
        alloc_yield = 0
        allocations = response.allocations

        if allocations == None:
            apys[uids[response_idx]] = sys.float_info.min
            continue

        initial_balance = assets_and_pools["total_assets"]
        total_allocated = Decimal(0)
        cheating = False

        for pool_id, allocation in allocations.items():
            pool = assets_and_pools["pools"][pool_id]
            total_allocated += Decimal(
                str(allocation)
            )  # This should fix precision issues with python floats

            # score response very low if miner is cheating somehow
            if total_allocated > initial_balance or allocation < pool["borrow_amount"]:
                cheating = True
                break

            # calculate yield for given pool allocation
            util_rate = pool["borrow_amount"] / allocation
            interest_rate = calculate_apy(util_rate, pool)
            alloc_yield += allocation * interest_rate

        # punish if miner they're cheating
        # TODO: create a more forgiving penalty system?
        if cheating:
            miner_uid = uids[response_idx]
            bt.logging.warning(
                f"CHEATER DETECTED  - MINER WITH UID {miner_uid} - PUNISHING 👊😠"
            )
            apys[miner_uid] = sys.float_info.min
            continue

        # append total apy of miner to yields
        apy = float(alloc_yield / initial_balance)

        if apy > max_apy:
            max_apy = apy

        apys[uids[response_idx]] = apy

    # TODO: should probably move some things around later down the road
    allocs = {}
    for idx in range(len(responses)):
        if responses[idx].allocations is None:
            continue
        if len(responses[idx].allocations) == len(assets_and_pools["pools"]):
            allocs[uids[idx]] = {
                "apy": apys[uids[idx]],
                "allocations": responses[idx].allocations,
            }

    sorted_apys = {
        k: v for k, v in sorted(apys.items(), key=lambda item: item[1], reverse=True)
    }

    axon_times = get_response_times(
        uids=uids, responses=responses, timeout=QUERY_TIMEOUT
    )
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
