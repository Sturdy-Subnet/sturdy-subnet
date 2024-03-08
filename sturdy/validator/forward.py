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

from sturdy.protocol import AllocateAssets
from sturdy.validator.reward import get_rewards
from sturdy.utils.uids import get_random_uids
from sturdy.pools import generate_assets_and_pools
from sturdy.constants import QUERY_TIMEOUT

bt.metagraph


async def forward(self):
    """
    The forward function is called by the validator every time step.

    It is responsible for querying the network and scoring the responses.

    Args:
        self (:obj:`bittensor.neuron.Neuron`): The neuron object which contains all the necessary state for the validator.

    """
    # generate pools
    assets_and_pools = generate_assets_and_pools()

    # The dendrite client queries the network.
    # TODO: write custom availability function later down the road
    active_uids = [
        uid
        for uid in range(self.metagraph.n.item())
        if self.metagraph.axons[uid].is_serving
    ]
    active_axons = [self.metagraph.axons[uid] for uid in active_uids]

    responses = await self.dendrite(
        # Send the query to selected miner axons in the network.
        axons=active_axons,
        # Construct a dummy query. This simply contains a single integer.
        synapse=AllocateAssets(assets_and_pools=assets_and_pools),
        deserialize=False,
        timeout=QUERY_TIMEOUT,
    )
    allocations = {uid: responses[idx].allocations for idx, uid in enumerate(active_uids)}

    # Log the results for monitoring purposes.
    bt.logging.debug(f"Pools: {assets_and_pools['pools']}")
    bt.logging.debug(f"Received allocations (uid -> allocations): {allocations}")

    # TODO(developer): Define how the validator scores responses.
    # Adjust the scores based on responses from miners.
    rewards = get_rewards(
        self,
        query=self.step,
        uids=active_uids,
        assets_and_pools=assets_and_pools,
        responses=responses,
    )

    bt.logging.info(f"Scored responses: {rewards}")
    bt.logging.debug(f"active axons: {active_axons}")
    # Update the scores based on the rewards. You may want to define your own update_scores function for custom behavior.
    self.update_scores(rewards, active_uids)
