# ruff: noqa: RUF003 (ambiguous-unicode-character-comment) - for the equations :)
import asyncio
import json
import math
from copy import copy
from dataclasses import dataclass
from pathlib import Path

from beautifultable import BeautifulTable
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from web3 import AsyncWeb3
from web3.types import BlockIdentifier

from sturdy.constants import TAOFI_GQL_URL

TRANSPORT = AIOHTTPTransport(url=TAOFI_GQL_URL)
GQL_CLIENT = Client(transport=TRANSPORT, fetch_schema_from_transport=True)

X96 = 2**96
X128 = 2**128
X256 = 2**256

QUERY_BATCH_SIZE = 1000  # Default batch size for queries

NFT_POS_MGR_PATH = Path(__file__).parent.parent / "abi" / "NonfungiblePositionManager.json"
# TODO: use read_text() everywhere else?
NFT_POS_ABI = json.loads(NFT_POS_MGR_PATH.read_text())
NFT_POS_MGR_ADDR = "0x61EeA4770d7E15e7036f8632f4bcB33AF1Af1e25"


def sub_in_256(x: int, y: int) -> int:
    """Handle overflow/underflow for subtraction in fee calculations."""
    difference = x - y
    if difference < 0:
        return X256 + difference
    return difference


# dataclass for position fees info return type
@dataclass
class PositionFeesInfo:
    uncollected_fees_0: float
    uncollected_fees_1: float
    collected_fees_0: float
    collected_fees_1: float
    # fees in token1 equivalent
    uncollected_fees_0_token1_equivalent: float
    uncollected_fees_1_token1_equivalent: float
    collected_fees_0_token1_equivalent: float
    collected_fees_1_token1_equivalent: float
    total_fees_token1_equivalent: float
    token0_to_token1_rate: float
    position_liquidity: float
    current_tick: int
    tick_lower: int
    tick_upper: int
    owner: str
    token_0_symbol: str
    token_1_symbol: str
    token_0_decimals: int
    token_1_decimals: int


async def get_position_infos_subgraph(
    block_number: int, client: Client = GQL_CLIENT, first: int = QUERY_BATCH_SIZE, skip: int = 0
) -> dict[int, PositionFeesInfo]:
    """
    Get position fees for all positions at a specific block.

    Args:
        block_number: The block number to query
        client: The GraphQL client to use
        first: Number of positions to fetch (default: 1000)
        skip: Number of positions to skip for pagination (default: 0)

    Returns:
        Dictionary mapping position IDs to PositionFeesInfo objects
    """

    data = await client.execute_async(
        gql(POSITIONS_QUERY), variable_values={"blockNumber": block_number, "first": first, "skip": skip}
    )

    positions_subgraph_info = data["positions"]
    positions_fees = {}

    for _, position in enumerate(positions_subgraph_info):
        token0_to_token1_rate = float(position["pool"]["token1Price"])
        token_0_decimals = int(position["token0"]["decimals"])
        token_1_decimals = int(position["token1"]["decimals"])

        token_0_symbol = position["token0"]["symbol"]
        token_1_symbol = position["token1"]["symbol"]

        position_liquidity = int(position["liquidity"])
        owner = position["owner"]

        # Collected fees
        collected_fees_0 = max(0, float(position["collectedFeesToken0"]))
        collected_fees_1 = max(0, float(position["collectedFeesToken1"]))

        # Decimal adjustment for collected fees too
        collected_fees_adjusted_0 = collected_fees_0 / math.pow(10, token_0_decimals)
        collected_fees_adjusted_1 = collected_fees_1 / math.pow(10, token_1_decimals)

        # Collected fees in token1 equivalent
        collected_fees_0_token1_equivalent = collected_fees_adjusted_0 * token0_to_token1_rate
        collected_fees_1_token1_equivalent = collected_fees_adjusted_1

        # Tick information
        current_tick = int(position["pool"]["tick"])
        tick_lower = int(position["tickLower"]["tickIdx"])
        tick_upper = int(position["tickUpper"]["tickIdx"])

        positions_fees[int(position["id"])] = PositionFeesInfo(
            0.0,
            0.0,
            collected_fees_adjusted_0,  # Use adjusted value
            collected_fees_adjusted_1,  # Use adjusted value
            collected_fees_0_token1_equivalent,
            collected_fees_1_token1_equivalent,
            0.0,
            0.0,
            0.0,
            token0_to_token1_rate,
            position_liquidity,
            current_tick,
            tick_lower,
            tick_upper,
            owner,
            token_0_symbol,
            token_1_symbol,
            token_0_decimals,
            token_1_decimals,
        )

        # log the prices for debugging

    return positions_fees


# use this to calculate the uncalculated fees, liuqidity, etc. growth from starting block to end block
async def calculate_fee_growth(
    web3_provider: AsyncWeb3, block_start: int, block_end: int, client: Client = GQL_CLIENT
) -> tuple[dict[int, PositionFeesInfo], dict[int, PositionFeesInfo], dict[int, PositionFeesInfo]]:
    """
    Calculate the fee growth for positions between two blocks.

    Args:
        block_start: Starting block number
        block_end: Ending block number
        client: The GraphQL client to use

    Returns:
        Tuple of (start_positions, end_positions, growth_positions)
    """
    positions_fees_start = await get_all_positions_fees(web3_provider, block_start, client)
    positions_fees_end = await get_all_positions_fees(web3_provider, block_end, client)

    positions_growth = {}
    for position_id in positions_fees_end:
        if position_id not in positions_fees_start:
            # Just consider the growth to be the end fees if the position was not present at the start
            positions_growth[position_id] = positions_fees_end[position_id]
            continue

        # Calculate the growth in fees and liquidity
        start_fees = positions_fees_start[position_id]
        end_fees = positions_fees_end[position_id]
        liquidity_growth = end_fees.position_liquidity - start_fees.position_liquidity

        # If liquidity growth is negative, assume fee growths are zero
        if liquidity_growth < 0:
            growth = PositionFeesInfo(
                uncollected_fees_0=0.0,
                uncollected_fees_1=0.0,
                collected_fees_0=0.0,
                collected_fees_1=0.0,
                uncollected_fees_0_token1_equivalent=0.0,
                uncollected_fees_1_token1_equivalent=0.0,
                collected_fees_0_token1_equivalent=0.0,
                collected_fees_1_token1_equivalent=0.0,
                total_fees_token1_equivalent=0.0,
                token0_to_token1_rate=end_fees.token0_to_token1_rate,
                position_liquidity=0.0,
                current_tick=end_fees.current_tick,
                tick_lower=end_fees.tick_lower,
                tick_upper=end_fees.tick_upper,
                owner=end_fees.owner,
                token_0_symbol=end_fees.token_0_symbol,
                token_1_symbol=end_fees.token_1_symbol,
                token_0_decimals=end_fees.token_0_decimals,
                token_1_decimals=end_fees.token_1_decimals,
            )
        else:
            growth = PositionFeesInfo(
                max(0, end_fees.uncollected_fees_0 - start_fees.uncollected_fees_0),
                max(0, end_fees.uncollected_fees_1 - start_fees.uncollected_fees_1),
                max(0, end_fees.collected_fees_0 - start_fees.collected_fees_0),
                max(0, end_fees.collected_fees_1 - start_fees.collected_fees_1),
                max(0, end_fees.uncollected_fees_0_token1_equivalent - start_fees.uncollected_fees_0_token1_equivalent),
                max(0, end_fees.uncollected_fees_1_token1_equivalent - start_fees.uncollected_fees_1_token1_equivalent),
                max(0, end_fees.collected_fees_0_token1_equivalent - start_fees.collected_fees_0_token1_equivalent),
                max(0, end_fees.collected_fees_1_token1_equivalent - start_fees.collected_fees_1_token1_equivalent),
                max(0, end_fees.total_fees_token1_equivalent - start_fees.total_fees_token1_equivalent),
                end_fees.token0_to_token1_rate,
                liquidity_growth,
                end_fees.current_tick,
                end_fees.tick_lower,
                end_fees.tick_upper,
                end_fees.owner,
                end_fees.token_0_symbol,
                end_fees.token_1_symbol,
                end_fees.token_0_decimals,
                end_fees.token_1_decimals,
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
            transaction {
                timestamp
                blockNumber
            }
        }
    }
"""


async def get_all_positions_infos_subgraph(
    block_number: int, client: Client = GQL_CLIENT, batch_size: int = QUERY_BATCH_SIZE
) -> dict[int, PositionFeesInfo]:
    """
    Get all position fees at a specific block, handling pagination automatically.

    Args:
        block_number: The block number to query
        client: The GraphQL client to use
        batch_size: Number of positions to fetch per request (default: 1000)

    Returns:
        Dictionary mapping position IDs to PositionFeesInfo objects for all positions
    """
    position_infos = {}
    skip = 0

    while True:
        batch_positions = await get_position_infos_subgraph(
            block_number=block_number, client=client, first=batch_size, skip=skip
        )

        if not batch_positions:
            break

        position_infos.update(batch_positions)

        # If we got fewer positions than requested, we've reached the end
        if len(batch_positions) < batch_size:
            break

        skip += batch_size

    return position_infos


async def collect_fees(web3_provider: AsyncWeb3, token_id, block_number: int) -> tuple[int, int, int]:
    try:
        nft_position_manager = web3_provider.eth.contract(
            address=NFT_POS_MGR_ADDR,
            abi=NFT_POS_ABI,
        )
        fees = await nft_position_manager.functions.collect(
            (
                token_id,
                NFT_POS_MGR_ADDR,
                2**128 - 1,
                2**128 - 1,
            )
        ).call(block_identifier=block_number)

        # decode the response
        amount0_collected = fees[0]
        amount1_collected = fees[1]
    except Exception:
        return token_id, 0, 0
    else:
        return token_id, amount0_collected, amount1_collected


# TODO(uniswap_v3_lp): split this more apporpriately into seperate functions?
async def get_all_positions_fees(
    web3_provider: AsyncWeb3, block_identifier: BlockIdentifier, client: Client = GQL_CLIENT
) -> dict[int, PositionFeesInfo]:
    """
    Get uncollected fees for all positions at a specific block.
    This is done by static calling the collect() function of the NonfungiblePositionManager contract.
    """
    position_infos = await get_all_positions_infos_subgraph(block_identifier, client)
    token_ids = list(position_infos.keys())

    # create ascynio tasks and gather them for all token IDs to call collect_fees, and place results in a dictionary
    tasks = [collect_fees(web3_provider, token_id, block_identifier) for token_id in token_ids]
    results = await asyncio.gather(*tasks)
    uncollected_fees = {token_id: (amount0, amount1) for token_id, amount0, amount1 in results}

    # merge the *adjusted* uncollected fees with the position infos as their uncollected_fees_0 and uncollected_fees_1
    positions_fees = {}
    for token_id, (amount0, amount1) in uncollected_fees.items():
        position_info = position_infos[token_id]
        token0_to_token1_rate = position_info.token0_to_token1_rate
        positions_fees[token_id] = copy(position_info)
        positions_fees[token_id].uncollected_fees_0 = amount0 / math.pow(10, position_info.token_0_decimals)
        positions_fees[token_id].uncollected_fees_1 = amount1 / math.pow(10, position_info.token_1_decimals)
        positions_fees[token_id].uncollected_fees_0_token1_equivalent = (
            positions_fees[token_id].uncollected_fees_0 * token0_to_token1_rate
        )
        positions_fees[token_id].uncollected_fees_1_token1_equivalent = positions_fees[token_id].uncollected_fees_1
        positions_fees[token_id].total_fees_token1_equivalent = (
            positions_fees[token_id].uncollected_fees_0_token1_equivalent
            + positions_fees[token_id].uncollected_fees_1_token1_equivalent
            + positions_fees[token_id].collected_fees_0_token1_equivalent
            + positions_fees[token_id].collected_fees_1_token1_equivalent
        )

    return positions_fees


# function to display position fee growth information in a table format
def display_position_fees_growth(positions_growth: dict[int, PositionFeesInfo]) -> None:
    """
    Display position fees growth in a table format.

    Args:
        positions_growth: Dictionary mapping position IDs to PositionFeesInfo objects with growth data
    """
    table = BeautifulTable()
    table.column_headers = [
        "Position ID",
        "Uncollected Fees 0 Growth",
        "Uncollected Fees 1 Growth",
        "Collected Fees 0 Growth",
        "Collected Fees 1 Growth",
        # Token 1 equivalent growths
        "Total Fees Growth (Token1)",
    ]

    for position_id, fees in positions_growth.items():
        table.append_row(
            [
                position_id,
                f"{fees.uncollected_fees_0:.6f}",
                f"{fees.uncollected_fees_1:.6f}",
                f"{fees.collected_fees_0:.6f}",
                f"{fees.collected_fees_1:.6f}",
                f"{fees.total_fees_token1_equivalent:.6f}",
            ]
        )

    print(table)
