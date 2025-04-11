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
import traceback

import bittensor as bt
from dotenv import load_dotenv

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

    async def _init_async(self, config=None) -> None:
        await super()._init_async(config=config)
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
            POOL_DATA_PROVIDER_TYPE.ETHEREUM_MAINNET: await PoolProviderFactory.create_pool_provider(
                POOL_DATA_PROVIDER_TYPE.ETHEREUM_MAINNET, url=eth_provider_url
            ),
            POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET: await PoolProviderFactory.create_pool_provider(
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
        # Keep the lock if needed for other purposes
        self.lock = asyncio.Lock()

    async def run(self) -> None:
        """
        Initiates and manages the main loop for the miner on the Bittensor network.
        """
        try:
            # Check that miner is registered on the network.
            await self.sync()

            # Serve passes the axon information to the network + netuid we are hosting on.
            bt.logging.info(
                f"Serving miner axon {self.axon} on network: {self.config.subtensor.chain_endpoint} with netuid:\
                {self.config.netuid}"
            )

            # TODO: do I *have* to pass the netuid? can't it be inferred from the bt axon above?
            # TODO: should we wait for inclusion?
            await self.subtensor.serve_axon(netuid=self.config.netuid, axon=self.axon)

            # Start starts the miner's axon, making it active on the network.
            self.axon.start()

            bt.logging.info("Miner starting...")

            # This loop maintains the miner's operations until intentionally stopped.
            while not self.should_exit:
                # Wait before checking again using proper async sleep
                await asyncio.sleep(MINER_SYNC_FREQUENCY)  # 12 seconds per block

                if self.should_exit:
                    break

                # Sync metagraph and potentially set weights.
                await self.sync()
                self.step += 1

        except asyncio.CancelledError:
            # Handle graceful shutdown
            bt.logging.info("Miner task cancelled, shutting down...")
            self.axon.stop()

        except KeyboardInterrupt:
            bt.logging.info("Keyboard interrupt received, shutting down...")
            self.axon.stop()

        except Exception as e:
            bt.logging.error(f"Unexpected error in miner: {traceback.format_exc()}")

        finally:
            # Ensure axon is stopped
            if hasattr(self, "axon"):
                self.axon.stop()

    # create "with" entry and exit functions to call run() in the background for syncing, etc.
    async def __aenter__(self):
        """Async context manager entry"""
        self.should_exit = False
        # Create task instead of thread
        self.task = asyncio.create_task(self.run())
        return await asyncio.sleep(0)  # Make it awaitable by returning an awaitable :|
        # TODO: is there a better way to go about this?

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        self.should_exit = True
        # Cancel the task if it's still running
        if hasattr(self, "task") and not self.task.done():
            self.task.cancel()
            try:
                await self.task  # Wait for task to be cancelled
            except asyncio.CancelledError as e:
                bt.logging.error("Error exiting:")
                bt.logging.exception(e)

    async def resync_metagraph(self) -> None:
        """Resyncs the metagraph and updates the hotkeys and moving averages based on the new metagraph."""

        # Sync the metagraph.
        await self.metagraph.sync(subtensor=self.subtensor)
