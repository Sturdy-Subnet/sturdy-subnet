import math
from typing import Dict
from sturdy.base.miner import BaseMinerNeuron
from sturdy.pools import (
    POOL_TYPES,
    AaveV3DefaultInterestRatePool,
    BasePool,
    CompoundV3Pool,
    DaiSavingsRate,
    VariableInterestSturdySiloStrategy,
)
from sturdy.protocol import REQUEST_TYPES, AllocateAssets
import bittensor as bt


# NOTE: THIS IS JUST AN EXAMPLE - THIS MAY NOT WORK FOR ALL KINDS OF POOLS
def naive_algorithm(self: BaseMinerNeuron, synapse: AllocateAssets) -> Dict:
    bt.logging.debug(f"received request type: {synapse.request_type}")
    pools = synapse.assets_and_pools["pools"]
    match synapse.request_type:
        case REQUEST_TYPES.ORGANIC:
            for uid in pools:
                match pools[uid].pool_type:
                    case POOL_TYPES.AAVE:
                        pools[uid] = AaveV3DefaultInterestRatePool(**pools[uid].dict())
                    case POOL_TYPES.STURDY_SILO:
                        pools[uid] = VariableInterestSturdySiloStrategy(
                            **pools[uid].dict()
                        )
                    case POOL_TYPES.DAI_SAVINGS:
                        pools[uid] = DaiSavingsRate(**pools[uid].dict())
                    case POOL_TYPES.COMPOUND_V3:
                        pools[uid] = CompoundV3Pool(**pools[uid].dict())
                    case _:
                        pass

        case _:  # we assume it is a synthetic request
            for uid in pools:
                pools[uid] = BasePool(**pools[uid].dict())

    balance = synapse.assets_and_pools["total_assets"]
    pools = synapse.assets_and_pools["pools"]

    supply_rate_sum = 0
    supply_rates = {}

    # sync pool parameters by calling smart contracts on chain
    for _uid, pool in pools.items():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                pool.sync(self.w3)
            case POOL_TYPES.STURDY_SILO:
                pool.sync(synapse.user_address, self.w3)
            case T if T in (POOL_TYPES.DAI_SAVINGS, POOL_TYPES.COMPOUND_V3):
                pool.sync(self.w3)
            case _:
                pass

    # obtain supply rates of pools - aave pool and sturdy silo
    # rates are determined by making on chain calls to smart contracts
    for _uid, pool in pools.items():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                apy = pool.supply_rate(synapse.user_address, balance // len(pools))
                supply_rates[pool.pool_id] = apy
                supply_rate_sum += apy
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.COMPOUND_V3):
                apy = pool.supply_rate(balance // len(pools))
                supply_rates[pool.pool_id] = apy
                supply_rate_sum += apy
            case POOL_TYPES.DAI_SAVINGS:
                apy = pool.supply_rate()
                supply_rates[pool.pool_id] = apy
                supply_rate_sum += apy
            case POOL_TYPES.SYNTHETIC:
                apy = pool.supply_rate
                supply_rates[pool.pool_id] = apy
                supply_rate_sum += apy
            case _:
                pass

    current_allocations = {
        pool_uid: math.floor((supply_rates[pool_uid] / supply_rate_sum) * balance)
        for pool_uid, _ in pools.items()
    }

    return current_allocations
