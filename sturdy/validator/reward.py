# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# TODO(developer): Set your name
# Copyright © 2023 <your name>

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
import torch
from typing import List, Dict


def reward(query: int, max_apy: float, miner_apy: float) -> float:
    """
    Reward the miner response to the dummy request. This method returns a reward
    value for the miner, which is used to update the miner's score.

    Returns:
    - float: The reward value for the miner.
    """

    return miner_apy / max_apy


def get_rewards(
    self,
    query: int,
    assets_and_pools: Dict[int, Dict],
    responses: List,
) -> torch.FloatTensor:
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
    max_apy = sys.float_info.min
    # total apys of allocations per miner
    apys = []

    for response in responses:
        alloc_yield = 0
        allocations = response.allocations

        if allocations == None:
            apys.append(sys.float_info.min)
            continue

        initial_balance = assets_and_pools["total_assets"]
        total_allocated = 0
        cheating = False

        for pool_id, allocation in allocations.items():
            pool = assets_and_pools["pools"][pool_id]
            total_allocated += allocation

            # reject allocations if miner is cheating somehow
            if total_allocated > initial_balance or allocation < pool["borrow_amount"]:
                cheating = True
                break

            # calculate yield for given pool allocation

            util_rate = pool["borrow_amount"] / allocation
            interest_rate = (
                pool["base_rate"]
                + (util_rate / pool["optimal_util_rate"]) * pool["base_slope"]
                if util_rate < pool["optimal_util_rate"]
                else pool["base_rate"]
                + pool["base_slope"]
                + (
                    (util_rate - pool["optimal_util_rate"])
                    / (1 - pool["optimal_util_rate"])
                )
                * pool["kink_slope"]
            )

            alloc_yield += allocation * interest_rate

        # punish if miner they're cheating
        # TODO: create a more forgiving penalty system?
        if cheating:
            apys.append(sys.float_info.min)
            continue

        # append total apy of miner to yields
        apy = alloc_yield / initial_balance

        if apy > max_apy:
            max_apy = apy

        apys.append(apy)

    apys_dict = {x: apys[x] for x in range(len(apys))}
    sorted_apys = {
        k: v
        for k, v in sorted(apys_dict.items(), key=lambda item: item[1], reverse=True)
    }
    bt.logging.debug(f"sorted apys: {sorted_apys}")

    # Get all the reward results by iteratively calling your reward() function.
    return torch.FloatTensor(
        [reward(query, max_apy=max_apy, miner_apy=miner_apy) for miner_apy in apys]
    ).to(self.device)
