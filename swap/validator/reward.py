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
import bittensor as bt
from async_lru import alru_cache
from web3 import EthereumTesterProvider, Web3

from swap.constants import WHITELISTED_LP_MINER
from swap.utils.taofi_subgraph import PositionInfo, get_positions_with_scores

# a day in blocktime
BLOCK_ONE_DAY_AGO = 7200  # 2 hours in blocks, assuming 1 block per second
# we use this as a buffer in case the subgraph is not updated in time
BLOCK_BUFFER = 10  # 10 block (2 minutes) buffer


@alru_cache(maxsize=512, ttl=60)
async def get_subtensor_block(subtensor: bt.AsyncSubtensor) -> int:
    return await subtensor.block


async def get_rewards_uniswap_v3_lp(
    self,
    taofi_lp_evm_addresses: dict[int, str],
    subtensor: bt.AsyncSubtensor,
) -> tuple[list, dict]:
    """
    Returns rewards for Uniswap V3 LP miners based on their responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.
        taofi_lp_evm_addresses (dict[int, str]): A dictionary mapping miner UIDs to their associated EVM addresses.
        subtensor (:obj:`bittensor.AsyncSubtensor`): The Bittensor async subtensor instance.
        web3_provider (:obj:`web3.AsyncWeb3`): The web3 provider to interact with the Ethereum blockchain.

    Returns:
        tuple: A tuple containing a list of miner UIDs, a dictionary mapping uids to rewards,
               and claimed token ids by non-whitelisted miners.
    """

    miner_uids = list(taofi_lp_evm_addresses.keys())
    rewards = dict.fromkeys(miner_uids, 0)
    w3 = Web3(EthereumTesterProvider())

    try:
        current_block = await subtensor.get_current_block() - BLOCK_BUFFER
        # Get positions with concentration scores at current block
        positions_with_scores: dict[int, PositionInfo] = await get_positions_with_scores(block_number=current_block)
    except Exception as e:
        bt.logging.error(f"Error fetching information from Taofi subgraph: {e}")
        return (miner_uids, rewards)

    # Generate mapping from owners to token ids and their scores
    owners_to_positions = {}
    for token_id, position_info in positions_with_scores.items():
        owner = w3.to_checksum_address(position_info.owner)
        if owner not in owners_to_positions:
            owners_to_positions[owner] = []
        owners_to_positions[owner].append((token_id, position_info.reward_score))

    bt.logging.debug(f"Owners to positions mapping: {owners_to_positions}")

    # Track claimed token ids to identify unclaimed ones
    claimed_token_ids = set()
    # Track claimed owner addresses to avoid double counting
    claimed_owner_addresses = set()

    whitelisted_uid = None
    # Process regular miners first
    for miner_uid, evm_address in taofi_lp_evm_addresses.items():
        miner_hotkey = self.metagraph.hotkeys[miner_uid]
        if miner_hotkey == WHITELISTED_LP_MINER:
            whitelisted_uid = miner_uid
            continue  # Skip whitelisted miner for nowCurrent block: {current_block}")

        if evm_address is None:
            bt.logging.warning(f"Miner {miner_uid} has no associated EVM address, skipping...")
            continue

        miner_score = calculate_miner_score(
            miner_uid,
            evm_address,
            owners_to_positions,
            positions_with_scores,
            claimed_token_ids,
            claimed_owner_addresses,
        )
        rewards[miner_uid] = miner_score

    if whitelisted_uid is not None:
        unclaimed_token_ids = set(positions_with_scores.keys()) - claimed_token_ids
        whitelisted_score = calculate_whitelisted_score(whitelisted_uid, unclaimed_token_ids, positions_with_scores)
        rewards[whitelisted_uid] = whitelisted_score

    # Log total scores earned by all miners
    total_scores = sum(rewards.values())
    bt.logging.info(f"Total concentration scores for all miners: {total_scores}")

    # Normalize rewards
    max_score = max(rewards.values()) if rewards.values() else 0
    if max_score > 0:
        rewards = {uid: score / max_score for uid, score in rewards.items()}
    else:
        bt.logging.warning("Total fees earned by all miners is zero, not normalizing rewards")

    return (miner_uids, rewards)


def calculate_miner_score(
    miner_uid: int,
    evm_address: str,
    owners_to_positions: dict,
    positions_with_scores: dict,
    claimed_token_ids: set,
    claimed_owner_addresses: set,
) -> float:
    """Calculate concentration score for a regular (non-whitelisted) miner."""
    miner_score = 0.0
    owner_positions = owners_to_positions.get(evm_address, [])

    # Check if this owner address has already been claimed by another miner
    if evm_address in claimed_owner_addresses:
        bt.logging.debug(f"Owner address {evm_address} already claimed by another miner, skipping...")
        return 0.0

    # Mark this owner address as claimed
    claimed_owner_addresses.add(evm_address)

    for token_id, score in owner_positions:
        if token_id in claimed_token_ids:
            bt.logging.debug(f"Token ID {token_id} already claimed, skipping...")
            continue

        miner_score += score
        claimed_token_ids.add(token_id)

        if score > 0:
            position_info = positions_with_scores[token_id]
            bt.logging.debug(
                f"Miner {miner_uid}: token_id {token_id} score {score:.6f} | "
                f"Liquidity: {position_info.liquidity} | "
                f"Range: [{position_info.tick_lower}, {position_info.tick_upper}]"
            )

    return miner_score


def calculate_whitelisted_score(miner_uid: int, unclaimed_token_ids: set, positions_with_scores: dict) -> float:
    """Calculate concentration score for the whitelisted miner from unclaimed positions."""
    bt.logging.debug(f"Miner {miner_uid} is whitelisted, claiming {len(unclaimed_token_ids)} unclaimed positions")

    whitelisted_score = 0.0
    for token_id in unclaimed_token_ids:
        try:
            position_info = positions_with_scores[token_id]
            score = position_info.reward_score
            whitelisted_score += score

            if score > 0:
                bt.logging.debug(
                    f"Miner {miner_uid}: token_id {token_id} score {score:.6f} | "
                    f"Liquidity: {position_info.liquidity} | "
                    f"Range: [{position_info.tick_lower}, {position_info.tick_upper}]"
                )
        except Exception as e:
            bt.logging.error(f"Error fetching position info for token_id {token_id}: {e}")

    return whitelisted_score
