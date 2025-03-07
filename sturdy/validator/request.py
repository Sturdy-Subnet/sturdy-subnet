from dataclasses import dataclass
import bittensor as bt


@dataclass
class Request:
    """
    A request to be sent to a miner.
    """

    uid: int
    axon: bt.axon
    response_time: float | None = None
    deserialized: dict[str, object] | None = None
    synapse: bt.Synapse | None = None
    # save: bool = False
