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

import bittensor as bt
import typing
import asyncio

from sturdy.protocol import AllocateAssets
from sturdy.validator.reward import get_rewards
from sturdy.utils.uids import get_random_uids
from sturdy.pools import generate_assets_and_pools
from sturdy.protocol import AllocInfo
from sturdy.constants import QUERY_TIMEOUT

bt.metagraph


async def forward(self):
    """
    The forward function is called by the validator every time step.

    It is responsible for querying the network with synthetic requests and scoring the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    """
    # generates synthetic pools
    assets_and_pools = generate_assets_and_pools()
    await query_and_score_miners(self, assets_and_pools)


async def query_miner(
    self,
    synapse: bt.Synapse,
    uid: typing.List[int],
    deserialize: bool = False,
):
    response = await self.dendrite.forward(
        axons=self.metagraph.axons[uid],
        synapse=synapse,
        timeout=QUERY_TIMEOUT,
        deserialize=deserialize,
        streaming=False,
    )

    return response


async def query_multiple_miners(
    self,
    synapse: bt.Synapse,
    uids: typing.List[int],
    deserialize: bool = False,
):

    uid_to_query_task = {
        uid: asyncio.create_task(query_miner(self, synapse, uid, deserialize))
        for uid in uids
    }
    responses = await asyncio.gather(*uid_to_query_task.values())
    return responses


async def query_and_score_miners(
    self, assets_and_pools: typing.Dict
) -> typing.Dict[int, AllocInfo]:
    # The dendrite client queries the network.
    # TODO: write custom availability function later down the road
    active_uids = [
        uid
        for uid in range(self.metagraph.n.item())
        if self.metagraph.axons[uid].is_serving
    ]

    bt.logging.debug(f"active_uids: {active_uids}")

    responses = await query_multiple_miners(self, AllocateAssets(assets_and_pools=assets_and_pools), active_uids)
    allocations = {
        uid: responses[idx].allocations for idx, uid in enumerate(active_uids)
    }

    # Log the results for monitoring purposes.
    bt.logging.debug(f"Pools: {assets_and_pools['pools']}")
    bt.logging.debug(f"Received allocations (uid -> allocations): {allocations}")

    # Adjust the scores based on responses from miners.
    rewards, allocs = get_rewards(
        self,
        query=self.step,
        uids=active_uids,
        assets_and_pools=assets_and_pools,
        responses=responses,
    )

    bt.logging.info(f"Scored responses: {rewards}")

    self.update_scores(rewards, active_uids)
    bt.logging.debug(f"allocs:\n{allocs}")
    return allocs
