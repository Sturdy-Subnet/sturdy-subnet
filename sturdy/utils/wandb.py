import wandb
import bittensor as bt
import copy

from sturdy import __version__ as THIS_VERSION
from sturdy import __spec_version__ as THIS_SPEC_VERSION


def init_wandb_miner(self, reinit=False):
    """Starts a new wandb run for a miner."""
    tags = [
        self.wallet.hotkey.ss58_address,
        THIS_VERSION,
        str(THIS_SPEC_VERSION),
        f"netuid_{self.metagraph.netuid}",
    ]

    if self.config.mock:
        tags.append("mock")

    wandb_config = {
        key: copy.deepcopy(self.config.get(key, None))
        for key in ("neuron", "reward", "netuid", "wandb")
    }

    if wandb_config["neuron"] is not None:
        wandb_config["neuron"].pop("full_path", None)

    self.wandb = wandb.init(
        anonymous="allow",
        reinit=reinit,
        project=self.config.wandb.project_name,
        entity=self.config.wandb.entity,
        config=wandb_config,
        mode="offline" if self.config.wandb.offline else "online",
        dir=(
            self.config.neuron.full_path
            if self.config.neuron is not None
            else "wandb_logs"
        ),
        tags=tags,
        notes=self.config.wandb.notes,
    )
    bt.logging.success(
        prefix="Started a new wandb run for miner",
        sufix=f"<blue> {self.wandb.name} </blue>",
    )


def init_wandb_validator(self, reinit=False):
    """Starts a new wandb run for a validator."""
    tags = [
        self.wallet.hotkey.ss58_address,
        THIS_VERSION,
        str(THIS_SPEC_VERSION),
        f"netuid_{self.metagraph.netuid}",
    ]

    if self.config.mock:
        tags.append("mock")
    if self.config.neuron.disable_set_weights:
        tags.append("disable_set_weights")
    if self.config.neuron.disable_log_rewards:
        tags.append("disable_log_rewards")

    wandb_config = {
        key: copy.deepcopy(self.config.get(key, None))
        for key in ("neuron", "reward", "netuid", "wandb")
    }
    wandb_config["neuron"].pop("full_path", None)

    self.wandb = wandb.init(
        anonymous="allow",
        reinit=reinit,
        project=self.config.wandb.project_name,
        entity=self.config.wandb.entity,
        config=wandb_config,
        mode="offline" if self.config.wandb.offline else "online",
        dir=self.config.neuron.full_path,
        tags=tags,
        notes=self.config.wandb.notes,
    )
    bt.logging.success(
        prefix="Started a new wandb run for validator",
    )


def reinit_wandb(self):
    if hasattr(self, "wandb"):
        if self.wandb is not None:
            bt.logging.info("Reinitializing wandb")
            init_wandb_validator(self, reinit=True)
            bt.logging.info("Reinitialized wandb")


def should_reinit_wandb(self):
    if self.wandb_run_log_count >= self.config.wandb.run_log_limit:
        return True
    return False
