import argparse
import asyncio
import concurrent.futures
import copy
import os
import time

import bittensor as bt
import numpy as np
import numpy.typing as npt
from dotenv import load_dotenv

from sturdy.base.neuron import BaseNeuron
from sturdy.constants import QUERY_FREQUENCY
from sturdy.mock import MockDendrite
from sturdy.providers import POOL_DATA_PROVIDER_TYPE, PoolProviderFactory
from sturdy.utils.config import add_validator_args
from sturdy.utils.misc import normalize_numpy
from sturdy.utils.wandb import init_wandb_validator, reinit_wandb, should_reinit_wandb
from sturdy.utils.weight_utils import process_weights_for_netuid


class BaseValidatorNeuron(BaseNeuron):
    """
    Base class for Bittensor validators. Your validator should inherit from this class.
    """

    neuron_type: str = "ValidatorNeuron"

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser) -> None:
        super().add_args(parser)
        add_validator_args(cls, parser)

    async def _init_async(self, config=None) -> None:
        # Initialize thread_pool first before any potential early returns
        self.thread_pool = None

        await super()._init_async(config=config)
        load_dotenv()

        # set last query time to be 0
        self.last_query_time = 0

        # init wandb
        self.wandb_run_log_count = 0
        if not self.config.wandb.off:
            bt.logging.debug("loading wandb")
            init_wandb_validator(self=self)
        else:
            self.wandb = None

        # Save a copy of the hotkeys to local memory.
        self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)

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

        # Dendrite lets us send messages to other nodes (axons) in the network.
        if self.config.mock:
            self.dendrite = MockDendrite(wallet=self.wallet)
        else:
            self.dendrite = bt.dendrite(wallet=self.wallet)

        bt.logging.info(f"Dendrite: {self.dendrite}")

        # Set up initial scoring weights for validation
        bt.logging.info("Building validation weights.")
        self.scores = np.zeros(self.metagraph.n, dtype=np.float32)
        self.similarity_penalties = {}
        self.sorted_apys = {}
        self.sorted_axon_times = {}

        # Load state
        bt.logging.info("load_state()")
        await self.load_state()
        # Init sync with the network. Updates the metagraph.
        await self.sync()

        # Serve axon to enable external connections.
        if not self.config.neuron.axon_off:
            await self.serve_axon()
        else:
            bt.logging.warning("axon off, not serving ip to chain.")

        # Create asyncio event loop to manage async tasks.
        self.loop = asyncio.get_event_loop()

        # Instantiate runners
        self.should_exit: bool = False
        self.is_running: bool = False
        self.lock = asyncio.Lock()

        self._stop_event = asyncio.Event()
        self._tasks = []
        self.last_query_time = 0
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.config.validator.max_workers)

    def __del__(self) -> None:
        if self.thread_pool:
            # Shutdown the thread pool when the object is deleted
            bt.logging.info("Shutting down thread pool...")
            self.thread_pool.shutdown(wait=True)

    async def start(self) -> None:
        """Start validator tasks"""
        self._tasks.append(asyncio.create_task(self.run_main_loop()))

    async def stop(self) -> None:
        """Stop all validator tasks"""
        self._stop_event.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            bt.logging.debug("Ran validator tasks")
            self._tasks.clear()
            bt.logging.debug("Cleared validator tasks")

    async def __aenter__(self) -> "BaseValidatorNeuron":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
        if self.wandb:
            self.wandb.finish()

    async def run_main_loop(self) -> None:
        """Main validator loop"""
        await self.sync()
        bt.logging.info("Validator starting...")

        try:
            while not self._stop_event.is_set():
                current_time = time.time()
                if current_time - self.last_query_time > QUERY_FREQUENCY:
                    bt.logging.info(f"step({self.step})")

                    try:
                        await self.concurrent_forward()
                    except Exception as e:
                        bt.logging.exception(f"Error in concurrent forward: {e}")

                    self.last_query_time = current_time
                    await self.sync()
                    bt.logging.debug("Syncing complete")
                    self.step += 1
                    bt.logging.debug("Logging metrics")
                    self.log_metrics()
                    bt.logging.debug("Logged metrics")

                await asyncio.sleep(1)

        except Exception as e:
            bt.logging.exception(f"Error in main loop: {e}")

    def log_metrics(self) -> None:
        """Log metrics to wandb"""
        if self.config.wandb.off:
            return

        try:
            metrics = {f"miner_scores/score_uid_{uid}": float(score) for uid, score in enumerate(self.scores)}
            metrics.update(
                {
                    "validator_run_step": self.step,
                    **{f"similarity_penalties/uid_{uid}": score for uid, score in self.similarity_penalties.items()},
                    **{f"apys/uid_{uid}": apy for uid, apy in self.sorted_apys.items()},
                    **{f"axon_times/uid_{uid}": time for uid, time in self.sorted_axon_times.items()},
                }
            )

            self.wandb.log(metrics)
            self.wandb_run_log_count += 1

            if should_reinit_wandb(self):
                reinit_wandb(self)

        except Exception as e:
            bt.logging.error(f"Failed to log metrics: {e}")

    async def serve_axon(self) -> None:
        """Serve axon to enable external connections."""

        bt.logging.info("serving ip to chain...")
        try:
            self.axon = bt.axon(wallet=self.wallet, config=self.config)

            try:
                await self.subtensor.serve_axon(
                    netuid=self.config.netuid,
                    axon=self.axon,
                )
                bt.logging.info(
                    f"Running validator {self.axon} on network: {self.config.subtensor.chain_endpoint} with netuid: \
                        {self.config.netuid}"
                )
            except Exception as e:
                bt.logging.error(f"Failed to serve Axon with exception: {e}")

        except Exception as e:
            bt.logging.error(f"Failed to create Axon initialize with exception: {e}")

    async def concurrent_forward(self) -> None:
        bt.logging.info("Running concurrent_forward()")
        coroutines = [self.forward() for _ in range(self.config.neuron.num_concurrent_forwards)]
        await asyncio.gather(*coroutines)

    async def set_weights(self) -> None:
        """
        Sets the validator weights to the metagraph hotkeys based on the scores it has received from the miners. The weights
        determine the trust and incentive level the validator assigns to miner nodes on the network.
        """

        # Check if self.scores contains any NaN values and log a warning if it does.
        if np.isnan(self.scores).any():
            bt.logging.warning(
                "Scores contain NaN values. This may be due to a lack of responses from miners, or a bug in your reward \
                functions."
            )

        # Calculate the average reward for each uid across non-zero values.
        # Replace any NaN values with 0.
        raw_weights = normalize_numpy(self.scores)

        bt.logging.debug(f"raw_weights {raw_weights}")
        bt.logging.debug(f"raw_weight_uids {self.metagraph.uids}")
        # Process the raw weights to final_weights via subtensor limitations.
        (
            processed_weight_uids,
            processed_weights,
        ) = await process_weights_for_netuid(
            uids=self.metagraph.uids,
            weights=raw_weights,
            netuid=self.config.netuid,
            subtensor=self.subtensor,
            metagraph=self.metagraph,
        )

        bt.logging.debug(f"processed_weights {processed_weights}")
        bt.logging.debug(f"processed_weight_uids {processed_weight_uids}")

        # Convert to uint16 weights and uids.
        (
            uint_uids,
            uint_weights,
        ) = bt.utils.weight_utils.convert_weights_and_uids_for_emit(uids=processed_weight_uids, weights=processed_weights)
        bt.logging.debug(f"uint_weights {uint_weights}")
        bt.logging.debug(f"uint_uids {uint_uids}")

        # Set the weights on chain via our subtensor connection.
        result, msg = await self.subtensor.set_weights(
            wallet=self.wallet,
            netuid=self.config.netuid,
            uids=uint_uids,
            weights=uint_weights,
            wait_for_finalization=False,
            wait_for_inclusion=False,
            version_key=self.spec_version,
        )
        if result is True:
            bt.logging.info("set_weights on chain successfully!")
        else:
            bt.logging.error("set_weights failed", msg)

    async def resync_metagraph(self) -> None:
        """Resyncs the metagraph and updates the hotkeys and moving averages based on the new metagraph."""
        bt.logging.info("resync_metagraph()")

        # Copies state of metagraph before syncing.
        previous_metagraph = copy.deepcopy(self.metagraph)

        # Sync the metagraph.
        await self.metagraph.sync(subtensor=self.subtensor)

        # Check if the metagraph axon info has changed.
        if previous_metagraph.axons == self.metagraph.axons:
            return

        bt.logging.info("Metagraph updated, re-syncing hotkeys, dendrite pool and moving averages")
        # Zero out all hotkeys that have been replaced.
        for uid, hotkey in enumerate(self.hotkeys):
            if hotkey != self.metagraph.hotkeys[uid]:
                self.scores[uid] = 0  # hotkey has been replaced

        # Check to see if the metagraph has changed size.
        # If so, we need to add new hotkeys and moving averages.
        if len(self.hotkeys) < len(self.metagraph.hotkeys):
            # Update the size of the moving average scores.
            new_moving_average = np.zeros(self.metagraph.n)
            min_len = min(len(self.hotkeys), len(self.scores))
            new_moving_average[:min_len] = self.scores[:min_len]
            # zero out nans
            self.scores = np.clip(np.nan_to_num(new_moving_average), a_min=0, a_max=1)
        elif len(self.hotkeys) > len(self.metagraph.hotkeys):
            # Update the size of the moving average scores.
            new_moving_average = np.zeros(self.metagraph.n)
            new_moving_average = self.scores[: len(self.metagraph.hotkeys)]
            # zero out nans
            self.scores = np.clip(np.nan_to_num(new_moving_average), a_min=0, a_max=1)

        # Update the hotkeys.
        self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)

    def update_scores(self, rewards: npt.NDArray, uids: list[int]) -> None:
        """Performs exponential moving average on the scores based on the rewards received from the miners."""

        # Check if rewards contains NaN values.
        if np.isnan(rewards).any():
            bt.logging.warning(f"NaN values detected in rewards: {rewards}")
            # Replace any NaN values in rewards with 0.
            rewards = np.nan_to_num(rewards, 0)

        # Check if `uids` is already a tensor and clone it to avoid the warning.
        uids_tensor = np.copy(uids)

        # Compute forward pass rewards, assumes uids are mutually exclusive. shape: [ metagraph.n ]
        scattered_rewards: npt.NDArray = np.zeros_like(self.scores)
        np.put_along_axis(scattered_rewards, uids_tensor, rewards, axis=0)
        bt.logging.debug(f"Scattered rewards: {rewards}")

        # Update scores with rewards produced by this step. shape: [ metagraph.n ]
        alpha: float = self.config.neuron.moving_average_alpha
        self.scores: npt.NDArray = np.clip(
            np.nan_to_num(alpha * scattered_rewards + (1 - alpha) * self.scores), a_min=0, a_max=1
        )
        bt.logging.debug(f"Updated moving avg scores: {self.scores}")

    async def save_state(self) -> None:
        """Saves the state of the validator to a file asynchronously."""
        bt.logging.info("Saving validator state...")

        # Run np.savez in an executor to avoid blocking
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: np.savez(
                self.config.neuron.full_path + "/state",
                step=self.step,
                scores=self.scores,
                hotkeys=self.hotkeys,
            ),
        )

        bt.logging.info("Saved")

    async def load_state(self) -> None:
        """Loads the state of the validator from a file asynchronously."""
        bt.logging.info("Loading validator state.")

        state_path = f"{self.config.neuron.full_path}/state.npz"

        try:
            # Load state in executor
            state = await asyncio.get_event_loop().run_in_executor(None, lambda: np.load(state_path))

            self.step = state["step"]
            self.scores = state["scores"]
            self.hotkeys = state["hotkeys"]

            bt.logging.info(f"Loaded state with {len(self.hotkeys)} hotkeys")

        except FileNotFoundError:
            bt.logging.info(f"No state file found at {state_path}. Starting with empty state.")
            self.step = 0
            self.scores = np.zeros(self.metagraph.n, dtype=np.float32)
            self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)
