from datetime import datetime

from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

from sturdy.constants import TAOFI_GQL_URL

TRANSPORT = AIOHTTPTransport(url=TAOFI_GQL_URL)
GQL_CLIENT = Client(transport=TRANSPORT, fetch_schema_from_transport=True)


async def get_uniswap_v3_pool_swaps(since: datetime, pool_address: str, client=GQL_CLIENT) -> dict:
    # Convert datetime to UNIX timestamp (integer)
    timestamp_unix = int(since.timestamp())
    print(f"Fetching Uniswap V3 pool swaps since {since} (UNIX: {timestamp_unix}) for pool {pool_address}")

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
