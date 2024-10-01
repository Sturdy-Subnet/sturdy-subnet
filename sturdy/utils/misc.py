# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 Opentensor Foundation

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

import time
from collections.abc import Callable
from decimal import Decimal
from functools import lru_cache, update_wrapper
from math import floor
from typing import Any

import bittensor as bt
import numpy as np
from pydantic import BaseModel

from sturdy.constants import (
    RESERVE_FACTOR_MASK,
    RESERVE_FACTOR_START_BIT_POSITION,
    SIG_FIGS,
)
from sturdy.utils.ethmath import wei_div, wei_mul

# TODO: cleanup functions - lay them out better across files?


# rand range but float
def randrange_float(
    start,
    stop,
    step,
    sig: int = SIG_FIGS,
    max_prec: int = SIG_FIGS,
    rng_gen: Any = np.random.RandomState,
) -> float:
    num_steps = int((stop - start) / step)
    random_step = rng_gen.randint(0, num_steps + 1)
    return format_num_prec(start + random_step * step, sig=sig, max_prec=max_prec)


def retry_with_backoff(func, *args: Any, **kwargs: Any) -> Any:
    """
    Retry a function with exponential backoff and jitter when rate limited.
    """
    max_retries = 5  # Maximum number of retries
    base_delay = 0.1  # Initial delay in seconds
    max_delay = 60  # Maximum delay in seconds

    retries = 0
    while retries < max_retries:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "Rate limited" in str(e):
                delay = min(base_delay * 2**retries, max_delay)
                jitter = np.random.uniform(delay / 2, delay * 1.5)  # noqa: NPY002
                time.sleep(jitter)
                retries += 1
            else:
                raise
    raise Exception(f"Maximum retries ({max_retries}) exceeded for {func.__name__}")  # noqa: TRY002


def rayMul(a: int, b: int) -> int:  # noqa: N802
    """Multiplies two ray, rounding half up to the nearest ray
    See:
    https://github.com/aave/aave-v3-core/blob/724a9ef43adf139437ba87dcbab63462394d4601/contracts/protocol/libraries/math/WadRayMath.sol#L65
    """
    HALF_RAY = 10**27 // 2
    RAY = 10**27

    # Check for overflow
    if b == 0 or a <= (2**256 - 1 - HALF_RAY) // b:
        return (a * b + HALF_RAY) // RAY
    raise ValueError("Multiplication overflow")


def getReserveFactor(reserve_configuration) -> int:  # noqa: N802
    return (reserve_configuration.data & ~RESERVE_FACTOR_MASK) >> RESERVE_FACTOR_START_BIT_POSITION


def get_synapse_from_body(
    body: BaseModel,
    synapse_model: type[bt.Synapse],
) -> bt.Synapse:
    body_dict = body.dict()
    return synapse_model(**body_dict)


def format_num_prec(num: float, sig: int = SIG_FIGS, max_prec: int = SIG_FIGS) -> float:
    return float(f"{{0:.{max_prec}f}}".format(float(format(num, f".{sig}f"))))


def borrow_rate(util_rate, pool) -> int:
    return (
        pool.base_rate + wei_mul(wei_div(util_rate, pool.optimal_util_rate), pool.base_slope)
        if util_rate < pool.optimal_util_rate
        else pool.base_rate
        + pool.base_slope
        + wei_mul(
            wei_div((util_rate - pool.optimal_util_rate), (1e18 - pool.optimal_util_rate)),
            pool.kink_slope,
        )
    )



def supply_rate(util_rate, pool) -> int:
    return wei_mul(util_rate, pool.borrow_rate)


# LRU Cache with TTL
def ttl_cache(maxsize: int = 128, typed: bool = False, ttl: int = -1) -> Any:
    """
    Decorator that creates a cache of the most recently used function calls with a time-to-live (TTL) feature.
    The cache evicts the least recently used entries if the cache exceeds the `maxsize` or if an entry has
    been in the cache longer than the `ttl` period.

    Args:
        maxsize (int): Maximum size of the cache. Once the cache grows to this size, subsequent entries
                       replace the least recently used ones. Defaults to 128.
        typed (bool): If set to True, arguments of different types will be cached separately. For example,
                      f(3) and f(3.0) will be treated as distinct calls with distinct results. Defaults to False.
        ttl (int): The time-to-live for each cache entry, measured in seconds. If set to a non-positive value,
                   the TTL is set to a very large number, effectively making the cache entries permanent. Defaults to -1.

    Returns:
        Callable: A decorator that can be applied to functions to cache their return values.

    The decorator is useful for caching results of functions that are expensive to compute and are called
    with the same arguments frequently within short periods of time. The TTL feature helps in ensuring
    that the cached values are not stale.

    Example:
        @ttl_cache(ttl=10)
        def get_data(param):
            # Expensive data retrieval operation
            return data
    """
    if ttl <= 0:
        ttl = 65536
    hash_gen = _ttl_hash_gen(ttl)

    def wrapper(func: Callable) -> Callable:
        @lru_cache(maxsize, typed)
        def ttl_func(ttl_hash, *args, **kwargs) -> Any:  # noqa: ANN002, ANN003, ARG001
            return func(*args, **kwargs)

        def wrapped(*args, **kwargs) -> Any:  # noqa: ANN002, ANN003
            th = next(hash_gen)
            return ttl_func(th, *args, **kwargs)

        return update_wrapper(wrapped, func)

    return wrapper


def _ttl_hash_gen(seconds: int):  # noqa: ANN202
    """
    Internal generator function used by the `ttl_cache` decorator to generate a new hash value at regular
    time intervals specified by `seconds`.

    Args:
        seconds (int): The number of seconds after which a new hash value will be generated.

    Yields:
        int: A hash value that represents the current time interval.

    This generator is used to create time-based hash values that enable the `ttl_cache` to determine
    whether cached entries are still valid or if they have expired and should be recalculated.
    """
    start_time = time.time()
    while True:
        yield floor((time.time() - start_time) / seconds)


# 12 seconds updating block.
@ttl_cache(maxsize=1, ttl=12)
def ttl_get_block(self) -> int:
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
    return self.subtensor.get_current_block()
