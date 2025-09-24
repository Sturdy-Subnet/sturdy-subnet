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
from web3 import AsyncWeb3, EthereumTesterProvider, Web3

from swap.constants import WHITELISTED_LP_MINER
from swap.utils.taofi_subgraph import PositionFeesInfo, get_fees_in_range

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
    web3_provider: AsyncWeb3,
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
        one_day_ago = max(1, current_block - BLOCK_ONE_DAY_AGO)
        one_day_block_timestamp = int((await subtensor.get_timestamp(block=one_day_ago)).timestamp())
        fees_in_range_ret: tuple[dict[int, PositionFeesInfo], dict[int, bool]] = await get_fees_in_range(
            block_start=one_day_ago,
            block_end=current_block,
            web3_provider=web3_provider,
            subtract_burns_from_timestamp=one_day_block_timestamp,
        )
        in_range_fee_growth, in_range_mapping = fees_in_range_ret
    except Exception as e:
        bt.logging.error(f"Error fetching information from Taofi subgraph: {e}")
        return (miner_uids, rewards)

    # Generate mapping from owners to token ids
    owners_to_token_ids = {}
    for token_id, position_info in in_range_fee_growth.items():
        owner = w3.to_checksum_address(position_info.owner)
        owners_to_token_ids.setdefault(owner, []).append(token_id)

    bt.logging.debug(f"Owners to token ids mapping: {owners_to_token_ids}")

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

        miner_fees = calculate_miner_fees(
            miner_uid,
            evm_address,
            owners_to_token_ids,
            in_range_fee_growth,
            in_range_mapping,
            claimed_token_ids,
            claimed_owner_addresses,
        )
        rewards[miner_uid] = miner_fees

    if whitelisted_uid is not None:
        unclaimed_token_ids = set(in_range_fee_growth.keys()) - claimed_token_ids
        whitelisted_fees = calculate_whitelisted_fees(
            whitelisted_uid, unclaimed_token_ids, in_range_fee_growth, in_range_mapping
        )
        rewards[whitelisted_uid] = whitelisted_fees

    # Log total fees earned by all miners
    total_fees = sum(rewards.values())
    bt.logging.info(f"Total fees earned by all miners: {total_fees}")

    # Normalize rewards
    max_fees = max(rewards.values()) if rewards.values() else 0
    if max_fees > 0:
        rewards = {uid: fees / max_fees for uid, fees in rewards.items()}
    else:
        bt.logging.warning("Total fees earned by all miners is zero, not normalizing rewards")

    return (miner_uids, rewards)


def calculate_miner_fees(
    miner_uid: int,
    evm_address: str,
    owners_to_token_ids: dict,
    in_range_fee_growth: dict,
    in_range_mapping: dict,
    claimed_token_ids: set,
    claimed_owner_addresses: set,
) -> float:
    """Calculate fees for a regular (non-whitelisted) miner."""
    miner_fees = 0.0
    owner_token_ids = owners_to_token_ids.get(evm_address, [])

    # Check if this owner address has already been claimed by another miner
    if evm_address in claimed_owner_addresses:
        bt.logging.debug(f"Owner address {evm_address} already claimed by another miner, skipping...")
        return 0.0

    # Mark this owner address as claimed
    claimed_owner_addresses.add(evm_address)

    for token_id in owner_token_ids:
        if token_id in claimed_token_ids:
            bt.logging.debug(f"Token ID {token_id} already claimed, skipping...")
            continue
        try:
            position_info = in_range_fee_growth[token_id]
        except KeyError:
            bt.logging.error(f"Token ID {token_id} not found in in_range_fee_growth")
            continue

        try:
            fees_pos = position_info.total_fees_token1_equivalent
            miner_fees += fees_pos
            claimed_token_ids.add(token_id)
            bt.logging.debug(
                f"Miner {miner_uid}: token_id {token_id} earned {fees_pos} fees | "
                f"In range: {'✅' if in_range_mapping[token_id] else '❌'}"
            )
        except Exception as e:
            bt.logging.error(f"Error fetching position info for token_id {token_id}: {e}")

    return miner_fees


def calculate_whitelisted_fees(
    miner_uid: int, unclaimed_token_ids: set, in_range_fee_growth: dict, in_range_mapping: dict
) -> float:
    """Calculate fees for the whitelisted miner from unclaimed positions."""
    bt.logging.debug(f"Miner {miner_uid} is whitelisted, claiming {len(unclaimed_token_ids)} unclaimed positions")

    whitelisted_fees = 0.0
    for token_id in unclaimed_token_ids:
        try:
            position_info = in_range_fee_growth[token_id]
            fees_pos = position_info.total_fees_token1_equivalent
            whitelisted_fees += fees_pos

            if fees_pos > 0:
                bt.logging.debug(
                    f"Miner {miner_uid}: token_id {token_id} earned {fees_pos} fees | "
                    f"In range: {'✅' if in_range_mapping[token_id] else '❌'}"
                )
        except Exception as e:
            bt.logging.error(f"Error fetching position info for token_id {token_id}: {e}")

    return whitelisted_fees
