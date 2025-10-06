import json
import math
from dataclasses import dataclass
from pathlib import Path

from beautifultable import BeautifulTable
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

from swap.constants import TAOFI_GQL_URL

TRANSPORT = AIOHTTPTransport(url=TAOFI_GQL_URL)
GQL_CLIENT = Client(transport=TRANSPORT, fetch_schema_from_transport=True)
QUERY_BATCH_SIZE = 1000  # Default batch size for queries

NFT_POS_MGR_PATH = Path(__file__).parent.parent / "abi" / "NonfungiblePositionManager.json"
# TODO: use read_text() everywhere else?
NFT_POS_ABI = json.loads(NFT_POS_MGR_PATH.read_text())
NFT_POS_MGR_ADDR = "0x61EeA4770d7E15e7036f8632f4bcB33AF1Af1e25"

# Reward scoring parameters
WIDTH_PENALTY_EXPONENT = 1.2  # Controls how strongly wider tick ranges are penalized (higher = stronger penalty)

POSITIONS_QUERY = """
    query GetTokenPositions($blockNumber: Int!, $limit: Int = 1000, $offset: Int = 0) {
        positions: positionsAtBlock(limit: $limit, offset: $offset, blockNumber: $blockNumber) {
            id
            owner
            tickLower {
                tickIdx
            }
            tickUpper {
                tickIdx
            }
            pool {
                liquidity
                tick
                token1Price
            }
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
            liquidity
        }
    }
"""


# dataclass for position fees info return type
@dataclass
class PositionInfo:
    position_id: int
    owner: str
    liquidity: float
    tick_lower: int
    tick_upper: int
    pool_current_tick: int
    token_0_symbol: str
    token_1_symbol: str
    token_0_decimals: int
    token_1_decimals: int
    reward_score: float = 0.0  # Will be calculated based on concentration


def calculate_reward_score(liquidity: float, tick_lower: int, tick_upper: int, current_tick: int) -> float:
    """
    Calculate reward score for a position based on liquidity concentration.

    This rewards positions that:
    - Are in range (current tick between tick_lower and tick_upper)
    - Have tighter ranges (more concentrated liquidity)
    - Are centered close to the current tick
    - Provide more liquidity

    Args:
        liquidity: The amount of liquidity in the position
        tick_lower: Lower tick boundary of the position
        tick_upper: Upper tick boundary of the position
        current_tick: Current tick of the pool

    Returns:
        Score for the position (0 if out of range or invalid)
    """
    # missing/invalid tick or non-positive liquidity yields zero
    if not math.isfinite(current_tick):
        return 0.0
    if not math.isfinite(liquidity) or liquidity <= 0:
        return 0.0

    # out-of-range positions get zero score
    is_in_range = current_tick >= tick_lower and current_tick <= tick_upper
    if not is_in_range:
        return 0.0

    width = tick_upper - tick_lower
    # invalid range yields zero score
    if not math.isfinite(width) or width <= 0:
        return 0.0

    center = (tick_lower + tick_upper) / 2
    distance_from_center = abs(center - current_tick)
    width_penalty = 1 / math.pow(width, WIDTH_PENALTY_EXPONENT)  # Penalize wider ranges
    center_weight = 1 / (1 + distance_from_center)  # Favor positions close to current_tick
    base_score = width_penalty * center_weight

    return base_score * liquidity  # Incorporate liquidity


async def get_position_scores(
    block_number: int, client: Client = GQL_CLIENT, limit: int = QUERY_BATCH_SIZE, offset: int = 0
) -> dict[int, PositionInfo]:
    """
    Get position concentration scores for all positions at a specific block.

    Args:
        block_number: The block number to query
        client: The GraphQL client to use
        limit: Number of positions to fetch (default: 1000)
        offset: Number of positions to offset for pagination (default: 0)

    Returns:
        Dictionary mapping position IDs to PositionInfo objects with calculated scores
    """

    data = await client.execute_async(
        gql(POSITIONS_QUERY), variable_values={"blockNumber": block_number, "limit": limit, "offset": offset}
    )

    positions_subgraph_info = data["positions"]
    positions = {}

    for position in positions_subgraph_info:
        position_id = int(position["id"])
        position_liquidity = float(position["liquidity"])
        owner = position["owner"].lower()

        # Token information
        token_0_decimals = int(position["token0"]["decimals"])
        token_1_decimals = int(position["token1"]["decimals"])
        token_0_symbol = position["token0"]["symbol"]
        token_1_symbol = position["token1"]["symbol"]

        # Tick information
        pool_current_tick = int(position["pool"]["tick"])
        tick_lower = int(position["tickLower"]["tickIdx"])
        tick_upper = int(position["tickUpper"]["tickIdx"])

        # Calculate the reward score based on concentration
        reward_score = calculate_reward_score(
            liquidity=position_liquidity, tick_lower=tick_lower, tick_upper=tick_upper, current_tick=pool_current_tick
        )

        positions[position_id] = PositionInfo(
            position_id=position_id,
            owner=owner,
            liquidity=position_liquidity,
            tick_lower=tick_lower,
            tick_upper=tick_upper,
            pool_current_tick=pool_current_tick,
            token_0_symbol=token_0_symbol,
            token_1_symbol=token_1_symbol,
            token_0_decimals=token_0_decimals,
            token_1_decimals=token_1_decimals,
            reward_score=reward_score,
        )

    return positions


async def get_positions_with_scores(block_number: int, client: Client = GQL_CLIENT) -> dict[int, PositionInfo]:
    """
    Get all positions with concentration scores at a specific block.

    This function replaces the fee-based scoring with concentration-based scoring
    that rewards positions with tight ranges near the current price.

    Args:
        block_number: Block to query at
        client: GraphQL client

    Returns:
        Dictionary mapping position IDs to PositionInfo objects with calculated scores
    """
    return await get_all_position_scores(block_number, client)


async def get_all_position_scores(
    block_number: int, client: Client = GQL_CLIENT, batch_size: int = QUERY_BATCH_SIZE
) -> dict[int, PositionInfo]:
    """
    Get all position scores at a specific block, handling pagination automatically.

    Args:
        block_number: The block number to query
        client: The GraphQL client to use
        batch_size: Number of positions to fetch per request (default: 1000)

    Returns:
        Dictionary mapping position IDs to PositionInfo objects with calculated scores
    """
    all_positions = {}
    offset = 0

    while True:
        batch_positions = await get_position_scores(block_number=block_number, client=client, limit=batch_size, offset=offset)

        if not batch_positions:
            break

        all_positions.update(batch_positions)

        # If we got fewer positions than requested, we've reached the end
        if len(batch_positions) < batch_size:
            break

        offset += batch_size

    return all_positions


# function to display position info in a table
def display_positions_table(positions: dict[int, PositionInfo]) -> None:
    table = BeautifulTable()
    table.columns.header = [
        "Position ID",
        "Owner",
        "Liquidity",
        "Tick Lower",
        "Tick Upper",
        "Current Tick",
        "Token 0",
        "Token 1",
        "Reward Score",
    ]

    for pos in positions.values():
        table.rows.append(
            [
                pos.position_id,
                pos.owner,
                f"{pos.liquidity:.2f}",
                pos.tick_lower,
                pos.tick_upper,
                pos.pool_current_tick,
                pos.token_0_symbol,
                pos.token_1_symbol,
                f"{pos.reward_score:.4f}",
            ]
        )

    print(table)
