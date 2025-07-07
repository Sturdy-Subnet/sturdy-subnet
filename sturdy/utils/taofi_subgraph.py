from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

from sturdy.constants import TAOFI_GQL_URL

TRANSPORT = AIOHTTPTransport(url=TAOFI_GQL_URL)
GQL_CLIENT = Client(transport=TRANSPORT, fetch_schema_from_transport=True)


async def fetch_uniswap_pos_and_swaps(since: int, pool_address: str, client=GQL_CLIENT) -> tuple[dict, dict]:
    print(f"Fetching Uniswap V3 pool swaps since (UNIX: {since}) for pool {pool_address}")

    # Pool address has to be in lowercase because the subgraph wants it that way :/
    pool_addr_lower = pool_address.lower()
    # TODO(uniswap_v3_lp): set "first" to a sensible value, or paginate if needed
    query = gql(
        f"""
      {{
      positions(first: 1000) {{
        id
        tickLower {{
        tickIdx
        }}
        tickUpper {{
        tickIdx
        }}
        pool {{
        id
        tick
        }}
        liquidity
        owner
      }}
      swaps(
        where: {{
        pool: "{pool_addr_lower}",
        timestamp_gt: {since}
        }},
        orderBy: timestamp,
        orderDirection: desc
      ) {{
        timestamp
        amountUSD
        tick
      }}
      pool(id: "{pool_addr_lower}") {{
        id
        tick
      }}
      }}
      """
    )

    response = await client.execute_async(query)

    swaps = response.get("swaps", [])
    positions = {int(position["id"]): position for position in response.get("positions", [])}
    current_tick = int(response.get("pool", {}).get("tick", 0))

    return positions, swaps, current_tick
