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
import uuid
from typing import Any

import bittensor as bt
import numpy as np
from web3 import Web3
from web3.constants import ADDRESS_ZERO

from sturdy.constants import (
    MAX_SCORING_PERIOD,
    MIN_SCORING_PERIOD,
    MIN_TOTAL_ASSETS_AMOUNT,
    QUERY_TIMEOUT,
    SCORING_PERIOD_STEP,
)
from sturdy.pools import POOL_TYPES, ChainBasedPoolModel, generate_challenge_data
from sturdy.protocol import REQUEST_TYPES, AllocateAssets, AllocInfo
from sturdy.validator.reward import filter_allocations, get_rewards
from sturdy.validator.sql import (
    delete_active_allocs,
    delete_stale_active_allocs,
    get_active_allocs,
    get_db_connection,
    log_allocations,
)
from sturdy.validator.utils.axon import query_single_axon
from sturdy.validator.request import Request


async def forward(self) -> Any:
    """
    The forward function is called by the validator every time step.

    It is responsible for querying the network with synthetic requests and scoring the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    """

    while True:
        # delete stale active allocations after expiry time
        bt.logging.debug("Purging stale active allocation requests")
        with get_db_connection(self.config.db_dir) as conn:
            rows_affected = delete_stale_active_allocs(conn)
        bt.logging.debug(f"Purged {rows_affected} stale active allocation requests")

        # initialize pools and assets
        challenge_data = generate_challenge_data(self.w3)
        request_uuid = str(uuid.uuid4()).replace("-", "")
        user_address = challenge_data.get("user_address", None)

        # check if there are enough assets to move around
        total_assets = challenge_data["assets_and_pools"]["total_assets"]

        if total_assets < MIN_TOTAL_ASSETS_AMOUNT:
            bt.logging.error(f"Total assets are too low: {total_assets}, retrying...")
            continue
        break

    bt.logging.info("Querying miners...")
    axon_times, allocations = await query_and_score_miners(
        self,
        assets_and_pools=challenge_data["assets_and_pools"],
        request_type=REQUEST_TYPES.SYNTHETIC,
        user_address=user_address if user_address is not None else ADDRESS_ZERO,
    )

    assets_and_pools = challenge_data["assets_and_pools"]
    pools = assets_and_pools["pools"]
    metadata = get_metadata(pools, self.w3)

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


def get_metadata(pools: dict[str, ChainBasedPoolModel], w3: Web3) -> dict:
    metadata = {}
    for contract_addr, pool in pools.items():
        pool.sync(w3)
        match pool.pool_type:
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.MORPHO, POOL_TYPES.YEARN_V3):
                metadata[contract_addr] = pool._yield_index
            case T if T in (POOL_TYPES.AAVE_DEFAULT, POOL_TYPES.AAVE_TARGET):
                metadata[contract_addr] = pool._yield_index
            case _:
                pass

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
    deserialize: bool = False,
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
            lambda: query_single_axon(self.dendrite, request),
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
        request = Request(
            uid=uid,
            axon=self.metagraph.axons[uid],
            synapse=synapse,
        )
        return request
    except Exception as e:
        bt.logging.error(f"prepare_single_request::Error preparing request for UID {uid}: {e}")
        return None


async def query_and_score_miners(
    self,
    assets_and_pools: Any,
    request_type: REQUEST_TYPES = REQUEST_TYPES.SYNTHETIC,
    user_address: str = ADDRESS_ZERO,
) -> tuple[list, dict[str, AllocInfo]]:
    # The dendrite client queries the network.
    # TODO: write custom availability function later down the road
    active_uids = [str(uid) for uid in range(self.metagraph.n.item()) if self.metagraph.axons[uid].is_serving]

    np.random.shuffle(active_uids)

    bt.logging.debug(f"active_uids: {active_uids}")

    synapse = AllocateAssets(
        request_type=request_type,
        assets_and_pools=assets_and_pools,
        user_address=user_address,
    )

    # query all miners
    responses = await query_multiple_miners(
        self,
        synapse,
        active_uids,
    )

    allocations = {uid: responses[idx].allocations for idx, uid in enumerate(active_uids)}  # type: ignore[]

    # Log the results for monitoring purposes.
    bt.logging.debug(f"Assets and pools: {synapse.assets_and_pools}")
    bt.logging.debug(f"Received allocations (uid -> allocations): {allocations}")

    curr_pools = assets_and_pools["pools"]
    for pool in curr_pools.values():
        pool.sync(self.w3)

    # score previously suggested miner allocations based on how well they are performing now

    # get all the request ids for the pools we should be scoring from the db
    active_alloc_rows = []
    with get_db_connection(self.config.db_dir) as conn:
        active_alloc_rows = get_active_allocs(conn)

    bt.logging.debug(f"Active allocs: {active_alloc_rows}")

    uids_to_delete = []
    for active_alloc in active_alloc_rows:
        request_uid = active_alloc["request_uid"]
        uids_to_delete.append(request_uid)
        # calculate rewards for previous active allocations
        miner_uids, rewards = get_rewards(self, active_alloc)
        bt.logging.debug(f"miner rewards: {rewards}")
        bt.logging.debug(f"sim penalities: {self.similarity_penalties}")

        # TODO: there may be a better way to go about this
        if len(miner_uids) < 1:
            break

        # update the moving average scores of the miners
        int_miner_uids = [int(uid) for uid in miner_uids]
        self.update_scores(rewards, int_miner_uids)

    # wipe these allocations from the db after scoring them
    if len(uids_to_delete) > 0:
        with get_db_connection(self.config.db_dir) as conn:
            rows_affected = delete_active_allocs(conn, uids_to_delete)
            bt.logging.debug(f"Scored and removed {rows_affected} active allocation requests")

    # before logging latest allocations
    # filter them
    axon_times, filtered_allocs = filter_allocations(
        self,
        query=self.step,
        uids=active_uids,
        responses=responses,
        assets_and_pools=assets_and_pools,
    )

    sorted_indices = [idx for idx, val in sorted(enumerate(self.scores), key=lambda k: k[1], reverse=True)]

    sorted_allocs = {}
    rank = 1
    for idx in sorted_indices:
        alloc = filtered_allocs.get(str(idx), None)
        if alloc is None:
            continue

        alloc["rank"] = rank
        sorted_allocs[str(idx)] = alloc
        rank += 1

    bt.logging.debug(f"sorted allocations: {sorted_allocs}")

    return axon_times, sorted_allocs
