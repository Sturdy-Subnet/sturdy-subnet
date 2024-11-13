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

from sturdy.constants import MAX_SCORING_PERIOD, MIN_SCORING_PERIOD, QUERY_TIMEOUT, SCORING_PERIOD_STEP
from sturdy.pools import POOL_TYPES, ChainBasedPoolModel, generate_challenge_data
from sturdy.protocol import REQUEST_TYPES, AllocateAssets, AllocInfo
from sturdy.validator.reward import filter_allocations, get_rewards
from sturdy.validator.sql import get_active_allocs, get_db_connection, log_allocations


async def forward(self) -> Any:
    """
    The forward function is called by the validator every time step.

    It is responsible for querying the network with synthetic requests and scoring the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    """
    # initialize pools and assets
    # TODO: only sturdy silos and morpho vaults for now
    challenge_data = generate_challenge_data(self.w3)
    request_uuid = str(uuid.uuid4()).replace("-", "")
    user_address = challenge_data.get("user_address", None)

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
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.MORPHO):
                metadata[contract_addr] = pool._share_price
            case T if T in (POOL_TYPES.AAVE_DEFAULT, POOL_TYPES.AAVE_TARGET):
                metadata[contract_addr] = pool._normalized_income
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

async def query_miner(
    self,
    synapse: bt.Synapse,
    uid: str,
    deserialize: bool = False,
) -> bt.Synapse:
    return await self.dendrite.forward(
        axons=self.metagraph.axons[int(uid)],
        synapse=synapse,
        timeout=QUERY_TIMEOUT,
        deserialize=deserialize,
        streaming=False,
    )


async def query_multiple_miners(
    self,
    synapse: bt.Synapse,
    uids: list[str],
    deserialize: bool = False,
) -> list[bt.Synapse]:
    uid_to_query_task = {uid: asyncio.create_task(query_miner(self, synapse, uid, deserialize)) for uid in uids}
    return await asyncio.gather(*uid_to_query_task.values())


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

    for active_alloc in active_alloc_rows:
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

    # before logging latest allocations
    # filter them
    axon_times, filtered_allocs = filter_allocations(
        self,
        query=self.step,
        uids=active_uids,
        responses=responses,
        assets_and_pools=assets_and_pools,
    )

    # TODO: sort the miners' by their current scores and return their respective allocations
    sorted_indices = [idx for idx, val in sorted(enumerate(self.scores), key=lambda k: k[1], reverse=True)]

    sorted_allocs = {}
    for idx in sorted_indices:
        alloc = filtered_allocs.get(str(idx), None)
        if alloc is None:
            continue

        sorted_allocs[str(idx)] = alloc

    bt.logging.debug(f"sorted allocations: {sorted_allocs}")

    return axon_times, sorted_allocs
