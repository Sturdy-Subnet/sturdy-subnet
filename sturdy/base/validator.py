import argparse
import asyncio
import concurrent.futures
import copy
import json
import os
import time

import bittensor as bt
import numpy as np
import numpy.typing as npt
from dotenv import load_dotenv

from sturdy.base.neuron import BaseNeuron
from sturdy.constants import (
    NEW_TASK_INITIAL_DELAY,
    UNISWAP_V3_LP_QUERY_FREQUENCY,
)
from sturdy.protocol import MINER_TYPE
from sturdy.providers import POOL_DATA_PROVIDER_TYPE, PoolProviderFactory
from sturdy.utils.association import get_associated_evm_keys
from sturdy.utils.config import add_validator_args
from sturdy.utils.misc import normalize_numpy
from sturdy.utils.wandb import init_wandb_validator, reinit_wandb, should_reinit_wandb
from sturdy.utils.weight_utils import process_weights_for_netuid
from sturdy.validator.forward import uniswap_v3_lp_forward


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
        # Add separate query time for uniswap v3 lp forward
        self.last_uniswap_v3_lp_query_time = 0
        # Add separate query time for volume generator forward
        self.last_volume_generator_query_time = 0

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

        # setup bittensor web3 provider
        bittensor_web3_url = os.environ.get("BITTENSOR_WEB3_PROVIDER_URL")
        if bittensor_web3_url is None:
            raise ValueError("You must provide a valid bittensor web3 provider url")

        self.pool_data_providers = {
            POOL_DATA_PROVIDER_TYPE.ETHEREUM_MAINNET: await PoolProviderFactory.create_pool_provider(
                POOL_DATA_PROVIDER_TYPE.ETHEREUM_MAINNET, url=eth_provider_url
            ),
            POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET: await PoolProviderFactory.create_pool_provider(
                POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET, url=bittensor_mainnet_url
            ),
            POOL_DATA_PROVIDER_TYPE.BITTENSOR_WEB3: await PoolProviderFactory.create_pool_provider(
                POOL_DATA_PROVIDER_TYPE.BITTENSOR_WEB3, url=bittensor_web3_url
            ),
        }

        # Dendrite lets us send messages to other nodes (axons) in the network.
        self.dendrite = bt.dendrite(wallet=self.wallet)

        bt.logging.info(f"Dendrite: {self.dendrite}")

        # Set up initial scoring weights for validation
        bt.logging.info("Building validation weights.")
        self.scores = np.zeros(self.metagraph.n, dtype=np.float32)
        self.similarity_penalties = {}
        self.sorted_apys = {}
        self.sorted_axon_times = {}
        self.miner_types: dict[int, MINER_TYPE] = {}
        self.associated_evm_addresses: dict[int, str] = {}

        # Load state
        bt.logging.info("load_state()")
        await self.load_state()
        # Init sync with the network. Updates the metagraph.
        await self.sync()

        # Create asyncio event loop to manage async tasks.
        self.loop = asyncio.get_event_loop()

        # Instantiate runners
        self.should_exit: bool = False
        self.is_running: bool = False
        self.lock = asyncio.Lock()

        self._stop_event = asyncio.Event()
        self._tasks = []
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.config.validator.max_workers)

    def __del__(self) -> None:
        if self.thread_pool:
            # Shutdown the thread pool when the object is deleted
            bt.logging.info("Shutting down thread pool...")
            self.thread_pool.shutdown(wait=True)

    async def start(self) -> None:
        """Start validator tasks"""
        await asyncio.sleep(NEW_TASK_INITIAL_DELAY)
        self._tasks.append(asyncio.create_task(self.run_uniswap_v3_lp_loop()))

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

    async def uniswap_v3_lp_forward(self) -> any:
        """
        Forward pass for Uniswap V3 LP allocations.
        """
        bt.logging.debug("uniswap_v3_lp_forward()")
        return await uniswap_v3_lp_forward(self)

    async def run_uniswap_v3_lp_loop(self) -> None:
        """Uniswap V3 LP validator loop running in parallel"""
        bt.logging.info("Uniswap V3 LP validator starting...")

        try:
            while not self._stop_event.is_set():
                current_time = time.time()
                # Use a different frequency if desired, or make it configurable

                if current_time - self.last_uniswap_v3_lp_query_time > UNISWAP_V3_LP_QUERY_FREQUENCY:
                    bt.logging.info("Running uniswap_v3_lp_forward")

                    try:
                        await self.uniswap_v3_lp_forward()
                    except Exception as e:
                        bt.logging.exception(f"Error in uniswap_v3_lp_forward: {e}")

                    self.last_uniswap_v3_lp_query_time = current_time

                await asyncio.sleep(1)

        except Exception as e:
            bt.logging.exception(f"Error in uniswap v3 lp loop: {e}")

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
        """
        Resyncs the metagraph, miner types, evm address associations,
        and updates the hotkeys and moving averages based on the new metagraph.
        """
        bt.logging.info("resync_metagraph()")

        # Copies state of metagraph before syncing.
        previous_metagraph = copy.deepcopy(self.metagraph)

        # Sync the metagraph.
        await self.metagraph.sync(subtensor=self.subtensor)

        # Get commitments and convert to uid-based mapping
        commitments_raw = await self.subtensor.get_all_commitments(netuid=self.config.netuid)
        commitments = {}

        for hotkey, commitment in commitments_raw.items():
            try:
                uid = self.metagraph.hotkeys.index(hotkey)
                try:
                    commitments[uid] = json.loads(commitment)
                except json.JSONDecodeError as e:
                    bt.logging.warning(f"Failed to parse commitment JSON for hotkey {hotkey}: {e}")
                    commitments[uid] = {}
            except ValueError:
                bt.logging.warning(f"Hotkey {hotkey} not found in metagraph, skipping commitment")

        old_miner_types = copy.deepcopy(self.miner_types)
        bt.logging.debug(f"Miner type commitments: {commitments}")

        # Update miner types from commitments
        for uid, commitment in commitments.items():
            try:
                new_type = MINER_TYPE(commitment.get("miner_type", MINER_TYPE.UNISWAP_V3_LP))
            except Exception as e:
                new_type = MINER_TYPE.UNISWAP_V3_LP
                bt.logging.warning(f"Invalid miner type for uid {uid}, defaulting to UNISWAP_V3_LP: {e}")
            if uid not in self.miner_types or self.miner_types[uid] != new_type:
                bt.logging.info(f"Miner {uid} changed type to {new_type}")
            self.miner_types[uid] = new_type

        bt.logging.debug(f"Updated miner types: {self.miner_types}")

        # Check if a miner changed their miner_type since last time
        for uid in self.miner_types:
            if uid in old_miner_types and old_miner_types[uid] != self.miner_types[uid]:
                bt.logging.warning(
                    f"Miner {uid} changed type from {old_miner_types[uid]} to {self.miner_types[uid]}, resetting score!!!"
                )
                self.scores[uid] = 0

        # Get the associated EVM addresses for each hotkey that is a LP miner and volume generator
        taofi_miner_uids = [
            uid
            for uid, miner_type in self.miner_types.items()
            if miner_type == MINER_TYPE.UNISWAP_V3_LP or miner_type == MINER_TYPE.VOLUME_GENERATOR
        ]
        self.associated_evm_addresses: dict[int, str] = await get_associated_evm_keys(
            self.config.netuid, taofi_miner_uids, self.subtensor
        )
        bt.logging.debug(f"Associated EVM addresses: {self.associated_evm_addresses}")

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

    def update_scores(self, rewards: npt.NDArray, uids: list[int], alpha: float) -> None:
        """Performs exponential moving average on the scores based on the rewards received from the miners."""

        # log the params
        bt.logging.debug(f"update_scores() called with rewards: {rewards}, uids: {uids}, alpha: {alpha}")
        # log self.scores
        bt.logging.debug(f"Current scores: {self.scores}")

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

        # create mask for the uids that we want to update scores for
        mask = np.isin(np.arange(len(self.scores)), uids_tensor)
        if not np.any(mask):
            bt.logging.debug("No valid UIDs to update scores for.")
            return
        bt.logging.debug(f"Mask for updating scores: {mask}")
        self.scores[mask] = np.clip(alpha * scattered_rewards[mask] + (1 - alpha) * self.scores[mask], a_min=0, a_max=1)
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
                miner_types=self.miner_types,
            ),
        )

        bt.logging.info("Saved")

    async def load_state(self) -> None:
        """Loads the state of the validator from a file asynchronously."""
        bt.logging.info("Loading validator state.")

        state_path = f"{self.config.neuron.full_path}/state.npz"

        try:
            # Load state in executor
            state = await asyncio.get_event_loop().run_in_executor(None, lambda: np.load(state_path, allow_pickle=True))

            self.step = state["step"]
            self.scores = state["scores"]
            self.hotkeys = state["hotkeys"]

            # Handle miner_types with potential enum errors
            self.miner_types = {}
            try:
                # Check if miner_types exists in state
                if "miner_types" in state.files:
                    try:
                        miner_types = state["miner_types"]
                        raw_miner_types = miner_types.item() if isinstance(miner_types, np.ndarray) else miner_types

                        # Clean up invalid miner types
                        for uid, miner_type_value in raw_miner_types.items():
                            try:
                                # Try to convert to MINER_TYPE enum
                                self.miner_types[uid] = MINER_TYPE(miner_type_value)
                            except ValueError:
                                # If invalid value, default to UNISWAP_V3_LP
                                bt.logging.warning(
                                    f"Invalid miner type {miner_type_value} for UID {uid}, defaulting to UNISWAP_V3_LP"
                                )
                                self.miner_types[uid] = MINER_TYPE.UNISWAP_V3_LP
                    except (ValueError, KeyError) as e:
                        # If we can't load miner_types at all due to enum issues, start fresh
                        bt.logging.warning(
                            f"Could not load miner_types due to enum error: {e}. Starting with empty miner_types."
                        )
                        self.miner_types = {}
            except Exception as e:
                bt.logging.warning(f"Unexpected error loading miner_types: {e}. Starting with empty miner_types.")
                self.miner_types = {}

            bt.logging.info(f"Loaded state with {len(self.hotkeys)} hotkeys")

        except FileNotFoundError:
            bt.logging.info(f"No state file found at {state_path}. Starting with empty state.")
            self.step = 0
            self.scores = np.zeros(self.metagraph.n, dtype=np.float32)
            self.hotkeys = copy.deepcopy(self.metagraph.hotkeys)
