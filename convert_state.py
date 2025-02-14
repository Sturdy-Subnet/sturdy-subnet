import numpy as np
import torch
import bittensor as bt
import argparse
import copy
import os

parser = argparse.ArgumentParser()
bt.wallet.add_args(parser)
bt.logging.add_args(parser)

parser.add_argument(
    "--neuron.name",
    type=str,
    help="Trials for this neuron go in neuron.root / (wallet_cold - wallet_hot) / neuron.name. ",
    default="validator",
)

parser.add_argument(
    "--netuid",
    type=int,
    help="netuid",
    default=10,
)

conf = bt.config(parser)


full_path = os.path.expanduser(  # noqa: PTH111
    "{}/{}/{}/netuid{}/{}".format(  # noqa: UP032
        conf.logging.logging_dir,
        conf.wallet.name,
        conf.wallet.hotkey,
        conf.netuid,
        conf.neuron.name,
    )
)

conf.neuron.full_path = os.path.expanduser(full_path)  # noqa: PTH111


def backup_state(state, config):
    state = torch.save(state, config.neuron.full_path + "/backup_state.pt")


def load_torch_state(to_load, config) -> None:
    """Loads the state of the validator from a file."""
    bt.logging.info("Loading validator state.")

    # Load the state of the validator from file.
    state = torch.load(config.neuron.full_path + "/state.pt")
    return state


def save_torch_state_as_np(state, config) -> None:
    """Saves the state of the validator to a file."""
    bt.logging.info("Saving validator state.")

    # Save the state of the validator to file.
    to_save = copy.copy(state)
    np.savez(
        config.neuron.full_path + "/state",
        step=to_save["step"],
        scores=to_save["scores"],
        hotkeys=to_save["hotkeys"],
    )


if __name__ == "__main__":
    state = {}
    print("---CONFIG---")
    print(conf)
    new_state = load_torch_state(state, conf)
    backup_state(new_state, conf)
    print("backed up state!")
    save_torch_state_as_np(new_state, conf)
    state = np.load(conf.neuron.full_path + "/state.npz")
    print("---STATE---")
    print(dict(state))
    print()
    print(
        ">>> COMPLETE! Please contact @shr1ftyy on discord if you see this message, and include the outputs provided above! <<<"
    )
