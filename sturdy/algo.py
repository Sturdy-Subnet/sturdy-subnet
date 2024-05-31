from typing import Dict
from sturdy.protocol import AllocateAssets
from sturdy.utils.misc import format_num_prec, supply_rate
from sturdy.constants import CHUNK_RATIO


def greedy_allocation_algorithm(synapse: AllocateAssets) -> Dict:
    max_balance = synapse.assets_and_pools["total_assets"]
    balance = max_balance
    pools = synapse.assets_and_pools["pools"]

    # how much of our assets we have allocated
    current_allocations = {k: 0.0 for k, _ in pools.items()}

    assert balance >= 0

    # run greedy algorithm to allocate assets to pools
    while balance > 0:
        # TODO: use np.float32 instead of format()??
        current_supply_rates = {
            k: format_num_prec(
                supply_rate(
                    util_rate=v["borrow_amount"]
                    / (current_allocations[k] + pools[k]["reserve_size"]),
                    pool=v,
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
        max_apy = max(current_supply_rates.values())
        min_apy = min(current_supply_rates.values())
        apy_range = format_num_prec(max_apy - min_apy)

        alloc_it = current_allocations.items()
        for pool_id, _ in alloc_it:
            delta = format_num_prec(
                to_allocate * ((current_supply_rates[pool_id] - min_apy) / (apy_range)),
            )
            current_allocations[pool_id] = format_num_prec(
                current_allocations[pool_id] + delta
            )
            to_allocate = format_num_prec(to_allocate - delta)

        assert to_allocate == 0  # should allocate everything from current chunk

    return current_allocations
