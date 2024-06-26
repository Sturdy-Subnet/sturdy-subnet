import math
from typing import Dict
from sturdy.protocol import AllocateAssets


# NOTE: THIS IS JUST AN EXAMPLE - THIS MAY NOT WORK FOR ALL KINDS OF POOLS
def naive_algorithm(synapse: AllocateAssets) -> Dict:
    max_balance = synapse.assets_and_pools["total_assets"]
    balance = max_balance
    pools = synapse.assets_and_pools["pools"]
    alloc = math.floor(balance / len(pools))
    current_allocations = {pool_uid: alloc for pool_uid, _ in pools.items()}

    return current_allocations
