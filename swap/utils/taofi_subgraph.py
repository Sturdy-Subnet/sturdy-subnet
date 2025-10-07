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
    reward_score: float = 0.0  # The liquidity value L (if in range)


def calculate_reward_score(liquidity: float, tick_lower: int, tick_upper: int, current_tick: int) -> float:
    """
    Calculate reward score for a position based on its liquidity value.

    In Uniswap V3, the liquidity value L already accounts for concentration.
    For a given amount of capital, tighter ranges result in higher L values.

    From the Uniswap V3 math (https://atiselsts.github.io/pdfs/uniswap-v3-liquidity-math.pdf):
    - L represents the effective liquidity available for swaps
    - Tighter ranges naturally have higher L for the same capital
    - L directly determines the price impact of trades

    This rewards positions that:
    - Are in range (current tick between tick_lower and tick_upper)
    - Have higher liquidity L (which means either more capital OR tighter range)

    Args:
        liquidity: The liquidity value L of the position
        tick_lower: Lower tick boundary of the position
        tick_upper: Upper tick boundary of the position
        current_tick: Current tick of the pool

    Returns:
        The liquidity value if in range, 0 otherwise
    """
    # Validate inputs
    if not math.isfinite(current_tick):
        return 0.0
    if not math.isfinite(liquidity) or liquidity <= 0:
        return 0.0

    # Check if position is in range
    is_in_range = current_tick >= tick_lower and current_tick <= tick_upper
    if not is_in_range:
        return 0.0

    # Return the liquidity value directly
    # This already incorporates concentration effects
    return liquidity


async def get_position_scores(
    block_number: int, client: Client = GQL_CLIENT, limit: int = QUERY_BATCH_SIZE, offset: int = 0
) -> dict[int, PositionInfo]:
    """
    Get position liquidity scores for all positions at a specific block.

    Scores positions based on their liquidity value L, which inherently
    accounts for concentration (tighter ranges have higher L for same capital).

    Args:
        block_number: The block number to query
        client: The GraphQL client to use
        limit: Number of positions to fetch (default: 1000)
        offset: Number of positions to offset for pagination (default: 0)

    Returns:
        Dictionary mapping position IDs to PositionInfo objects with liquidity scores
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

        # Calculate the reward score based on liquidity value
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
    Get all positions with liquidity-based scores at a specific block.

    Scores are based on the liquidity value L, which naturally rewards
    concentrated positions (tighter ranges yield higher L for same capital).

    Args:
        block_number: Block to query at
        client: GraphQL client

    Returns:
        Dictionary mapping position IDs to PositionInfo objects with liquidity scores
    """
    return await get_all_position_scores(block_number, client)


async def get_all_position_scores(
    block_number: int, client: Client = GQL_CLIENT, batch_size: int = QUERY_BATCH_SIZE
) -> dict[int, PositionInfo]:
    """
    Get all position liquidity scores at a specific block, handling pagination automatically.

    Scores are based on the liquidity value L for in-range positions.
    The liquidity value inherently rewards concentration since tighter
    ranges achieve higher L with the same capital.

    Args:
        block_number: The block number to query
        client: The GraphQL client to use
        batch_size: Number of positions to fetch per request (default: 1000)

    Returns:
        Dictionary mapping position IDs to PositionInfo objects with liquidity scores
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
