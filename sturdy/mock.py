# type: ignore[]
import asyncio
import random
import time

import bittensor as bt
import numpy as np

from sturdy.constants import QUERY_TIMEOUT


def generate_array_with_sum(rng_gen: np.random.RandomState, length: int, total_sum: int) -> list:
    # Generate an array of random numbers
    random_numbers = rng_gen.rand(length)

    # Scale the numbers so that they add up to the desired sum
    total_random_sum = sum(random_numbers)
    scaled_numbers = [int((num / total_random_sum) * total_sum) for num in random_numbers]

    # Adjust the last element to ensure the sum is exactly total_sum
    difference = total_sum - sum(scaled_numbers)
    scaled_numbers[-1] += difference

    return scaled_numbers


class MockSubtensor(bt.MockSubtensor):
    def __init__(self, netuid, n=16, wallet=None, network="mock") -> None:
        super().__init__(network=network)

        if not self.subnet_exists(netuid):
            self.create_subnet(netuid)

        # Register ourself (the validator) as a neuron at uid=0
        if wallet is not None:
            self.force_register_neuron(
                netuid=netuid,
                hotkey=wallet.hotkey.ss58_address,
                coldkey=wallet.coldkey.ss58_address,
                balance=100000,
                stake=100000,
            )

        # Register n mock neurons who will be miners
        for i in range(1, n + 1):
            self.force_register_neuron(
                netuid=netuid,
                hotkey=f"miner-hotkey-{i}",
                coldkey="mock-coldkey",
                balance=100000,
                stake=100000,
            )


class MockMetagraph(bt.metagraph):
    def __init__(self, netuid=1, network="mock", subtensor=None) -> None:
        super().__init__(netuid=netuid, network=network, sync=False)

        if subtensor is not None:
            self.subtensor = subtensor
        self.sync(subtensor=subtensor)

        for axon in self.axons:
            axon.ip = "127.0.0.0"
            axon.port = 8091

        bt.logging.info(f"Metagraph: {self}")
        bt.logging.info(f"Axons: {self.axons}")


class MockDendrite(bt.dendrite):
    """
    Replaces a real bittensor network request with a mock request that just returns some static response for all axons that
    are passed and adds some random delay.
    """

    def __init__(self, wallet, custom_allocs=False) -> None:
        super().__init__(wallet)
        self.custom_allocs = custom_allocs

    async def forward(
        self,
        axons: list[bt.axon],
        synapse: bt.Synapse = bt.Synapse(),  # noqa: B008
        timeout: float = QUERY_TIMEOUT,  # noqa: ASYNC109
        deserialize: bool = True,
        run_async: bool = True,  # noqa: ARG002
        streaming: bool = False,
    ) -> bt.Synapse:
        if streaming:
            raise NotImplementedError("Streaming not implemented yet.")

        async def query_all_axons(streaming: bool):  # noqa: ANN202, ARG001
            """Queries all axons for responses."""

            async def single_axon_response(i, axon):  # noqa: ANN202, ARG001
                """Queries a single axon for a response."""

                start_time = time.time()
                s = synapse.copy()
                s = self.preprocess_synapse_for_request(axon, s, timeout)
                # We just want to mock the response, so we'll just fill in some data
                process_time = random.random()  # noqa: S311
                if process_time < timeout:
                    s.dendrite.process_time = str(time.time() - start_time)
                    # Update the status code and status message of the dendrite to match the axon
                    # s.dummy_output = s.dummy_input * 2
                    s.dendrite.status_code = 200
                    s.dendrite.status_message = "OK"
                    synapse.dendrite.process_time = str(process_time)

                    if self.custom_allocs:
                        alloc_values = generate_array_with_sum(
                            np.random,
                            len(s.assets_and_pools["pools"]),
                            s.assets_and_pools["total_assets"]
                        )
                        contract_addrs = [pool.contract_address for pool in s.assets_and_pools["pools"].values()]
                        allocations = {contract_addrs[i]: alloc_values[i] for i in range(len(s.assets_and_pools["pools"]))}

                        s.allocations = allocations
                else:
                    # s.dummy_output = 0
                    s.dendrite.status_code = 408
                    s.dendrite.status_message = "Timeout"
                    synapse.dendrite.process_time = str(timeout)

                # Return the updated synapse object after deserializing if requested
                if deserialize:
                    return s.deserialize()
                else:
                    return s

            if isinstance(axons, bt.AxonInfo):
                return await single_axon_response(0, axons)
            return await asyncio.gather(*(single_axon_response(i, target_axon) for i, target_axon in enumerate(axons)))

        return await query_all_axons(streaming)

    def __str__(self) -> str:
        """
        Returns a string representation of the Dendrite object.

        Returns:
            str: The string representation of the Dendrite object in the format "dendrite(<user_wallet_address>)".
        """
        return f"MockDendrite({self.keypair.ss58_address})"
