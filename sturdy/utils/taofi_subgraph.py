# ruff: noqa: RUF003 (ambiguous-unicode-character-comment) - for the equations :)
import asyncio
import json
import math
from copy import copy
from dataclasses import dataclass
from pathlib import Path

import bittensor as bt
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

BURNS_QUERY = """
    query GetBurns($timestampStart: BigInt, $first: Int = 1000, $skip: Int = 0) {
        burns(
            where: {timestamp_gte: $timestampStart}
            first: $first
            skip: $skip
            orderBy: timestamp
            orderDirection: desc
        ) {
            origin
            timestamp
            amount0
            amount1
            tickLower
            tickUpper
            pool {
                token0 {
                    decimals
                }
                token1 {
                    decimals
                }
            }
        }
    }
"""


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


async def get_burns_for_timeframe(
    timestamp_start: int, client: Client = GQL_CLIENT, batch_size: int = QUERY_BATCH_SIZE
) -> list[dict]:
    """
    Get all burn events for the given timeframe.

    Args:
        timestamp_start: Start timestamp to query burns from
        client: The GraphQL client to use
        batch_size: Number of burns to fetch per request

    Returns:
        List of burn events with normalized amounts
    """
    all_burns = []
    skip = 0

    while True:
        data = await client.execute_async(
            gql(BURNS_QUERY), variable_values={"timestampStart": timestamp_start, "first": batch_size, "skip": skip}
        )

        burns = data["burns"]
        if not burns:
            break

        for burn in burns:
            burn_data = {
                "origin": burn["origin"].lower(),
                "tickLower": int(burn["tickLower"]),
                "tickUpper": int(burn["tickUpper"]),
                "amount0": float(burn["amount0"]),
                "amount1": float(burn["amount1"]),
                "timestamp": int(burn["timestamp"]),
            }
            all_burns.append(burn_data)

        # If we got fewer burns than requested, we've reached the end
        if len(burns) < batch_size:
            break

        skip += batch_size

    return all_burns


def match_burns_to_positions(position_infos: dict[int, PositionFeesInfo], burns: list[dict]) -> dict[int, tuple[float, float]]:
    """
    Match burn events to position IDs based on owner, tickLower, and tickUpper.

    Args:
        position_infos: Dictionary of position IDs to PositionFeesInfo
        burns: List of burn events

    Returns:
        Dictionary mapping position IDs to (total_burnt_amount0, total_burnt_amount1)
    """
    burns_by_position = {}

    burns_lookup = {}
    for burn in burns:
        key = (burn["origin"], burn["tickLower"], burn["tickUpper"])
        if key not in burns_lookup:
            burns_lookup[key] = []
        burns_lookup[key].append(burn)

    # Match positions to burns
    for position_id, position_info in position_infos.items():
        position_key = (
            position_info.owner.lower(),
            position_info.tick_lower,
            position_info.tick_upper,
        )

        if position_key in burns_lookup:
            total_burnt_0 = 0.0
            total_burnt_1 = 0.0

            for burn in burns_lookup[position_key]:
                total_burnt_0 += burn["amount0"]
                total_burnt_1 += burn["amount1"]

            burns_by_position[position_id] = (total_burnt_0, total_burnt_1)

    return burns_by_position


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

    return positions_fees


# use this to calculate the uncalculated fees, liuqidity, etc. growth from starting block to end block
async def calculate_fee_growth(
    web3_provider: AsyncWeb3,
    block_start: int,
    block_end: int,
    client: Client = GQL_CLIENT,
    subtract_burns_from_timestamp: int | None = None,
) -> tuple[dict[int, PositionFeesInfo], dict[int, PositionFeesInfo], dict[int, PositionFeesInfo]]:
    """
    Calculate the fee growth for positions between two blocks.

    Args:
        web3_provider: Web3 provider for blockchain calls
        block_start: Starting block number
        block_end: Ending block number
        client: The GraphQL client to use
        subtract_burns_from_timestamp: If provided, subtract burn amounts from this timestamp onwards

    Returns:
        Tuple of (start_positions, end_positions, growth_positions)
    """
    positions_fees_start = await get_all_positions_fees(web3_provider, block_start, client, subtract_burns_from_timestamp)
    positions_fees_end = await get_all_positions_fees(web3_provider, block_end, client, subtract_burns_from_timestamp)

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
    web3_provider: AsyncWeb3,
    block_identifier: BlockIdentifier,
    client: Client = GQL_CLIENT,
    subtract_burns_from_timestamp: int | None = None,
) -> dict[int, PositionFeesInfo]:
    """
    This function retrieves fee information for all Uniswap V3 positions by static calling
    the collect() function of the NonfungiblePositionManager contract. It handles the edge
    case where burnt position NFTs have their deposited liquidity incorrectly counted as
    uncollected fees by the Uniswap V3 core contract.

    When a position NFT gets burnt, the deposited liquidity associated with the position
    gets considered as uncollected fees (see Uniswap V3 core contract's burn() function).
    This shouldn't be considered as fees in our calculation, because it's really just the
    deposited liquidity for the position. This function optionally subtracts "burn" amounts
    from the specified timestamp onwards to correct for this behavior.

    Args:
        web3_provider: Web3 provider for blockchain calls
        block_identifier: Block to query at
        client: GraphQL client
        subtract_burns_from_timestamp: If provided, subtract "burn" amounts from this timestamp onwards
    """
    position_infos = await get_all_positions_infos_subgraph(block_identifier, client)
    token_ids = list(position_infos.keys())

    # Get burn events if timestamp provided
    burns_by_position = {}
    if subtract_burns_from_timestamp is not None:
        burns = await get_burns_for_timeframe(subtract_burns_from_timestamp, client)
        burns_by_position = match_burns_to_positions(position_infos, burns)

    bt.logging.debug(f"Found {len(position_infos)} positions at block {block_identifier}.")
    bt.logging.debug(f"Found {len(burns_by_position)} burns matching positions.")

    # create async tasks and gather them for all token IDs to call collect_fees, and place results in a dictionary
    tasks = [collect_fees(web3_provider, token_id, block_identifier) for token_id in token_ids]
    results = await asyncio.gather(*tasks)
    uncollected_fees = {token_id: (amount0, amount1) for token_id, amount0, amount1 in results}

    # merge the *adjusted* uncollected fees with the position infos as their uncollected_fees_0 and uncollected_fees_1
    positions_fees = {}
    for token_id, (amount0, amount1) in uncollected_fees.items():
        position_info = position_infos[token_id]
        token0_to_token1_rate = position_info.token0_to_token1_rate
        positions_fees[token_id] = copy(position_info)

        # Adjust uncollected fees for decimals
        uncollected_fees_0_adjusted = amount0 / math.pow(10, position_info.token_0_decimals)
        uncollected_fees_1_adjusted = amount1 / math.pow(10, position_info.token_1_decimals)

        # Subtract burns if position had burn events
        if token_id in burns_by_position:
            burnt_amount0, burnt_amount1 = burns_by_position[token_id]
            uncollected_fees_0_adjusted = max(0, uncollected_fees_0_adjusted - burnt_amount0)
            uncollected_fees_1_adjusted = max(0, uncollected_fees_1_adjusted - burnt_amount1)

        positions_fees[token_id].uncollected_fees_0 = uncollected_fees_0_adjusted
        positions_fees[token_id].uncollected_fees_1 = uncollected_fees_1_adjusted
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
