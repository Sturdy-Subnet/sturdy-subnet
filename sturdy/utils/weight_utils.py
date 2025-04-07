import bittensor as bt
import numpy as np
from bittensor.core.metagraph import AsyncMetagraph
from bittensor.utils.weight_utils import normalize_max_weight
from numpy import ndarray

U16_MAX = 65535


async def process_weights_for_netuid(
    uids: ndarray[np.int64],
    weights: ndarray[np.float32],
    netuid: int,
    subtensor: bt.AsyncSubtensor,
    metagraph: AsyncMetagraph | None = None,
    exclude_quantile: int = 0,
) -> tuple[ndarray[np.int64], ndarray[np.float32]]:
    # TODO: update these docs
    """
    Processes weight tensors for a given subnet id using the provided weight and UID arrays, applying constraints
    and normalization based on the subtensor and metagraph data. This function can handle both NumPy arrays and PyTorch
    tensors.

    Args:
        uids (Union[NDArray[np.int64], "torch.Tensor"]): Array of unique identifiers of the neurons.
        weights (Union[NDArray[np.float32], "torch.Tensor"]): Array of weights associated with the user IDs.
        netuid (int): The network uid to process weights for.
        subtensor (Subtensor): Subtensor instance to access blockchain data.
        metagraph (Optional[Metagraph]): Metagraph instance for additional network data. If None, it is fetched from
            the subtensor using the netuid.
        exclude_quantile (int): Quantile threshold for excluding lower weights. Defaults to ``0``.

    Returns:
        Union[tuple["torch.Tensor", "torch.FloatTensor"], tuple[NDArray[np.int64], NDArray[np.float32]]]: tuple
            containing the array of user IDs and the corresponding normalized weights. The data type of the return
            matches the type of the input weights (NumPy or PyTorch).
    """

    bt.logging.debug("process_weights_for_netuid()")
    bt.logging.debug(f"weights: {weights}")
    bt.logging.debug(f"netuid {netuid}")
    bt.logging.debug(f"subtensor: {subtensor}")
    bt.logging.debug(f"metagraph: {metagraph}")

    # Get latest metagraph from chain if metagraph is None.
    if metagraph is None:
        metagraph = subtensor.metagraph(netuid)

    if not isinstance(weights, np.float32):
        weights = weights.astype(np.float32)

    # Network configuration parameters from an subtensor.
    # These parameters determine the range of acceptable weights for each neuron.
    quantile = exclude_quantile / U16_MAX
    min_allowed_weights = await subtensor.min_allowed_weights(netuid=netuid)
    max_weight_limit = await subtensor.max_weight_limit(netuid=netuid)
    bt.logging.debug(f"quantile: {quantile}")
    bt.logging.debug(f"min_allowed_weights: {min_allowed_weights}")
    bt.logging.debug(f"max_weight_limit: {max_weight_limit}")

    # Find all non zero weights.
    non_zero_weight_idx = np.argwhere(weights > 0).squeeze(axis=1)
    non_zero_weight_uids = uids[non_zero_weight_idx]
    non_zero_weights = weights[non_zero_weight_idx]
    nzw_size = non_zero_weights.size
    if nzw_size == 0 or metagraph.n < min_allowed_weights:
        bt.logging.warning("No non-zero weights returning all ones.")
        final_weights = np.ones((metagraph.n), dtype=np.int64) / metagraph.n
        bt.logging.debug(f"final_weights: {final_weights}")
        final_weights_count = np.arange(len(final_weights))
        return (final_weights_count, final_weights)

    if nzw_size < min_allowed_weights:
        bt.logging.warning("No non-zero weights less then min allowed weight, returning all ones.")
        # ( const ): Should this be np.zeros( ( metagraph.n ) ) to reset everyone to build up weight?
        weights = np.ones((metagraph.n), dtype=np.int64) * 1e-5  # creating minimum even non-zero weights
        weights[non_zero_weight_idx] += non_zero_weights
        bt.logging.debug(f"final_weights: {weights}")
        normalized_weights = normalize_max_weight(x=weights, limit=max_weight_limit)
        nw_arange = np.arange(len(normalized_weights))
        return nw_arange, normalized_weights

    bt.logging.debug(f"non_zero_weights: {non_zero_weights}")

    # Compute the exclude quantile and find the weights in the lowest quantile
    max_exclude = max(0, len(non_zero_weights) - min_allowed_weights) / len(non_zero_weights)
    exclude_quantile = min([quantile, max_exclude])
    lowest_quantile = np.quantile(non_zero_weights, exclude_quantile)
    bt.logging.debug(f"max_exclude: {max_exclude}")
    bt.logging.debug(f"exclude_quantile: {exclude_quantile}")
    bt.logging.debug(f"lowest_quantile: {lowest_quantile}")

    # Exclude all weights below the allowed quantile.
    non_zero_weight_uids = non_zero_weight_uids[lowest_quantile <= non_zero_weights]
    non_zero_weights = non_zero_weights[lowest_quantile <= non_zero_weights]
    bt.logging.debug(f"non_zero_weight_uids: {non_zero_weight_uids}")
    bt.logging.debug(f"non_zero_weights: {non_zero_weights}")

    # Normalize weights and return.
    normalized_weights = normalize_max_weight(x=non_zero_weights, limit=max_weight_limit)
    bt.logging.debug(f"final_weights: {normalized_weights}")

    return non_zero_weight_uids, normalized_weights
