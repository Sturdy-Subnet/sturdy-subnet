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

import asyncio
import json
import uuid
from typing import Any

import bittensor as bt
import numpy as np
from web3 import AsyncWeb3, Web3
from web3.constants import ADDRESS_ZERO

from sturdy.constants import (
    LP_QUERY_TIMEOUT,
    MAX_SCORING_PERIOD,
    MIN_SCORING_PERIOD,
    MIN_TOTAL_ASSETS_AMOUNT,
    MINER_GROUP_EMISSIONS,
    MINER_GROUP_THRESHOLDS,
    SCORING_PERIOD_STEP,
)
from sturdy.pools import POOL_TYPES, BittensorAlphaTokenPool, ChainBasedPoolModel, generate_challenge_data
from sturdy.protocol import MINER_TYPE, REQUEST_TYPES, AllocateAssets, AllocInfo, UniswapV3PoolLiquidity
from sturdy.providers import POOL_DATA_PROVIDER_TYPE
from sturdy.validator.request import Request
from sturdy.validator.reward import filter_allocations, get_rewards_allocs, get_rewards_uniswap_v3_lp
from sturdy.validator.sql import (
    delete_active_allocs,
    garbage_collect_db,
    get_active_allocs,
    get_db_connection,
    get_request_info,
    log_allocations,
)
from sturdy.validator.utils.axon import query_single_axon


async def uniswap_v3_lp_forward(self) -> Any:
    """This is periodically called to query miners for their LP positions into TaoFi's Uniswap V3 pool."""
    bt.logging.info("Running Uniswap V3 LP forward function...")
    await query_and_score_miners_uniswap_v3_lp(self)


async def forward(self) -> Any:
    """
    The forward function is called by the validator every time step.

    It is responsible for querying the network with synthetic requests and scoring the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    """

    while True:
        # delete stale active allocations and requests
        bt.logging.debug("Purging stale rows from the database...")
        with get_db_connection(self.config.db_dir) as conn:
            # TODO: consider just using a cascade delete for the allocation requests?
            # NOTE: cascades likely won't work if we decide to implement db syncing with cr-sqlite
            garbage_collect_db(conn)

        chain_data_provider = np.random.choice(list(self.pool_data_providers.values()))
        try:
            challenge_data = await generate_challenge_data(chain_data_provider)
        except Exception as e:
            bt.logging.exception(f"Failed to generate challenge data: {e}")
            continue

        request_uuid = str(uuid.uuid4()).replace("-", "")
        user_address = challenge_data.get("user_address", None)

        # check if there are enough assets to move around
        total_assets = challenge_data["assets_and_pools"]["total_assets"]
        if isinstance(chain_data_provider, ChainBasedPoolModel):
            bt.logging.debug("Checking total assets amount of generated challenge...")
            if total_assets < MIN_TOTAL_ASSETS_AMOUNT:
                bt.logging.error(f"Total assets are too low: {total_assets}, retrying...")
                continue
            bt.logging.debug("Check passed")

        break

    bt.logging.info("Querying miners...")
    axon_times, allocations = await query_and_score_miners_allocs(
        self,
        assets_and_pools=challenge_data["assets_and_pools"],
        chain_data_provider=chain_data_provider,
        request_type=REQUEST_TYPES.SYNTHETIC,
        user_address=user_address if user_address is not None else ADDRESS_ZERO,
    )

    if not allocations:
        bt.logging.warning("No allocations received from miners, skipping forward step.")
        return

    assets_and_pools = challenge_data["assets_and_pools"]
    pools = assets_and_pools["pools"]
    metadata = await get_metadata(pools, chain_data_provider)

    scoring_period = get_scoring_period()

    with get_db_connection(self.config.db_dir) as conn:
        log_allocations(
            conn,
            request_uuid,
            self.metagraph.hotkeys,
            assets_and_pools,
            metadata,
            allocations,
            axon_times,
            REQUEST_TYPES.SYNTHETIC,
            scoring_period,
        )


# TODO: have a better way to determine how to obtain metadata from the inputted pools
# for more info see TODO(provider)
async def get_metadata(
    pools: dict[str, ChainBasedPoolModel | BittensorAlphaTokenPool], chain_data_provider: AsyncWeb3 | bt.AsyncSubtensor
) -> dict:
    metadata = {}
    for pool_key, pool in pools.items():
        await pool.sync(chain_data_provider)
        if isinstance(chain_data_provider, AsyncWeb3):
            match pool.pool_type:
                case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.MORPHO, POOL_TYPES.YEARN_V3):
                    metadata[pool_key] = pool._yield_index
                case T if T in (POOL_TYPES.AAVE_DEFAULT, POOL_TYPES.AAVE_TARGET):
                    metadata[pool_key] = pool._yield_index
                case _:
                    pass
        else:
            # get current bittensor block
            block = await chain_data_provider.block
            price_rao = pool._price_rao
            meta = {"block": block, "price_rao": price_rao}
            metadata[pool_key] = meta

    return metadata


def get_scoring_period(rng_gen: np.random.RandomState = None) -> int:
    if rng_gen is None:
        rng_gen = np.random.RandomState()

    return rng_gen.choice(
        np.arange(
            MIN_SCORING_PERIOD,
            MAX_SCORING_PERIOD + SCORING_PERIOD_STEP,
            SCORING_PERIOD_STEP,
        ),
    )


async def query_multiple_miners(
    self,
    synapse: bt.Synapse,
    uids: list[str],
) -> list[bt.Synapse]:
    responses = []
    for uid in uids:
        request = prepare_single_request(self, int(uid), synapse.model_copy())
        if request:
            try:
                task = asyncio.create_task(process_single_request(self, request))
                await task
                request.synapse.dendrite.process_time = request.response_time
                responses.append(request.synapse)
            except Exception as e:
                bt.logging.error(f"query_multiple_miners::Error in task for UID {uid}: {e}")
                responses.append(None)
        else:
            bt.logging.error(f"query_multiple_miners::Error preparing request for UID {uid}")
            responses.append(None)
    return responses


async def process_single_request(self, request: Request) -> Request:
    """
    Process a single request and return the response.
    """
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            self.thread_pool,
            lambda: query_single_axon(self.dendrite, request, query_timeout=self.config.neuron.timeout),
        )
        response = await response
    except Exception as e:
        bt.logging.error(f"Error processing request for UID {request.uid}: {e}")
    return request


def prepare_single_request(self, uid: int, synapse: bt.Synapse) -> Request | None:
    """
    Prepare a single request to be sent to the miner.
    """
    try:
        return Request(
            uid=uid,
            axon=self.metagraph.axons[uid],
            synapse=synapse,
        )
    except Exception as e:
        bt.logging.error(f"prepare_single_request::Error preparing request for UID {uid}: {e}")
        return None


def sort_allocation_by_score(allocations: dict[str, AllocInfo], scores: list) -> dict[str, AllocInfo]:
    """
    Sort the allocations by score in descending order.
    """
    sorted_indices = [idx for idx, val in sorted(enumerate(scores), key=lambda k: k[1], reverse=True)]
    sorted_allocs = {}
    rank = 1
    for idx in sorted_indices:
        alloc = allocations.get(str(idx), None)
        if alloc is None:
            continue

        alloc["rank"] = rank
        sorted_allocs[str(idx)] = alloc
        rank += 1
    return sorted_allocs


# TODO(provider): Don't rely on chain provider parameter
# we should be depedendant on the information directly from each pool model vs. having
# to rely on a chain_data_provider input parameter - which is actually very limiting -
# particularly in a situation where you want to handle pools from multiple chains at once for
# i.e. cross chain asset allocation optimisation!
async def query_and_score_miners_allocs(
    self,
    assets_and_pools: Any,
    chain_data_provider: Web3 | bt.AsyncSubtensor,  # TODO: we shouldn't need this here - use self.pool_data_providers
    request_type: REQUEST_TYPES = REQUEST_TYPES.SYNTHETIC,
    user_address: str = ADDRESS_ZERO,
) -> tuple[list, dict[str, AllocInfo]]:
    # The dendrite client queries the network.
    # TODO: write custom availability function later down the road
    uids_to_query = [uid for uid, t in self.miner_types.items() if t == MINER_TYPE.ALLOC]

    if uids_to_query is None or len(uids_to_query) < 1:
        bt.logging.error("No miners available to query for allocations.")
        return [], {}

    np.random.shuffle(uids_to_query)

    bt.logging.debug(f"active_uids: {uids_to_query}")

    # TODO: see TODO(provider)
    pools = assets_and_pools["pools"]
    first_pool = next(iter(pools.values()))
    pool_data_provider_type = first_pool.pool_data_provider_type

    synapse = AllocateAssets(
        request_type=request_type,
        assets_and_pools=assets_and_pools,
        user_address=user_address,
        pool_data_provider=pool_data_provider_type,
    )

    # query all miners
    responses = await query_multiple_miners(
        self,
        synapse,
        uids_to_query,
    )

    bt.logging.trace(f"Received responses: {responses}")

    allocations = {uid: responses[idx].allocations for idx, uid in enumerate(uids_to_query)}  # type: ignore[]

    # Log the results for monitoring purposes.
    bt.logging.info(f"Assets and pools: {synapse.assets_and_pools}")
    bt.logging.info(f"Received allocations (uid -> allocations): {allocations}")

    curr_pools = assets_and_pools["pools"]
    for pool in curr_pools.values():
        await pool.sync(chain_data_provider)

    # score previously suggested miner allocations based on how well they are performing now

    # get all the request ids for the pools we should be scoring from the db
    active_alloc_rows = []
    with get_db_connection(self.config.db_dir) as conn:
        active_alloc_rows = get_active_allocs(conn)

    bt.logging.debug(f"Active allocs: {active_alloc_rows}")

    uids_to_delete = []
    for active_alloc in active_alloc_rows:
        request_uid = active_alloc["request_uid"]
        with get_db_connection(self.config.db_dir) as conn:
            # NOTE: see TODO(provider)
            request_info = get_request_info(conn, request_uid=request_uid)
            data_pools = json.loads(request_info[0]["assets_and_pools"])["pools"]
            first_entry = next(iter(data_pools.values()))
            data_provider = self.pool_data_providers[first_entry["pool_data_provider_type"]]
            bt.logging.debug(f"Pool data provider to use for scoring this pool: {data_provider}")

        uids_to_delete.append(request_uid)
        # calculate rewards for previous active allocations
        miner_uids, rewards, should_update_scores = await get_rewards_allocs(self, active_alloc, data_provider)
        bt.logging.debug(f"sim penalities: {self.similarity_penalties}")

        # TODO: there may be a better way to go about this
        if len(miner_uids) < 1:
            break

        # update the moving average scores of the miners
        int_miner_uids = [int(uid) for uid in miner_uids]
        if should_update_scores:
            # Apply penalties to the lowest performing miners
            # note that "rewards" is a numpy array of floats
            sorted_rewards = sorted(zip(int_miner_uids, rewards, strict=False), key=lambda x: x[1], reverse=True)
            if len(sorted_rewards) > MINER_GROUP_THRESHOLDS["ALLOC"]:
                for uid, _ in sorted_rewards[MINER_GROUP_THRESHOLDS["ALLOC"] :]:
                    rewards[int_miner_uids.index(uid)] = 0.0
            # scale emissions by the miner group emissions
            rewards *= MINER_GROUP_EMISSIONS["ALLOC"]
            bt.logging.debug(f"miner rewards: {rewards}")
            self.update_scores(rewards, int_miner_uids, self.config.neuron.alloc_moving_average_alpha)

    # wipe these allocations from the db after scoring them
    if len(uids_to_delete) > 0:
        with get_db_connection(self.config.db_dir) as conn:
            rows_affected = delete_active_allocs(conn, uids_to_delete)
            bt.logging.debug(f"Scored and removed {rows_affected} active allocation requests")

    # before logging latest allocations
    # filter them
    axon_times, filtered_allocs, filtered_out_uids = filter_allocations(
        self,
        query=self.step,
        uids=uids_to_query,
        responses=responses,
        assets_and_pools=assets_and_pools,
        query_timeout=self.config.neuron.timeout,
    )

    # array of zeros the length of the filtered out uids
    bt.logging.warning("Scoring filtered out miners with zero scores.")
    bt.logging.warning(f"Filtered out uids: {filtered_out_uids}")
    unresponsive_miner_scores = np.zeros(len(filtered_out_uids), dtype=np.float64)
    # update the scores of the filtered out uids
    self.update_scores(unresponsive_miner_scores, filtered_out_uids, self.config.neuron.alloc_moving_average_alpha)

    sorted_allocs = sort_allocation_by_score(filtered_allocs, self.scores)

    bt.logging.debug(f"sorted allocations: {sorted_allocs}")

    return axon_times, sorted_allocs


async def query_and_score_miners_uniswap_v3_lp(self) -> tuple[list, dict[int, float]]:
    """
    Query the network for Uniswap V3 LP positions and score the responses.
    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.
    Returns:
        tuple: A tuple containing the axon times and the amount of fees they have earned in the past scoring period.
    """
    bt.logging.info("Querying miners for Uniswap V3 LP positions...")

    # filter out uids to query
    uids_to_query = [uid for uid, t in self.miner_types.items() if t == MINER_TYPE.UNISWAP_V3_LP]
    np.random.shuffle(uids_to_query)
    bt.logging.debug(f"Miners to query for Uniswap V3 LP positions: {uids_to_query}")

    if uids_to_query is None or len(uids_to_query) < 1:
        bt.logging.error("No miners available to query for allocations.")
        return [], {}

    # query all miners
    synapses = [
        # TODO(uniswap_v3_lp): Move these constants to a config file or constants module
        # much like the pool registry for evm-based pools
        UniswapV3PoolLiquidity(
            pool_address="0x6647dcbeb030dc8E227D8B1A2Cb6A49F3C887E3c",
            token_0="0x9Dc08C6e2BF0F1eeD1E00670f80Df39145529F81",
            token_1="0xB833E8137FEDf80de7E908dc6fea43a029142F20",
            signature=None,
            message=f"{self.wallet.hotkey.ss58_address}-{self.metagraph.hotkeys[uid]}-{str(uuid.uuid4()).replace('-', '')}",
        )
        for uid in uids_to_query
    ]

    query_tasks = []
    for idx, uid in enumerate(uids_to_query):
        axon = self.metagraph.axons[uid]
        query_task = self.dendrite.call(
            target_axon=axon,
            synapse=synapses[idx].model_copy(),
            timeout=LP_QUERY_TIMEOUT,
            deserialize=False,
        )
        query_tasks.append(query_task)

    responses = await asyncio.gather(*query_tasks)
    uids_to_queries = {str(uid): synapse for uid, synapse in zip(uids_to_query, synapses, strict=False)}
    uids_to_responses = {str(uid): response for uid, response in zip(uids_to_query, responses, strict=False)}

    bt.logging.debug(f"Sent requests: {uids_to_queries}")
    bt.logging.debug(f"Received responses: {uids_to_responses}")

    # score the responses
    # get the bittensor mainnet provider
    bt_mainnet_provider = self.pool_data_providers[POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET]
    bt_web3_provider = self.pool_data_providers[POOL_DATA_PROVIDER_TYPE.BITTENSOR_WEB3]
    miner_uids, rewards_dict = await get_rewards_uniswap_v3_lp(
        self,
        requests=synapses,
        responses=responses,
        lp_miner_uids=uids_to_query,
        subtensor=bt_mainnet_provider,
        web3_provider=bt_web3_provider,
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


async def query_top_n_miners(
    self,
    n: int,
    assets_and_pools: Any,
    request_type: REQUEST_TYPES = REQUEST_TYPES.SYNTHETIC,
    user_address: str = ADDRESS_ZERO,
) -> tuple[list, dict[str, AllocInfo]]:
    """
    Query the top n miners by their scores and return their allocations.
    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.
        n (int): The number of top miners to query.
        assets_and_pools (dict): The assets and pools to be allocated.
        request_type (REQUEST_TYPES): The type of request to be sent to the miners.
        user_address (str): The address of the user making the request.
    Returns:
        tuple: A tuple containing the axon times and the allocations of the top n miners.
    """

    # get the top n miners by their scores (self.scores). the index of each score is the uid of the miner
    # make sure that the miner type is the correct one (they must be MINER_TYPE.ALLOC)
    alloc_uids = [uid for uid in range(len(self.scores)) if self.miner_types[uid] == MINER_TYPE.ALLOC]
    top_n_uids = [str(uid) for uid in np.argsort([self.scores[uid] for uid in alloc_uids])[-n:]]
    bt.logging.debug(f"Top {n} allocation miners to query: {top_n_uids}")

    # TODO: see TODO(provider)
    pools = assets_and_pools["pools"]
    first_pool = next(iter(pools.values()))
    pool_data_provider_type = first_pool.pool_data_provider_type

    # query the top n miners
    synapse = AllocateAssets(
        request_type=request_type,
        assets_and_pools=assets_and_pools,
        user_address=user_address,
        pool_data_provider=pool_data_provider_type,
    )

    responses = await query_multiple_miners(
        self,
        synapse,
        top_n_uids,
    )

    bt.logging.debug(f"Received responses: {responses}")
    allocations = {uid: responses[idx].allocations for idx, uid in enumerate(top_n_uids)}  # type: ignore[]
    bt.logging.debug(f"Received allocations: {allocations}")
    # Log the results for monitoring purposes.
    bt.logging.info(f"Assets and pools: {synapse.assets_and_pools}")
    bt.logging.info(f"Received allocations (uid -> allocations): {allocations}")

    chain_data_provider = self.pool_data_providers[first_pool.pool_data_provider_type]
    curr_pools = assets_and_pools["pools"]
    for pool in curr_pools.values():
        await pool.sync(chain_data_provider)

    # filter the allocations
    axon_times, filtered_allocs, _ = filter_allocations(
        self,
        query=self.step,
        uids=top_n_uids,
        responses=responses,
        assets_and_pools=assets_and_pools,
        query_timeout=self.config.neuron.timeout,
    )
    bt.logging.debug(f"Filtered allocations: {filtered_allocs}")
    # sort the allocations by score
    sorted_allocs = sort_allocation_by_score(filtered_allocs, self.scores)
    bt.logging.debug(f"Sorted allocations: {sorted_allocs}")

    return axon_times, sorted_allocs
