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
from web3.constants import ADDRESS_ZERO

from sturdy.constants import QUERY_TIMEOUT, SCORING_PERIOD
from sturdy.pools import generate_challenge_data
from sturdy.protocol import REQUEST_TYPES, AllocateAssets, AllocInfo
from sturdy.validator.reward import filter_allocations
from sturdy.validator.sql import get_active_allocs, get_db_connection, log_allocations


async def forward(self) -> Any:
    """
    The forward function is called by the validator every time step.

    It is responsible for querying the network with synthetic requests and scoring the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    """
    # initialize pools and assets

    challenge_data = generate_challenge_data(web3_provider=self.w3)
    request_uuid = str(uuid.uuid4()).replace("-", "")

    axon_times, allocations = await query_and_score_miners(
        self,
        assets_and_pools=challenge_data["assets_and_pools"],
        request_type=REQUEST_TYPES.SYNTHETIC,
        user_address=challenge_data["user_address"],
    )

    with get_db_connection() as conn:
        log_allocations(
            conn,
            request_uuid,
            challenge_data["assets_and_pools"],
            allocations,
            axon_times,
            REQUEST_TYPES.SYNTHETIC,
            SCORING_PERIOD
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
    assets_and_pools: Any = None,
    request_type: REQUEST_TYPES = REQUEST_TYPES.SYNTHETIC,
    user_address: str = ADDRESS_ZERO,
) -> tuple[list, dict[str, AllocInfo]]:
    # The dendrite client queries the network.
    # TODO: write custom availability function later down the road
    active_uids = [str(uid) for uid in range(self.metagraph.n.item()) if self.metagraph.axons[uid].is_serving]

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

    # score previously suggested miner allocations based on how well they are performing now

    # get all the request ids for the pools we should be scoring from the db
    active_allocs = []
    with get_db_connection() as conn:
        active_allocs = get_active_allocs(conn)

    bt.logging.debug(f"Active allocs: {active_allocs}")

    # before logging latest allocations
    # filter them
    axon_times, filtered_allocs = filter_allocations(
        self,
        query=self.step,
        uids=active_uids,
        active_allocations=active_allocs,
        responses=responses,
        assets_and_pools=assets_and_pools,
    )

    # calculate rewards for previous active allocations

    # update the moving average scores of the miners
    # int_active_uids = [int(uid) for uid in active_uids]
    # self.update_scores(rewards, int_active_uids)

    # TODO: sort the miners' by their current scores and return their respective allocations

    return axon_times, filtered_allocs
