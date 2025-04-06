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

import argparse
import asyncio
import os
import threading
import time
import traceback

import bittensor as bt
from dotenv import load_dotenv
from web3 import AsyncWeb3

from sturdy.base.neuron import BaseNeuron
from sturdy.constants import MINER_SYNC_FREQUENCY
from sturdy.providers import POOL_DATA_PROVIDER_TYPE, PoolProviderFactory
from sturdy.utils.config import add_miner_args
from sturdy.utils.wandb import init_wandb_miner


class BaseMinerNeuron(BaseNeuron):
    """
    Base class for Bittensor miners.
    """

    neuron_type: str = "MinerNeuron"

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser):
        super().add_args(parser)
        add_miner_args(cls, parser)

    def __init__(self, config=None):
        super().__init__(config=config)
        load_dotenv()

        # init wandb
        if not self.config.wandb.off:
            bt.logging.debug("loading wandb")
            init_wandb_miner(self=self)

        # TODO: move setup to a separate function?
        # setup ethereum mainnet provider
        eth_provider_url = os.environ.get("ETHEREUM_MAINNET_PROVIDER_URL")
        if eth_provider_url is None:
            raise ValueError("You must provide a valid web3 provider url")

        # setup bittensor mainnet provider
        bittensor_mainnet_url = os.environ.get("BITTENSOR_MAINNET_PROVIDER_URL")
        if bittensor_mainnet_url is None:
            raise ValueError("You must provide a valid subtensor provider url")

        self.pool_data_providers = {
            POOL_DATA_PROVIDER_TYPE.ETHEREUM_MAINNET: PoolProviderFactory.create_pool_provider(
                POOL_DATA_PROVIDER_TYPE.ETHEREUM_MAINNET, url=eth_provider_url
            ),
            POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET: PoolProviderFactory.create_pool_provider(
                POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET, url=bittensor_mainnet_url
            ),
        }

        # Warn if allowing incoming requests from anyone.
        if not self.config.blacklist.force_validator_permit:
            bt.logging.warning("You are allowing non-validators to send requests to your miner. This is a security risk.")
        if self.config.blacklist.allow_non_registered:
            bt.logging.warning(
                "You are allowing non-registered entities to send requests to your miner. This is a security risk."
            )

        # The axon handles request processing, allowing validators to send this miner requests.
        self.axon = bt.axon(wallet=self.wallet, config=self.config)

        # Attach determiners which functions are called when servicing a request.
        bt.logging.info("Attaching forward function to miner axon.")
        self.axon.attach(
            forward_fn=self.forward,
            blacklist_fn=self.blacklist,
            priority_fn=self.priority,
        )
        bt.logging.info(f"Axon created: {self.axon}")

        # Instantiate runners
        self.should_exit: bool = False
        self.is_running: bool = False
        self.thread: threading.Thread = None
        self.lock = asyncio.Lock()

    def run(self):
        """
        Initiates and manages the main loop for the miner on the Bittensor network. The main loop handles graceful shutdown on
        keyboard interrupts and logs unforeseen errors.

        This function performs the following primary tasks:
        1. Check for registration on the Bittensor network.
        2. Starts the miner's axon, making it active on the network.
        3. Periodically resynchronizes with the chain; updating the metagraph with the latest network
        state and setting weights.

        The miner continues its operations until `should_exit` is set to True or an external interruption occurs.
        During each epoch of its operation, the miner waits for new blocks on the Bittensor network, updates its
        knowledge of the network (metagraph), and sets its weights. This process ensures the miner remains active
        and up-to-date with the network's latest state.

        Note:
            - The function leverages the global configurations set during the initialization of the miner.
            - The miner's axon serves as its interface to the Bittensor network, handling incoming and outgoing requests.

        Raises:
            KeyboardInterrupt: If the miner is stopped by a manual interruption.
            Exception: For unforeseen errors during the miner's operation, which are logged for diagnosis.
        """

        # Check that miner is registered on the network.
        self.sync()

        # Serve passes the axon information to the network + netuid we are hosting on.
        # This will auto-update if the axon port of external ip have changed.
        bt.logging.info(
            f"Serving miner axon {self.axon} on network: {self.config.subtensor.chain_endpoint} with netuid:\
            {self.config.netuid}"
        )
        self.axon.serve(netuid=self.config.netuid, subtensor=self.subtensor)

        # Start  starts the miner's axon, making it active on the network.
        self.axon.start()

        bt.logging.info("Miner starting...")

        # This loop maintains the miner's operations until intentionally stopped.
        try:
            while not self.should_exit:
                # Wait before checking again.
                time.sleep(MINER_SYNC_FREQUENCY)  # 12 seconds per block

                # Check if we should exit.
                if self.should_exit:
                    break

                # Sync metagraph and potentially set weights.
                self.sync()
                self.step += 1

        # If someone intentionally stops the miner, it'll safely terminate operations.
        except KeyboardInterrupt:
            self.axon.stop()
            exit()

        # In case of unforeseen errors, the miner will log the error and continue operations.
        except Exception as e:  # noqa
            bt.logging.error(traceback.format_exc())

    # create "with" entry and exit functions to call run() in the background for syncing, etc.
    def __enter__(self):
        self.should_exit = False
        self.thread = threading.Thread(target=self.run)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.should_exit = True
        self.thread.join()

    def resync_metagraph(self) -> None:
        """Resyncs the metagraph and updates the hotkeys and moving averages based on the new metagraph."""

        # Sync the metagraph.
        self.metagraph.sync(subtensor=self.subtensor)
