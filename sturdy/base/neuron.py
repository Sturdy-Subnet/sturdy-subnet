# The MIT License (MIT)
# Copyright © 2023 Yuma Rao

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

import copy
from abc import ABC, abstractmethod

import bittensor as bt
from bittensor.core.metagraph import AsyncMetagraph
from bittensor.core.async_subtensor import get_async_subtensor
from bittensor_wallet.mock import get_mock_wallet

from sturdy import __spec_version__ as spec_version
from sturdy.mock import MockMetagraph, MockSubtensor

# Sync calls set weights and also resyncs the metagraph.
from sturdy.utils.config import add_args, check_config, config
from sturdy.utils.misc import ttl_get_block


class BaseNeuron(ABC):
    """
    Base class for Bittensor miners. This class is abstract and should be inherited by a subclass. It contains the core logic
    for all neurons; validators and miners.

    In addition to creating a wallet, subtensor, and metagraph, this class also handles the synchronization of the network
    state via a basic checkpointing mechanism based on epoch length.
    """

    neuron_type: str = "BaseNeuron"

    @classmethod
    def check_config(cls, config: "bt.Config"):
        check_config(cls, config)

    @classmethod
    def add_args(cls, parser):
        add_args(cls, parser)

    @classmethod
    def config(cls):
        return config(cls)

    subtensor: bt.AsyncSubtensor
    # subtensor: bt.subtensor
    wallet: bt.wallet
    metagraph: AsyncMetagraph
    # metagraph: bt.metagraph
    spec_version: int = spec_version

    @property
    async def block(self):
        return await ttl_get_block(self)

    @classmethod
    async def create(cls, config=None) -> "BaseNeuron":
        """
        Factory method to create an instance of the neuron class.
        """
        # Create a new instance of the class
        instance = cls()
        # Initialize the instance asynchronously
        await instance._init_async(config=config)
        return instance

    async def _init_async(self, config=None) -> None:
        base_config = copy.deepcopy(config or BaseNeuron.config())
        self.config = self.config()
        self.config.merge(base_config)
        self.check_config(self.config)

        # Set up logging with the provided configuration and directory.
        bt.logging(config=self.config, logging_dir=self.config.full_path)

        # If a gpu is required, set the device to cuda:N (e.g. cuda:0)
        self.device = self.config.neuron.device

        # Log the configuration for reference.
        bt.logging.info(self.config)

        # Build Bittensor objects
        # These are core Bittensor classes to interact with the network.
        bt.logging.info("Setting up bittensor objects.")

        self.wallet = bt.wallet(config=self.config)
        # TODO: remove
        # self.subtensor = bt.AsyncSubtensor(config=self.config)
        self.subtensor = await get_async_subtensor(config=self.config)
        # await self.subtensor.initialize()
        self.metagraph = await self.subtensor.metagraph(self.config.netuid)

        bt.logging.info(f"Wallet: {self.wallet}")
        bt.logging.info(f"Subtensor: {self.subtensor}")
        bt.logging.info(f"Metagraph: {self.metagraph}")

        # Check if the miner is registered on the Bittensor network before proceeding further.
        await self.check_registered()

        # Each miner gets a unique identity (UID) in the network for differentiation.
        self.uid = self.metagraph.hotkeys.index(self.wallet.hotkey.ss58_address)
        bt.logging.info(
            f"Running neuron on subnet: {self.config.netuid} with uid {self.uid} using network: \
            {self.subtensor.chain_endpoint}"
        )
        self.step = 0

    @abstractmethod
    async def forward(self, synapse: bt.Synapse) -> bt.Synapse: ...

    async def sync(self) -> None:
        """
        Wrapper for synchronizing the state of the network for the given miner or validator.
        """
        try:
            await self.check_registered()
        except Exception:
            bt.logging.error("Could not check registration status! Skipping...")

        try:
            if await self.should_sync_metagraph():
                await self.resync_metagraph()
        except Exception as e:
            bt.logging.error("There was an issue with trying to sync with the metagraph! See Error:")
            bt.logging.exception(e)

        try:
            if self.should_set_weights():
                await self.set_weights()
        except Exception as e:
            bt.logging.error("Failed to set weights! See Error:")
            bt.logging.exception(e)

        # Always save state asynchronously
        await self.save_state()

    async def check_registered(self) -> None:
        # --- Check for registration.
        if not await self.subtensor.is_hotkey_registered(
            netuid=self.config.netuid,
            hotkey_ss58=self.wallet.hotkey.ss58_address,
        ):
            bt.logging.error(
                f"Wallet: {self.wallet} is not registered on netuid {self.config.netuid}."
                f" Please register the hotkey using `btcli subnets register` before trying again"
            )
            exit()

    async def should_sync_metagraph(self) -> bool:
        """
        Check if enough epoch blocks have elapsed since the last checkpoint to sync.
        """
        return (await self.block - self.metagraph.last_update[self.uid]) > self.config.neuron.epoch_length

    def should_set_weights(self) -> bool:
        # Check if enough epoch blocks have elapsed since the last epoch.
        if self.config.neuron.disable_set_weights:
            return False
        return self.neuron_type != "MinerNeuron"  # don't set weights if you're a miner

    @abstractmethod
    async def save_state(self) -> None:  # Changed to async
        pass

    @abstractmethod
    async def load_state(self) -> None:  # Changed to async for consistency
        pass
