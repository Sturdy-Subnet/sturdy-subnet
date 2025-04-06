import math
from typing import cast

import bittensor as bt
from web3.constants import ADDRESS_ZERO

from sturdy.base.miner import BaseMinerNeuron
from sturdy.pools import (
    POOL_TYPES,
    BittensorAlphaTokenPool,
    PoolFactory,
    get_minimum_allocation,
)
from sturdy.protocol import AllocateAssets

THRESHOLD = 0.99  # used to avoid over-allocations


# NOTE: THIS IS JUST AN EXAMPLE - THIS IS NOT VERY OPTIMIZED
async def naive_algorithm(self: BaseMinerNeuron, synapse: AllocateAssets) -> dict:
    bt.logging.debug(f"received request type: {synapse.request_type}")
    pools = cast(dict, synapse.assets_and_pools["pools"])

    for uid, pool in pools.items():
        if isinstance(pool, BittensorAlphaTokenPool):
            pools[uid] = PoolFactory.create_pool(
                pool_type=pool.pool_type,
                netuid=pool.netuid,
            )
        else:
            pools[uid] = PoolFactory.create_pool(
                pool_type=pool.pool_type,
                web3_provider=self.w3,  # type: ignore[]
                user_address=(
                    pool.user_address if pool.user_address != ADDRESS_ZERO else synapse.user_address
                ),  # TODO: is there a cleaner way to do this?
                contract_address=pool.contract_address,
            )
    bt.logging.debug("created pools")

    total_assets_available = int(THRESHOLD * synapse.assets_and_pools["total_assets"])
    pools = cast(dict, synapse.assets_and_pools["pools"])

    rates_sum = 0
    rates = {}

    # sync pool parameters by calling smart contracts on chain
    for pool in pools.values():
        if isinstance(pool, BittensorAlphaTokenPool):
            await pool.sync(self.subtensor)
        else:
            await pool.sync(self.w3)
    bt.logging.debug("synced pools")

    # check the amounts that have been borrowed from the pools - and account for them
    minimums = {}
    for pool_uid, pool in pools.items():
        if isinstance(pool, BittensorAlphaTokenPool):
            minimums[pool_uid] = 0
        else:
            minimums[pool_uid] = get_minimum_allocation(pool)
    bt.logging.debug("set minimum allocation amounts")

    total_assets_available -= sum(minimums.values())
    balance = int(total_assets_available)  # obtain supply rates of pools - aave pool and sturdy silo
    # rates are determined by making on chain calls to smart contracts
    for pool in pools.values():
        match pool.pool_type:
            case POOL_TYPES.DAI_SAVINGS:
                apy = await pool.supply_rate()
                rates[pool.contract_address] = apy
                rates_sum += apy
            case POOL_TYPES.BT_ALPHA:
                price = pool._price_rao
                rates[str(pool.netuid)] = price
                rates_sum += price
            case _:
                apy = await pool.supply_rate(balance // len(pools))
                rates[pool.contract_address] = apy
                rates_sum += apy

    return {pool_uid: minimums[pool_uid] + math.floor((rates[pool_uid] / rates_sum) * balance) for pool_uid in pools}
