# ruff: noqa: RUF003 (ambiguous-unicode-character-comment) - for the equations :)
import math
from dataclasses import dataclass

from beautifultable import BeautifulTable
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

from sturdy.constants import TAOFI_GQL_URL

TRANSPORT = AIOHTTPTransport(url=TAOFI_GQL_URL)
GQL_CLIENT = Client(transport=TRANSPORT, fetch_schema_from_transport=True)

X96 = math.pow(2, 96)
X128 = math.pow(2, 128)

QUERY_BATCH_SIZE = 1000  # Default batch size for queries


# dataclass for position fees return type
@dataclass
class PositionFees:
    uncollected_fees_0: float
    uncollected_fees_1: float
    collected_fees_0: float
    collected_fees_1: float
    position_liquidity: float
    owner: str
    uncollected_fees_token1_equivalent: float = 0.0
    collected_fees_token1_equivalent: float = 0.0
    total_fees_token1_equivalent: float = 0.0


async def get_positions_fees(
    block_number: int, client: Client = GQL_CLIENT, first: int = QUERY_BATCH_SIZE, skip: int = 0
) -> dict[int, PositionFees]:
    """
    Get position fees for all positions at a specific block.

    Args:
        block_number: The block number to query
        client: The GraphQL client to use
        first: Number of positions to fetch (default: 1000)
        skip: Number of positions to skip for pagination (default: 0)

    Returns:
        Dictionary mapping position IDs to PositionFees objects
    """

    data = await client.execute_async(
        gql(POSITIONS_QUERY), variable_values={"blockNumber": block_number, "first": first, "skip": skip}
    )
    positions = data["positions"]
    positions_fees = {}

    # Cache for pool data to avoid redundant queries
    pool_data_cache = {}

    for _, position in enumerate(positions):
        symbol_0_decimals = int(position["token0"]["decimals"])
        symbol_1_decimals = int(position["token1"]["decimals"])
        position_liquidity = int(position["liquidity"])
        pool_id = position["pool"]["id"]
        owner = position["owner"]

        # Get pool data (with caching)
        if pool_id not in pool_data_cache:
            pool_tick_data = await client.execute_async(
                gql(POOL_TICK_QUERY), variable_values={"poolId": pool_id, "blockNumber": block_number}
            )
            pool_data_cache[pool_id] = {
                "token0Price": float(pool_tick_data["pool"]["token0Price"]),  # token0 price in token1
                "token1Price": float(pool_tick_data["pool"]["token1Price"]),  # token1 price in token0
            }

        # token1Price gives us how much token0 equals 1 token1
        token0_to_token1_rate = pool_data_cache[pool_id]["token1Price"]

        # The formulas below are from Uniswap Whitepaper Section 6.3 and 6.4
        # 𝑓𝑟 =𝑓𝑔−𝑓𝑏(𝑖𝑙)−𝑓𝑎(𝑖𝑢)
        # 𝑓𝑢 =𝑙·(𝑓𝑟(𝑡1)−𝑓𝑟(𝑡0))

        # used for both tokens' fee amounts
        tick_current = float(position["pool"]["tick"])
        tick_lower = float(position["tickLower"]["tickIdx"])
        tick_upper = float(position["tickUpper"]["tickIdx"])

        # Global fee growth per liquidity '𝑓𝑔' for both token 0 and token 1
        fee_growth_global_0 = float(position["pool"]["feeGrowthGlobal0X128"]) / X128
        fee_growth_global_1 = float(position["pool"]["feeGrowthGlobal1X128"]) / X128

        # Fee growth outside '𝑓𝑜' of our lower tick for both token 0 and token 1
        tick_lower_fee_growth_outside_0 = float(position["tickLower"]["feeGrowthOutside0X128"]) / X128
        tick_lower_fee_growth_outside_1 = float(position["tickLower"]["feeGrowthOutside1X128"]) / X128

        # Fee growth outside '𝑓𝑜' of our upper tick for both token 0 and token 1
        tick_upper_fee_growth_outside_0 = float(position["tickUpper"]["feeGrowthOutside0X128"]) / X128
        tick_upper_fee_growth_outside_1 = float(position["tickUpper"]["feeGrowthOutside1X128"]) / X128

        # These are '𝑓𝑏(𝑖𝑙)' and '𝑓𝑎(𝑖𝑢)' from the formula
        # for both token 0 and token 1
        tick_lower_fee_growth_below_0 = 0
        tick_lower_fee_growth_below_1 = 0
        tick_upper_fee_growth_above_0 = 0
        tick_upper_fee_growth_above_1 = 0

        # These are the calculations for '𝑓𝑎(𝑖)' from the formula
        # for both token 0 and token 1
        if tick_current >= tick_upper:
            tick_upper_fee_growth_above_0 = fee_growth_global_0 - tick_upper_fee_growth_outside_0
            tick_upper_fee_growth_above_1 = fee_growth_global_1 - tick_upper_fee_growth_outside_1
        else:
            tick_upper_fee_growth_above_0 = tick_upper_fee_growth_outside_0
            tick_upper_fee_growth_above_1 = tick_upper_fee_growth_outside_1

        # These are the calculations for '𝑓b(𝑖)' from the formula
        # for both token 0 and token 1
        if tick_current >= tick_lower:
            tick_lower_fee_growth_below_0 = tick_lower_fee_growth_outside_0
            tick_lower_fee_growth_below_1 = tick_lower_fee_growth_outside_1
        else:
            tick_lower_fee_growth_below_0 = fee_growth_global_0 - tick_lower_fee_growth_outside_0
            tick_lower_fee_growth_below_1 = fee_growth_global_1 - tick_lower_fee_growth_outside_1

        # Calculations for '𝑓𝑟(𝑡1)' part of the '𝑓𝑢 =𝑙·(𝑓𝑟(𝑡1)−𝑓𝑟(𝑡0))' formula
        # for both token 0 and token 1
        fr_t1_0 = fee_growth_global_0 - tick_lower_fee_growth_below_0 - tick_upper_fee_growth_above_0
        fr_t1_1 = fee_growth_global_1 - tick_lower_fee_growth_below_1 - tick_upper_fee_growth_above_1

        # '𝑓𝑟(𝑡0)' part of the '𝑓𝑢 =𝑙·(𝑓𝑟(𝑡1)−𝑓𝑟(𝑡0))' formula
        # for both token 0 and token 1
        fee_growth_inside_last_0 = float(position["feeGrowthInside0LastX128"]) / X128
        fee_growth_inside_last_1 = float(position["feeGrowthInside1LastX128"]) / X128

        # The final calculations for the '𝑓𝑢 =𝑙·(𝑓𝑟(𝑡1)−𝑓𝑟(𝑡0))' uncollected fees formula
        # for both token 0 and token 1 since we now know everything that is needed to compute it
        uncollected_fees_0 = position_liquidity * (fr_t1_0 - fee_growth_inside_last_0)
        uncollected_fees_1 = position_liquidity * (fr_t1_1 - fee_growth_inside_last_1)

        # Collected fees
        collected_fees_0 = max(0, float(position["collectedFeesToken0"]))
        collected_fees_1 = max(0, float(position["collectedFeesToken1"]))

        # Decimal adjustment to get final results
        uncollected_fees_adjusted_0 = max(0, uncollected_fees_0 / math.pow(10, symbol_0_decimals))
        uncollected_fees_adjusted_1 = max(0, uncollected_fees_1 / math.pow(10, symbol_1_decimals))

        # Decimal adjustment for collected fees too
        collected_fees_adjusted_0 = collected_fees_0 / math.pow(10, symbol_0_decimals)
        collected_fees_adjusted_1 = collected_fees_1 / math.pow(10, symbol_1_decimals)

        # Calculate token1 equivalent values using ADJUSTED values for both
        uncollected_fees_token1_equivalent = uncollected_fees_adjusted_0 * token0_to_token1_rate + uncollected_fees_adjusted_1

        # Fixed: use adjusted values for collected fees too
        collected_fees_token1_equivalent = collected_fees_adjusted_0 * token0_to_token1_rate + collected_fees_adjusted_1

        # Total fees in token1 equivalent
        total_fees_token1_equivalent = uncollected_fees_token1_equivalent + collected_fees_token1_equivalent

        positions_fees[int(position["id"])] = PositionFees(
            uncollected_fees_adjusted_0,
            uncollected_fees_adjusted_1,
            collected_fees_adjusted_0,  # Use adjusted value
            collected_fees_adjusted_1,  # Use adjusted value
            position_liquidity,
            owner,
            uncollected_fees_token1_equivalent,
            collected_fees_token1_equivalent,
            total_fees_token1_equivalent,
        )

        # log the prices for debugging

    return positions_fees


# use this to calculate the uncalculated fees, liuqidity, etc. growth from starting block to end block
async def calculate_fee_growth(
    block_start: int, block_end: int, client: Client = GQL_CLIENT
) -> tuple[dict[int, PositionFees], dict[int, PositionFees], dict[int, PositionFees]]:
    """
    Calculate the fee growth for positions between two blocks.

    Args:
        block_start: Starting block number
        block_end: Ending block number
        client: The GraphQL client to use

    Returns:
        Tuple of (start_positions, end_positions, growth_positions)
    """
    positions_fees_start = await get_all_positions_fees(block_start, client)
    positions_fees_end = await get_all_positions_fees(block_end, client)

    positions_growth = {}
    for position_id in positions_fees_start:
        if position_id not in positions_fees_end:
            # Use owner from start position since end position doesn't exist
            start_fees = positions_fees_start[position_id]
            positions_growth[position_id] = PositionFees(0, 0, 0, 0, 0, start_fees.owner, 0.0, 0.0, 0.0)
            continue

        # Calculate the growth in fees and liquidity
        start_fees = positions_fees_start[position_id]
        end_fees = positions_fees_end[position_id]
        liquidity_growth = end_fees.position_liquidity - start_fees.position_liquidity

        # If liquidity growth is negative, assume fee growths are zero
        if liquidity_growth < 0:
            growth = PositionFees(0, 0, 0, 0, liquidity_growth, end_fees.owner, 0.0, 0.0, 0.0)
        else:
            growth = PositionFees(
                max(0, end_fees.uncollected_fees_0 - start_fees.uncollected_fees_0),
                max(0, end_fees.uncollected_fees_1 - start_fees.uncollected_fees_1),
                max(0, end_fees.collected_fees_0 - start_fees.collected_fees_0),
                max(0, end_fees.collected_fees_1 - start_fees.collected_fees_1),
                liquidity_growth,
                end_fees.owner,
                max(0, end_fees.uncollected_fees_token1_equivalent - start_fees.uncollected_fees_token1_equivalent),
                max(0, end_fees.collected_fees_token1_equivalent - start_fees.collected_fees_token1_equivalent),
                max(0, end_fees.total_fees_token1_equivalent - start_fees.total_fees_token1_equivalent),
            )
        positions_growth[position_id] = growth

    return positions_fees_start, positions_fees_end, positions_growth


# GraphQL queries with proper parametrization and formatting
POSITIONS_QUERY = """
    query GetTokenPositions($blockNumber: Int!, $first: Int = 1000, $skip: Int = 0) {
        positions(first: $first, skip: $skip, block: {number: $blockNumber}) {
            id
            owner
            collectedFeesToken0
            collectedFeesToken1
            token0 {
                symbol
                id
                decimals
            }
            token1 {
                symbol
                id
                decimals
            }
            pool {
                id
                liquidity
                sqrtPrice
                tick
                feeGrowthGlobal0X128
                feeGrowthGlobal1X128
            }
            liquidity
            depositedToken0
            depositedToken1
            feeGrowthInside0LastX128
            feeGrowthInside1LastX128
            tickLower {
                tickIdx
                price0
                price1
                feeGrowthOutside0X128
                feeGrowthOutside1X128
            }
            tickUpper {
                tickIdx
                price0
                price1
                feeGrowthOutside0X128
                feeGrowthOutside1X128
            }
            withdrawnToken0
            withdrawnToken1
            collectedFeesToken0
            collectedFeesToken1
            transaction {
                timestamp
                blockNumber
            }
        }
    }
"""

POOL_TICK_QUERY = """
    query GetPoolTick($poolId: ID!, $blockNumber: Int!) {
        pool(id: $poolId, block: {number: $blockNumber}) {
            tick
            token0Price
            token1Price
        }
    }
"""


async def get_pool_tick(pool_id: str, block_number: int, client: Client = GQL_CLIENT) -> int:
    """
    Get the current tick for a specific pool.

    Args:
        pool_id: The pool ID to query
        client: The GraphQL client to use

    Returns:
        The current tick value for the pool
    """
    data = await client.execute_async(
        gql(POOL_TICK_QUERY), variable_values={"poolId": pool_id.lower(), "blockNumber": block_number}
    )
    return int(data["pool"]["tick"])


async def get_all_positions_fees(
    block_number: int, client: Client = GQL_CLIENT, batch_size: int = QUERY_BATCH_SIZE
) -> dict[int, PositionFees]:
    """
    Get all position fees at a specific block, handling pagination automatically.

    Args:
        block_number: The block number to query
        client: The GraphQL client to use
        batch_size: Number of positions to fetch per request (default: 1000)

    Returns:
        Dictionary mapping position IDs to PositionFees objects for all positions
    """
    all_positions = {}
    skip = 0

    while True:
        batch_positions = await get_positions_fees(block_number=block_number, client=client, first=batch_size, skip=skip)

        if not batch_positions:
            break

        all_positions.update(batch_positions)

        # If we got fewer positions than requested, we've reached the end
        if len(batch_positions) < batch_size:
            break

        skip += batch_size

    return all_positions


# function to display position fee growth information in a table format
def display_position_fees_growth(positions_growth: dict[int, PositionFees]) -> None:
    """
    Display position fees growth in a table format.

    Args:
        positions_growth: Dictionary mapping position IDs to PositionFees objects with growth data
    """
    table = BeautifulTable()
    table.column_headers = [
        "Position ID",
        "Uncollected Fees 0 Growth",
        "Uncollected Fees 1 Growth",
        "Collected Fees 0 Growth",
        "Collected Fees 1 Growth",
        "Uncollected Fees Token1 Equivalent Growth",
        "Collected Fees Token1 Equivalent Growth",
        "Total Fees Token1 Equivalent Growth",
    ]

    for position_id, fees in positions_growth.items():
        table.append_row(
            [
                position_id,
                f"{fees.uncollected_fees_0:.6f}",
                f"{fees.uncollected_fees_1:.6f}",
                f"{fees.collected_fees_0:.6f}",
                f"{fees.collected_fees_1:.6f}",
                f"{fees.uncollected_fees_token1_equivalent:.6f}",
                f"{fees.collected_fees_token1_equivalent:.6f}",
                f"{fees.total_fees_token1_equivalent:.6f}",
            ]
        )

    print(table)
