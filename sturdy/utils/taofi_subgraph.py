from datetime import datetime

from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

# TODO(uniswap_v3_lp): Make the url a constant or a configuration parameter
# This is the Uniswap V3 subgraph URL on Taofi
TRANSPORT = AIOHTTPTransport(url="https://subgraph.taofi.com/subgraphs/name/uniswap/v3")
GQL_CLIENT = Client(transport=TRANSPORT, fetch_schema_from_transport=True)


async def get_uniswap_v3_pool_swaps(since: datetime, pool_address: str, client=GQL_CLIENT) -> dict:
    # Convert datetime to UNIX timestamp (integer)
    timestamp_unix = int(since.timestamp())

    # Create the GraphQL query string with the dynamic timestamp
    query = gql(
        f"""
        {{
          swaps(
            where: {{
              pool: "{pool_address}",
              timestamp_gt: {timestamp_unix}
            }},
            orderBy: timestamp,
            orderDirection: desc
          ) {{
            timestamp
            amountUSD
            tick
            sqrtPriceX96
            transaction {{
              blockNumber
            }}
          }}
        }}
        """
    )

    return await client.execute_async(query)
