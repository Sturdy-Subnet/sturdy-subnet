import numpy as np
import numpy.typing as npt
from async_lru import alru_cache

# TODO: cleanup functions - lay them out better across files?


def normalize_numpy(arr, p=1, axis=0, epsilon=1e-12) -> npt.NDArray:
    """
    Normalize the input array along the specified axis to have unit p-norm.

    Parameters:
    - arr (np.ndarray): Input array to normalize.
    - p (float or int): Order of the norm (e.g., 1 for L1, 2 for L2). Default is 2.
    - axis (int): Axis along which to compute the norms. Default is 1.
    - epsilon (float): Small value to avoid division by zero. Default is 1e-12.

    Returns:
    - np.ndarray: p-norm normalized array.
    """
    # Compute the p-norm along the specified axis
    p_norm = np.linalg.norm(arr, ord=p, axis=axis, keepdims=True)
    # Avoid division by zero
    p_norm = np.maximum(p_norm, epsilon)
    # Divide the array by its p-norm
    return arr / p_norm


# 12 seconds updating block.
@alru_cache(maxsize=1, ttl=12)
async def ttl_get_block(self) -> int:
    """
    Retrieves the current block number from the blockchain. This method is cached with a time-to-live (TTL)
    of 12 seconds, meaning that it will only refresh the block number from the blockchain at most every 12 seconds,
    reducing the number of calls to the underlying blockchain interface.

    Returns:
        int: The current block number on the blockchain.

    This method is useful for applications that need to access the current block number frequently and can
    tolerate a delay of up to 12 seconds for the latest information. By using a cache with TTL, the method
    efficiently reduces the workload on the blockchain interface.

    Example:
        current_block = ttl_get_block(self)

    Note: self here is the miner or validator instance
    """
    return await self.subtensor.get_current_block()
