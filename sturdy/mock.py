# type: ignore[]
import asyncio
import random
import time
from typing import Optional, Union

import bittensor as bt
import numpy as np
from bittensor.utils.balance import Balance

from sturdy.constants import QUERY_TIMEOUT
from sturdy.pools import get_minimum_allocation


def generate_array_with_sum(rng_gen: np.random.RandomState, total_sum: int, min_amounts: [int]) -> list:
    length = len(min_amounts)
    # Generate an array of random numbers
    random_numbers = rng_gen.rand(length)
    min_sum = sum(min_amounts)
    delta_sum = total_sum - min_sum

    # Scale the numbers so that they add up to the desired sum
    total_random_sum = sum(random_numbers)
    scaled_numbers = [min_amounts[idx] + int((num / total_random_sum) * delta_sum) for idx, num in enumerate(random_numbers)]

    # Adjust the last element to ensure the sum is exactly total_sum
    difference = total_sum - sum(scaled_numbers)
    scaled_numbers[-1] += difference

    return scaled_numbers


class MockSubtensor(bt.MockSubtensor):
    def __init__(self, netuid, n=16, max_allowed_uids=16, wallet=None, network="mock") -> None:
        super().__init__(network=network)

        if not self.subnet_exists(netuid):
            self.create_subnet(netuid)

        # set max allowed uids
        self.chain_state["SubtensorModule"]["MaxAllowedUids"][netuid][0] = max_allowed_uids
        uids_left = n

        # Register ourself (the validator) as a neuron at uid=0
        if wallet is not None:
            self.force_register_neuron(
                netuid=netuid,
                hotkey=wallet.hotkey.ss58_address,
                coldkey=wallet.coldkey.ss58_address,
                balance=100000,
                stake=100000,
            )
            uids_left -= 1

        # Register n mock neurons who will be miners
        for i in range(1, uids_left + 1):
            self.force_register_neuron(
                netuid=netuid,
                hotkey=f"miner-hotkey-{i}",
                coldkey="mock-coldkey",
                balance=100000,
                stake=100000,
            )

    def force_register_neuron(
        self,
        netuid: int,
        hotkey: str,
        coldkey: str,
        stake: Union["Balance", float, int] = Balance(0),
        balance: Union["Balance", float, int] = Balance(0),
    ) -> int:
        """
        Force register a neuron on the mock chain, returning the UID.
        """
        stake = self._convert_to_balance(stake)
        balance = self._convert_to_balance(balance)

        subtensor_state = self.chain_state["SubtensorModule"]
        if netuid not in subtensor_state["NetworksAdded"]:
            raise Exception("Subnet does not exist")

        uid = self._register_neuron(netuid=netuid, hotkey=hotkey, coldkey=coldkey)

        subtensor_state["TotalStake"][self.block_number] = (
            self._get_most_recent_storage(subtensor_state["TotalStake"]) + stake.rao
        )
        subtensor_state["Stake"][hotkey][coldkey][self.block_number] = stake.rao

        if balance.rao > 0:
            self.force_set_balance(coldkey, balance)
        self.force_set_balance(coldkey, balance)

        return uid

    def _register_neuron(self, netuid: int, hotkey: str, coldkey: str) -> int:
        subtensor_state = self.chain_state["SubtensorModule"]
        if netuid not in subtensor_state["NetworksAdded"]:
            raise Exception("Subnet does not exist")

        subnetwork_n = self._get_most_recent_storage(subtensor_state["SubnetworkN"][netuid])

        if subnetwork_n > 0 and any(
            self._get_most_recent_storage(subtensor_state["Keys"][netuid][uid]) == hotkey for uid in range(subnetwork_n)
        ):
            # already_registered
            raise Exception("Hotkey already registered")
        else:
            # Not found
            if subnetwork_n >= self._get_most_recent_storage(subtensor_state["MaxAllowedUids"][netuid]):
                # Subnet full, replace neuron randomly
                uid = random.randint(0, subnetwork_n - 1)  # noqa: S311
            else:
                # Subnet not full, add new neuron
                # Append as next uid and increment subnetwork_n
                uid = subnetwork_n
                subtensor_state["SubnetworkN"][netuid][self.block_number] = subnetwork_n + 1

            subtensor_state["Stake"][hotkey] = {}
            subtensor_state["Stake"][hotkey][coldkey] = {}
            subtensor_state["Stake"][hotkey][coldkey][self.block_number] = 0

            subtensor_state["Uids"][netuid][hotkey] = {}
            subtensor_state["Uids"][netuid][hotkey][self.block_number] = uid

            subtensor_state["Keys"][netuid][uid] = {}
            subtensor_state["Keys"][netuid][uid][self.block_number] = hotkey

            subtensor_state["Owner"][hotkey] = {}
            subtensor_state["Owner"][hotkey][self.block_number] = coldkey

            subtensor_state["Active"][netuid][uid] = {}
            subtensor_state["Active"][netuid][uid][self.block_number] = True

            subtensor_state["LastUpdate"][netuid][uid] = {}
            subtensor_state["LastUpdate"][netuid][uid][self.block_number] = self.block_number

            subtensor_state["Rank"][netuid][uid] = {}
            subtensor_state["Rank"][netuid][uid][self.block_number] = 0.0

            subtensor_state["Emission"][netuid][uid] = {}
            subtensor_state["Emission"][netuid][uid][self.block_number] = 0.0

            subtensor_state["Incentive"][netuid][uid] = {}
            subtensor_state["Incentive"][netuid][uid][self.block_number] = 0.0

            subtensor_state["Consensus"][netuid][uid] = {}
            subtensor_state["Consensus"][netuid][uid][self.block_number] = 0.0

            subtensor_state["Trust"][netuid][uid] = {}
            subtensor_state["Trust"][netuid][uid][self.block_number] = 0.0

            subtensor_state["ValidatorTrust"][netuid][uid] = {}
            subtensor_state["ValidatorTrust"][netuid][uid][self.block_number] = 0.0

            subtensor_state["Dividends"][netuid][uid] = {}
            subtensor_state["Dividends"][netuid][uid][self.block_number] = 0.0

            subtensor_state["PruningScores"][netuid][uid] = {}
            subtensor_state["PruningScores"][netuid][uid][self.block_number] = 0.0

            subtensor_state["ValidatorPermit"][netuid][uid] = {}
            subtensor_state["ValidatorPermit"][netuid][uid][self.block_number] = False

            subtensor_state["Weights"][netuid][uid] = {}
            subtensor_state["Weights"][netuid][uid][self.block_number] = []

            subtensor_state["Bonds"][netuid][uid] = {}
            subtensor_state["Bonds"][netuid][uid][self.block_number] = []

            subtensor_state["Axons"][netuid][hotkey] = {}
            subtensor_state["Axons"][netuid][hotkey][self.block_number] = {}

            subtensor_state["Prometheus"][netuid][hotkey] = {}
            subtensor_state["Prometheus"][netuid][hotkey][self.block_number] = {}

            if hotkey not in subtensor_state["IsNetworkMember"]:
                subtensor_state["IsNetworkMember"][hotkey] = {}
            subtensor_state["IsNetworkMember"][hotkey][netuid] = {}
            subtensor_state["IsNetworkMember"][hotkey][netuid][self.block_number] = True

            return uid

    def neuron_for_uid_lite(self, uid: int, netuid: int, block: Optional[int] = None) -> Optional[bt.NeuronInfoLite]:
        if block:
            if self.block_number < block:
                raise Exception("Cannot query block in the future")

        else:
            block = self.block_number

        if netuid not in self.chain_state["SubtensorModule"]["NetworksAdded"]:
            raise Exception("Subnet does not exist")

        neuron_info = self._neuron_subnet_exists(uid, netuid, block)
        if neuron_info is None:
            return None

        else:
            neuron_info_dict = neuron_info.__dict__
            del neuron_info
            del neuron_info_dict["weights"]
            del neuron_info_dict["bonds"]

            neuron_info_lite = bt.NeuronInfoLite(**neuron_info_dict)
            return neuron_info_lite


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
                    s.dendrite.status_code = 200
                    s.dendrite.status_message = "OK"
                    synapse.dendrite.process_time = str(process_time)

                    if self.custom_allocs:
                        pools = synapse.assets_and_pools["pools"]
                        min_amounts = [get_minimum_allocation(pool) for pool in pools.values()]

                        alloc_values = generate_array_with_sum(np.random, s.assets_and_pools["total_assets"], min_amounts)
                        contract_addrs = [pool.contract_address for pool in s.assets_and_pools["pools"].values()]
                        allocations = {contract_addrs[i]: alloc_values[i] for i in range(len(s.assets_and_pools["pools"]))}

                        s.allocations = allocations
                else:
                    s.dendrite.status_code = 408
                    s.dendrite.status_message = "Timeout"
                    synapse.dendrite.process_time = str(timeout)

                # Return the updated synapse object after deserializing if requested
                if deserialize:
                    return s.deserialize()

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
