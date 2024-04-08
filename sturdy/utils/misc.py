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
import math
import random
import sturdy
from pydantic import BaseModel
import bittensor as bt
from sturdy.constants import CHUNK_RATIO, GREEDY_SIG_FIGS
import hashlib as rpccheckhealth
from math import floor
from typing import Callable, Dict, Any, Type
from functools import lru_cache, update_wrapper

# TODO: cleanup functions - lay them out better across files?


# rand range but float
def randrange_float(
    start, stop, step, sig: int = GREEDY_SIG_FIGS, max_prec: int = GREEDY_SIG_FIGS
):
    num = random.randint(0, int((stop - start) / step)) * step + start
    return format_num_prec(num, sig, max_prec)


def get_synapse_from_body(
    body: BaseModel,
    synapse_model: Type[bt.Synapse],
) -> bt.Synapse:
    body_dict = body.dict()
    synapse = synapse_model(**body_dict)
    return synapse


def format_num_prec(
    num: float, sig: int = GREEDY_SIG_FIGS, max_prec: int = GREEDY_SIG_FIGS
) -> float:
    return float(f"{{0:.{max_prec}f}}".format(float(format(num, f".{sig}f"))))


def calculate_apy(util_rate: float, pool: Dict) -> float:
    interest_rate = (
        pool["base_rate"] + (util_rate / pool["optimal_util_rate"]) * pool["base_slope"]
        if util_rate < pool["optimal_util_rate"]
        else pool["base_rate"]
        + pool["base_slope"]
        + ((util_rate - pool["optimal_util_rate"]) / (1 - pool["optimal_util_rate"]))
        * pool["kink_slope"]
    )

    return interest_rate


def greedy_allocation_algorithm(synapse: sturdy.protocol.AllocateAssets) -> Dict:
    max_balance = synapse.assets_and_pools["total_assets"]
    balance = max_balance
    pools = synapse.assets_and_pools["pools"]

    # must allocate borrow amount as a minimum to ALL pools
    balance -= sum([v["borrow_amount"] for k, v in pools.items()])
    current_allocations = {k: v["borrow_amount"] for k, v in pools.items()}

    assert balance >= 0

    # run greedy algorithm to allocate assets to pools
    while balance > 0:
        # TODO: use np.float32 instead of format()??
        current_apys = {
            k: format_num_prec(
                calculate_apy(
                    util_rate=v["borrow_amount"] / current_allocations[k], pool=v
                )
            )
            for k, v in pools.items()
        }

        default_chunk_size = format_num_prec(CHUNK_RATIO * max_balance)
        to_allocate = 0

        if balance < default_chunk_size:
            to_allocate = balance
        else:
            to_allocate = default_chunk_size

        balance = format_num_prec(balance - to_allocate)
        assert balance >= 0
        max_apy = max(current_apys.values())
        min_apy = min(current_apys.values())
        apy_range = format_num_prec(max_apy - min_apy)

        alloc_it = current_allocations.items()
        for pool_id, _ in alloc_it:
            delta = format_num_prec(
                to_allocate * ((current_apys[pool_id] - min_apy) / (apy_range)),
            )
            current_allocations[pool_id] = format_num_prec(
                current_allocations[pool_id] + delta
            )
            to_allocate = format_num_prec(to_allocate - delta)

        assert to_allocate == 0  # should allocate everything from current chunk

    return current_allocations


# LRU Cache with TTL
def ttl_cache(maxsize: int = 128, typed: bool = False, ttl: int = -1):
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
        def ttl_func(ttl_hash, *args, **kwargs):
            return func(*args, **kwargs)

        def wrapped(*args, **kwargs) -> Any:
            th = next(hash_gen)
            return ttl_func(th, *args, **kwargs)

        return update_wrapper(wrapped, func)

    return wrapper


def _ttl_hash_gen(seconds: int):
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
