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

import json
from datetime import datetime
from typing import cast

import bittensor as bt
import numpy.typing as npt
from async_lru import alru_cache
from bittensor import Balance
from eth_account.messages import encode_defunct
from hexbytes import HexBytes
from web3 import EthereumTesterProvider, Web3

from sturdy.constants import QUERY_TIMEOUT
from sturdy.pools import POOL_TYPES, ChainBasedPoolModel, PoolFactory, check_allocations
from sturdy.protocol import AllocationsDict, AllocInfo, UniswapV3PoolLiquidity
from sturdy.utils.bt_alpha import fetch_dynamic_info, get_vali_avg_apy
from sturdy.utils.ethmath import wei_div
from sturdy.utils.misc import get_scoring_period_length
from sturdy.utils.taofi_subgraph import fetch_uniswap_pos_and_swaps
from sturdy.validator.apy_binning import calculate_bin_rewards, create_apy_bins, sort_bins_by_processing_time
from sturdy.validator.sql import get_db_connection, get_miner_responses, get_request_info


@alru_cache(maxsize=512, ttl=60)
async def get_subtensor_block(subtensor: bt.AsyncSubtensor) -> int:
    return await subtensor.block


def get_response_times(uids: list[int], responses, timeout: float) -> dict[str, float]:
    """
    Returns a list of axons based on their response times.

    This function pairs each uid with its corresponding axon's response time.
    Lower response times are considered better.

    Args:
        uids (list[int]): list of unique identifiers for each axon.
        responses (list[Response]): list of Response objects corresponding to each axon.

    Returns:
        dict[str, float]: a dictionary: uid -> process_time

    Example:
        >>> get_response_times(
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


def _get_rewards(
    self,
    apys_and_allocations: dict[str, dict[str, AllocationsDict | int]],
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel] | int],
    uids: list[str],
    axon_times: dict[str, float],
) -> npt.NDArray:
    """
    Rewards miner responses using APY-based binning and within-bin allocation similarity.
    """
    # Extract APY values
    apys = {uid: info["apy"] for uid, info in apys_and_allocations.items()}

    # Create APY-based bins
    apy_bins = create_apy_bins(apys)
    apy_bins = sort_bins_by_processing_time(apy_bins, axon_times)
    bt.logging.debug(f"apy bins: {apy_bins}")

    # Calculate rewards based on bins and allocation similarity
    rewards, penalties = calculate_bin_rewards(apy_bins, apys_and_allocations, assets_and_pools, axon_times)

    # Store penalties for logging/debugging
    # round value to 4 decimal places so that it doesn't flood logs
    self.similarity_penalties = {uid: round(float(penalties[i]), 4) for i, uid in enumerate(uids)}

    return rewards


async def annualized_yield_pct(
    allocations: dict,
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel] | int],
    seconds_passed: int,
    extra_metadata: dict,
    pool_data_provider: bt.AsyncSubtensor | None = None,
) -> int:
    """
    Calculates annualized yields of allocations in pools within scoring period
    """

    if seconds_passed < 1:
        return 0

    # calculate projected yield
    initial_balance = cast(int, assets_and_pools["total_assets"])
    pools = cast(dict[str, ChainBasedPoolModel], assets_and_pools["pools"])
    total_yield = 0

    seconds_per_year = 31536000

    if isinstance(pool_data_provider, bt.AsyncSubtensor):
        current_block = await get_subtensor_block(pool_data_provider)

    # TODO: refactor?
    for key, pool in pools.items():
        # assume there is no allocation to that pool if not found
        try:
            allocation = allocations[key]
        except Exception:
            bt.logging.trace(f"could not find allocation to {key}, assuming it is 0...")
            allocation = 0
            continue
        match pool.pool_type:
            case T if T in (
                POOL_TYPES.STURDY_SILO,
                POOL_TYPES.MORPHO,
                POOL_TYPES.YEARN_V3,
                POOL_TYPES.AAVE_DEFAULT,
                POOL_TYPES.AAVE_TARGET,
            ):
                # TODO: temp fix
                if allocation > 0:
                    last_share_price = extra_metadata[key]
                    curr_share_price = pool._yield_index
                    pct_delta = float(curr_share_price - last_share_price) / float(last_share_price)
                    deposit_delta = allocation - pool._user_deposits
                    try:
                        adjusted_pct_delta = (
                            (pool._total_supplied_assets) / (pool._total_supplied_assets + deposit_delta + 1) * pct_delta
                        )
                        annualized_pct_yield = adjusted_pct_delta * (seconds_per_year / seconds_passed)
                        total_yield += int(allocation * annualized_pct_yield)
                    except Exception as e:
                        bt.logging.error("Error calculating annualized pct yield, skipping:")
                        bt.logging.exception(e)
            case POOL_TYPES.BT_ALPHA:
                try:
                    initial_alloc = allocation["amount"]
                    vali_hotkey = allocation["delegate_ss58"]
                    if initial_alloc > 0:
                        metadata = extra_metadata[key]

                        last_block = metadata["block"]
                        last_price = metadata["price_rao"]

                        dynamic_info: bt.DynamicInfo = await fetch_dynamic_info(
                            sub=pool_data_provider, block=last_block, netuid=pool.netuid
                        )
                        delta = initial_alloc - pool.current_amount

                        # alpha delta (in tao)
                        alpha_delta_tao = delta / (last_price + 1)

                        # consider slippage
                        alpha_lost = 0
                        if delta > 0:
                            _, alpha_lost_bal = dynamic_info.tao_to_alpha_with_slippage(Balance.from_rao(delta))
                            alpha_lost = alpha_lost_bal.rao
                        elif delta < 0:
                            alpha_num = int(abs(delta) / dynamic_info.price)
                            _, tao_lost_bal = dynamic_info.alpha_to_tao_with_slippage(
                                Balance.from_rao(alpha_num, netuid=pool.netuid)
                            )
                            alpha_lost = int(tao_lost_bal.rao / (last_price / 1e9))

                        curr_price = pool._price_rao
                        annualized_alpha_apy = await get_vali_avg_apy(
                            subtensor=pool_data_provider,
                            netuid=pool.netuid,
                            hotkey=vali_hotkey,
                            block=last_block,
                            end_block=current_block,
                            delta_alpha_tao=alpha_delta_tao,
                        )

                        initial_amount_raw = int(initial_alloc / (last_price / 1e9) - alpha_lost)
                        if initial_amount_raw >= 0:
                            initial_amount = initial_amount_raw
                            alpha_amount = int((initial_amount) * (1 + annualized_alpha_apy))
                            tao_pct_return = ((alpha_amount * (curr_price / 1e9)) - (initial_alloc)) / (initial_alloc)
                            total_yield += int(tao_pct_return * initial_alloc)
                        else:
                            initial_amount = 0  # if initial_amount raw is less than zero than there is no initial amount
                            alpha_amount = 0  # same can be said for the alpha amount
                            tao_lost_slippage = alpha_lost * (
                                last_price / 1e9
                            )  # but we still want to consider the % loss from slippage - which is done here.
                            # tao_pct_return is simply not a number in this case
                            tao_pct_return = float("nan")
                            total_yield -= tao_lost_slippage

                        ## log the info above
                        bt.logging.trace(
                            f"initial amount: {initial_amount}, alpha amount: {alpha_amount}, \
                            alpha_delta_tao: {alpha_delta_tao}, annualized alpha apy: {annualized_alpha_apy}, \
                            tao_pct_return: {tao_pct_return}, initial_alloc: {initial_alloc}, \
                            current_amount: {pool.current_amount}, delta: {delta}, \
                            alpha_lost: {alpha_lost}, last_price: {last_price}, \
                            current_price: {curr_price} \
                            last_block: {last_block}, current_block: {current_block}"
                        )
                except Exception as e:
                    bt.logging.error("Error calculating annualized pct yield, skipping:")
                    bt.logging.exception(e)
            case _:
                total_yield += 0

    return wei_div(total_yield, initial_balance)


def filter_allocations(
    self,
    query: int,  # noqa: ARG001
    uids: list[str],
    responses: list,
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel] | int],
    query_timeout: int = QUERY_TIMEOUT,
) -> tuple[dict[str, float], dict[str, AllocInfo], list[str]]:
    """
    Returns filtered allocations based on the query and responses from the miner.

    Args:
    - query (int): The query sent to the miner.
    - responses (list[float]): A list of responses from the miner.

    Returns:
    - dict[str, float]: A dictionary containing the axon times for each uid.
    - dict[str, AllocInfo]: A dictionary containing the filtered allocations.
    - list[str]: A list of UIDs of miners that were filtered out.
    """

    filtered_allocs = {}
    axon_times = get_response_times(uids=uids, responses=responses, timeout=query_timeout)
    filtered_out_uids = []

    cheaters = []
    for response_idx, response in enumerate(responses):
        allocations = response.allocations
        miner_uid = uids[response_idx]

        # is the miner cheating w.r.t allocations?
        cheating = True
        try:
            cheating = not check_allocations(assets_and_pools, allocations)
        except Exception as e:
            bt.logging.error(e)  # type: ignore[]

        # score response very low if miner is cheating somehow or returns allocations with incorrect format
        if cheating:
            cheaters.append(miner_uid)
            filtered_out_uids.append(miner_uid)
            continue

        # used to filter out miners who timed out
        # TODO: should probably move some things around later down the road
        # TODO: cleaner way to do this?
        if response.allocations is not None and axon_times[str(miner_uid)] < query_timeout:
            filtered_allocs[str(miner_uid)] = {
                "allocations": response.allocations,
            }
        else:
            filtered_out_uids.append(miner_uid)

    bt.logging.warning(f"CHEATERS DETECTED: {cheaters}")

    curr_filtered_allocs = dict(sorted(filtered_allocs.items(), key=lambda item: int(item[0])))

    # round to 4 decimal places for nicer looking logs
    sorted_axon_times = {uid: round(t, 4) for (uid, t) in sorted(axon_times.items(), key=lambda item: item[1])}

    bt.logging.debug(f"sorted axon times:\n{sorted_axon_times}")

    self.sorted_axon_times = sorted_axon_times

    # Get all the reward results by iteratively calling your reward() function.
    return axon_times, curr_filtered_allocs, filtered_out_uids


# TODO: we shouldn't need chain_data provider here, use self.pool_data_providers instead
async def get_rewards_allocs(
    self, active_allocation, chain_data_provider: Web3 | bt.AsyncSubtensor
) -> tuple[list, list, bool]:
    # a dictionary, miner uids -> apy and allocations
    apys_and_allocations = {}
    miner_uids = []
    axon_times = {}

    # TODO: rename this here and in the database schema?
    request_uid = active_allocation["request_uid"]
    scoring_period_length = get_scoring_period_length(active_allocation)

    request_info = {}
    assets_and_pools = None
    miners = None

    with get_db_connection(self.config.db_dir) as conn:
        # get assets and pools that are used to benchmark miner
        # we get the first row entry - we assume that it is the only response from the database
        try:
            request_info = get_request_info(conn, request_uid=request_uid)[0]
            assets_and_pools = json.loads(request_info["assets_and_pools"])
        except Exception:
            return ([], {}, False)

        # obtain the miner responses for each request
        miners = get_miner_responses(conn, request_uid=request_uid)
        bt.logging.debug(f"filtered allocations: {miners}")

    # TODO: see if we can factor this into its own subroutine
    # if so, do the same with the same one in validator.py

    pools = assets_and_pools["pools"]
    new_pools = {}
    for uid, pool in pools.items():
        if pool["pool_type"] == POOL_TYPES.BT_ALPHA:
            new_pool = PoolFactory.create_pool(
                pool_type=pool["pool_type"],
                netuid=int(pool["netuid"]),
                current_amount=int(pool["current_amount"]),
                pool_data_provider_type=pool["pool_data_provider_type"],
            )
        else:
            new_pool = PoolFactory.create_pool(
                pool_type=pool["pool_type"],
                web3_provider=self.pool_data_providers[pool["pool_data_provider_type"]],  # type: ignore[]
                user_address=(pool["user_address"]),  # TODO: is there a cleaner way to do this?
                contract_address=pool["contract_address"],
            )

        # sync pool
        await new_pool.sync(chain_data_provider)
        new_pools[uid] = new_pool

    assets_and_pools["pools"] = new_pools

    try:
        miners_to_score = json.loads(active_allocation["miners"])
    except Exception as _:
        bt.logging.error("Failed to load miners to score - scoring all by default")
        miners_to_score = None

    # calculate the yield the pools accrued during the scoring period
    for miner in miners:
        allocations = json.loads(miner["allocation"])["allocations"]
        extra_metadata = json.loads(request_info["metadata"])
        miner_uid = miner["miner_uid"]
        if miners_to_score:
            try:
                prev_hotkey = miners_to_score[int(miner_uid)]
                new_hotkey = self.metagraph.hotkeys[int(miner_uid)]
                if new_hotkey != prev_hotkey:
                    bt.logging.info(
                        f"Miner with uid {miner_uid} and hotkey {new_hotkey} recently replaced {prev_hotkey}. \
                        It will not be scored"
                    )
                    continue
            except Exception as e:
                bt.logging.error(e)
                bt.logging.error("Failed miner hotkey check, continuing loop...")
                continue
        miner_apy = await annualized_yield_pct(
            allocations, assets_and_pools, scoring_period_length, extra_metadata, chain_data_provider
        )
        miner_axon_time = miner["axon_time"]

        miner_uids.append(miner_uid)
        axon_times[miner_uid] = miner_axon_time
        apys_and_allocations[miner_uid] = {"apy": miner_apy, "allocations": allocations}

    bt.logging.debug(f"yields and allocs: {apys_and_allocations}")
    # log miner uids -> apys
    apys = {uid: value["apy"] for uid, value in apys_and_allocations.items()}
    bt.logging.debug(f"apys: {apys}")

    # TODO: there may be a better way to go about this
    if len(miner_uids) < 1:
        return ([], {}, False)

    # if apys_and_allocations empty or apys are all zero, return miner uids, _get_rewards, and False
    if not apys_and_allocations or all(value["apy"] == 0 for value in apys_and_allocations.values()):
        bt.logging.warning("APYs are all zero or no APYs found, not updating miner scores")
        return (miner_uids, _get_rewards(self, apys_and_allocations, assets_and_pools, miner_uids, axon_times), False)
    # get rewards given the apys and allocations(s) with _get_rewards (???)
    return (miner_uids, _get_rewards(self, apys_and_allocations, assets_and_pools, miner_uids, axon_times), True)


async def get_rewards_uniswap_v3_lp(
    request: UniswapV3PoolLiquidity, responses: list[UniswapV3PoolLiquidity], uids: list[int]
) -> tuple[list, dict]:
    """
    Returns rewards for Uniswap V3 LP miners based on their responses.

    Args:
        responses (list): List of miner responses.

    Returns:
        tuple: A tuple containing a list of miner UIDs and a dictionary mappping uids to rewards.
    """

    miner_uids = []
    rewards = {}
    total_lp_scores = 0
    w3 = Web3(EthereumTesterProvider())
    bt.logging.debug(f"UIDS: {uids}")

    # track highest miner lp_score
    highest_miner_lp_score = 0

    try:
        # signature is valid, get swaps since the last 24 hours - timestamp is in utc
        # Get swaps from the last 24 hours
        one_day_ago = int(datetime.now().timestamp() - 24 * 60 * 60)
        positions, swaps, current_tick = await fetch_uniswap_pos_and_swaps(
            since=one_day_ago, pool_address=request.pool_address
        )
        bt.logging.debug(f"Current tick for pool {request.pool_address}: {current_tick}")
    except Exception as e:
        bt.logging.error(f"Error fetching information from Taofi subgraph: {e}")

    # set to keep track of token ids from miners
    claimed_token_ids = set()

    for idx, response in enumerate(responses):
        miner_uid = uids[idx]
        rewards[miner_uid] = 0  # initialize rewards for each miner
        miner_uids.append(miner_uid)

        if not isinstance(response, UniswapV3PoolLiquidity):
            raise TypeError(f"Expected UniswapV3PoolLiquidity, got {type(response)}")
        # check if token_id is not None
        if response.token_ids is None:
            bt.logging.warning(f"Miner {miner_uid} has no token_ids, skipping...")
            continue

        miner_uids.append(miner_uid)

        # track the lp score for the miner
        miner_lp_score = 0

        # inspect each position specified by the token_ids in the response
        for token_id in response.token_ids:
            # if token id is already claimed, skip it
            if token_id in claimed_token_ids:
                bt.logging.debug(f"Miner {miner_uid} has already claimed token_id {token_id}, skipping...")
                continue

            # get the position info from the contract
            try:
                position_info = positions[int(token_id)]
                bt.logging.debug(f"Position info for token_id {token_id}: {position_info}")
                pos_liquidity = int(position_info["liquidity"])
                upper_tick = int(position_info["tickUpper"]["tickIdx"])
                lower_tick = int(position_info["tickLower"]["tickIdx"])
                # TODO(uniswap_v3_lp): why is this in all caps, not a valid checksum by default?
                owner = Web3.to_checksum_address(position_info["owner"])
            except Exception as e:
                bt.logging.warning(f"Failed to get position info for token_id {token_id}: {e}")
                continue

            # verify that the signature is valid with web3
            sig = HexBytes(response.signature)
            msg = encode_defunct(text=request.message)
            sig_addr = w3.eth.account.recover_message(signable_message=msg, signature=sig)
            if sig_addr != owner:
                bt.logging.warning(
                    f"Miner {miner_uid} has invalid signature for token_id {token_id}, expected owner {owner}, got {sig_addr}"
                )
                continue

            bt.logging.debug(f"Miner {miner_uid} has position with token_id {token_id} owned by {owner}")
            claimed_token_ids.add(token_id)

            # check that the position is in range and has liquidity
            if pos_liquidity < 0 or not (lower_tick <= current_tick < upper_tick):
                bt.logging.warning(
                    f"Miner {miner_uid} has position with token_id {token_id} that is out of range or has no liquidity"
                )
                continue

            # calculate the lp score for the miner for each swap
            for swap in swaps:
                # check if the swap's tick is within the position's tick range
                if lower_tick <= int(swap["tick"]) <= upper_tick:
                    amount_usd = float(swap["amountUSD"])
                    miner_lp_score += amount_usd * pos_liquidity / 1e18

            bt.logging.debug(f"Miner {miner_uid} has LP score of {miner_lp_score} for token_id {token_id}")

        # store the miner's scores in the rewards dictionary
        rewards[miner_uid] = miner_lp_score
        highest_miner_fee = max(highest_miner_lp_score, miner_lp_score)
        total_lp_scores += miner_lp_score

    bt.logging.debug(f"Sum of all miner LP scores: {total_lp_scores}")
    # normalize the rewards
    if total_lp_scores > 0:
        for uid, reward in rewards.items():
            rewards[uid] = reward / highest_miner_fee
    else:
        bt.logging.warning("Total fees earned by all miners is zero, not normalizing rewards")
        for uid in rewards:
            rewards[uid] = 0
    bt.logging.debug(f"Miner rewards: {rewards}")

    return (miner_uids, rewards)
