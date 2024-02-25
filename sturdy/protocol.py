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

import typing
import bittensor as bt

# TODO(developer): Rewrite with your protocol definition.

# This is the protocol for the dummy miner and validator.
# It is a simple request-response protocol where the validator sends a request
# to the miner, and the miner responds with a dummy response.

# ---- miner ----
# Example usage:
#   def dummy( synapse: Dummy ) -> Dummy:
#       synapse.dummy_output = synapse.dummy_input + 1
#       return synapse
#   axon = bt.axon().attach( dummy ).serve(netuid=...).start()

# ---- validator ---
# Example usage:
#   dendrite = bt.dendrite()
#   dummy_output = dendrite.query( Dummy( dummy_input = 1 ) )
#   assert dummy_output == 2

#  1. AllocateAssets
#  2. AllocateAssetsUser  - TODO: is this really needed?
#  3. SubmitAllocations


class AllocateAssets(bt.Synapse):
    """
    This protocol helps in handling the distribution of validator-generated pools from
    the validator to miners, and then gathering miner-generated allocations afterwards.

    Attributes:
    - pools: A list of pools sent by the validator.
    - allocations: A list of pools and their respective allocations, when filled, represents the response from the miner.
    """

    # Required request input, filled by sending dendrite caller.
    # todo: what type should this be?
    assets_and_pools: typing.Dict[
        int | str, typing.Dict | float
    ]  # pools for miners to produce allocation amounts for - uid -> pool_info

    # Optional request output, filled by recieving axon.
    allocations: typing.Optional[typing.Dict[int, float]] = None

    # Saw this in https://github.com/ifrit98/storage-subnet/blob/HEAD/storage/protocol.py
    # TODO: can this just be removed lol? - (Probably)
    # required_request_fields = typing.List[str] = pydantic.Field(
    #     [
    #         "pools"
    #     ]
    #     ...
    # )

    def __str__(self):
        # TODO: figure out hwo to only show certain keys from pools and/or allocations
        return f"AllocateAssets(assets_and_pools={self.assets_and_pools})" f"allocations={self.allocations}"