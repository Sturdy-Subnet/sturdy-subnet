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

from typing import Any

import bittensor as bt
import numpy as np

from swap.constants import (
    MINER_GROUP_EMISSIONS,
    MINER_GROUP_THRESHOLDS,
)
from swap.protocol import MINER_TYPE
from swap.providers import POOL_DATA_PROVIDER_TYPE
from swap.validator.reward import (
    get_rewards_uniswap_v3_lp,
)


async def uniswap_v3_lp_forward(self) -> Any:
    """This is periodically called to query miners for their LP positions into TaoFi's Uniswap V3 pool."""
    bt.logging.info("Running Uniswap V3 LP forward function...")
    await query_and_score_miners_uniswap_v3_lp(self)


async def query_and_score_miners_uniswap_v3_lp(self) -> tuple[list, dict[int, float]]:
    """
    Query the chain for Uniswap V3 LP positions and score the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    Returns:
        tuple: A tuple containing the rewards and a dictionary of miner UIDs to their rewards.
    """

    bt.logging.info("Querying chain for miners with Uniswap V3 LP positions...")

    # filter out uids to query
    uids_to_query = [uid for uid, t in self.miner_types.items() if t == MINER_TYPE.UNISWAP_V3_LP]
    bt.logging.debug(f"Miners who claim to have Uniswap V3 LP positions: {uids_to_query}")

    if uids_to_query is None or len(uids_to_query) < 1:
        bt.logging.error("No LP miners registered")
        return [], {}

    bt_mainnet_provider = self.pool_data_providers[POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET]

    # filter out the associated evm addresses that are not in the uids to query
    taofi_lp_evm_addresses = {uid: evm for uid, evm in self.associated_evm_addresses.items() if uid in uids_to_query}

    # score lp miners
    miner_uids, rewards_dict = await get_rewards_uniswap_v3_lp(
        self,
        taofi_lp_evm_addresses=taofi_lp_evm_addresses,
        subtensor=bt_mainnet_provider,
    )

    # Sort rewards dict by value in descending order
    sorted_rewards = sorted(rewards_dict.items(), key=lambda x: x[1], reverse=True)
    if len(rewards_dict) > MINER_GROUP_THRESHOLDS["UNISWAP_V3_LP"]:
        # Apply penalties to the lowest performing miners
        for uid, _ in sorted_rewards[MINER_GROUP_THRESHOLDS["UNISWAP_V3_LP"] :]:
            rewards_dict[uid] = 0

    # Create rewards array for update_scores, and scale it by the miner group emissions
    rewards = MINER_GROUP_EMISSIONS["UNISWAP_V3_LP"] * np.array([rewards_dict[uid] for uid in miner_uids], dtype=np.float64)

    bt.logging.debug(f"miner rewards: {rewards_dict}")

    self.update_scores(rewards, miner_uids, self.config.neuron.lp_moving_average_alpha)

    return rewards, rewards_dict
