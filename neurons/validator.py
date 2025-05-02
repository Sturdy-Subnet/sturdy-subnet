# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 Syeam Bin Abdullah

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


import asyncio
import uuid
from typing import Any

# Bittensor
import bittensor as bt
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_429_TOO_MANY_REQUESTS,
)
from web3.constants import ADDRESS_ZERO

# import base validator class which takes care of most of the boilerplate
from sturdy.base.validator import BaseValidatorNeuron
from sturdy.constants import DB_DIR, MIN_TOTAL_ASSETS_AMOUNT

# Bittensor Validator Template:
from sturdy.pools import POOL_TYPES, PoolFactory
from sturdy.protocol import (
    REQUEST_TYPES,
    AllocateAssets,
    AllocateAssetsRequest,
    AllocateAssetsResponse,
    BTAlphaPoolRequest,
    GetAllocationResponse,
    RequestInfoResponse,
)
from sturdy.providers import POOL_DATA_PROVIDER_TYPE
from sturdy.utils.misc import get_synapse_from_body

# api key db
from sturdy.validator import forward, sql
from sturdy.validator.forward import query_top_n_miners


class Validator(BaseValidatorNeuron):
    """
    Your validator neuron class. You should use this class to define your validator's behavior. In particular, you should
    replace the forward function with your own logic.

    This class inherits from the BaseValidatorNeuron class, which in turn inherits from BaseNeuron. The BaseNeuron class takes
    care of routine tasks such as setting up wallet, subtensor, metagraph, logging directory, parsing config, etc. You can
    override any of the methods in BaseNeuron if you need to customize the behavior.

    This class provides reasonable default behavior for a validator such as keeping a moving average of the scores of the
    miners and using them to set weights at the end of each epoch. Additionally, the scores are reset for new hotkeys at the
    end of each epoch.
    """

    async def _init_async(self, config=None) -> None:
        await super()._init_async(config=config)
        self.uid_to_response = {}

    async def forward(self) -> Any:
        """
        Validator forward pass. Consists of:
        - Generating the query.
        - Querying the miners
        - Getting the responses
        - Rewarding the miners
        - Updating the scores
        """
        bt.logging.debug("forward()")
        return await forward(self)


# API
app = FastAPI(debug=False)


def _get_api_key(request: Request) -> Any:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]

    return auth_header


@app.middleware("http")
async def api_key_validator(request, call_next) -> Response:
    # TODO: getting status works but seeing two "invalid requests" logs afterwards
    if request.url.path in ["/docs", "/openapi.json", "/favicon.ico", "/redoc", "/status"]:
        return await call_next(request)

    api_key = _get_api_key(request)
    if not api_key:
        return JSONResponse(
            status_code=HTTP_400_BAD_REQUEST,
            content={"detail": "API key is missing"},
        )

    with sql.get_db_connection() as conn:
        api_key_info = sql.get_api_key_info(conn, api_key)

    if api_key_info is None:
        return JSONResponse(status_code=HTTP_401_UNAUTHORIZED, content={"detail": "Invalid API key"})

    credits_required = (
        1 if request.url.path != "/api_key_info" else 0
    )  # TODO: make this non-constant in the future???? (i.e. dependent on number of pools)????

    # Now check credits
    if api_key_info[sql.BALANCE] is not None and api_key_info[sql.BALANCE] <= credits_required:
        return JSONResponse(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Insufficient credits - sorry!"},
        )

    # Now check rate limiting
    with sql.get_db_connection() as conn:
        rate_limit_exceeded = sql.rate_limit_exceeded(conn, api_key_info)
        if rate_limit_exceeded:
            return JSONResponse(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded - sorry!"},
            )

    response: Response = await call_next(request)

    bt.logging.debug(f"response: {response}")
    if response.status_code == 200:
        with sql.get_db_connection() as conn:
            sql.update_requests_and_credits(conn, api_key_info, credits_required)
            sql.log_request(conn, api_key_info, request.url.path, credits_required)
            conn.commit()
    return response


# Initialize core_validator outside of the event loop
core_validator = None  # type: ignore[]


@app.get("/vali")
async def vali() -> dict:
    return {"step": core_validator.step, "config": core_validator.config}  # type: ignore[]


@app.get("/status")
async def status() -> dict:
    return {"status": "OK"}


@app.post("/allocate", response_model=AllocateAssetsResponse)
async def allocate(body: AllocateAssetsRequest) -> AllocateAssetsResponse | None:
    """
    Handles allocation requests by creating pools, querying and scoring miners, and returning the allocations.

    Args:
        body (AllocateAssetsRequest): The request body containing the allocation details including the type of request,
                                      user address, and assets and pools information.

    Returns:
        AllocateAssetsResponse: The response containing the allocations and a unique request UUID.

    Example Request JSON Data:
        {
          "request_type": "ORGANIC",
          "user_address": "0xD8f9475A4A1A6812212FD62e80413d496038A89A",
          "pool_data_provider": "ETHEREUM_MAINNET",
          "assets_and_pools": {
            "total_assets": 1000000000000000000,
            "pools": {
              ...
              "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227": {
                "pool_model_disc": "EVM_CHAIN_BASED",
                "pool_type": "STURDY_SILO",
                "contract_address": "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227"
              },
              ...
            }
          }
        }

    Example Response JSON Data:
        {
            "request_uuid": "a8af54a41fa347d7b59570c81fe35492",
            "allocations": {
                ...
                "1": {
                    "apy": 2609043057391825,
                    "allocations": {
                        ...
                        "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227": 250000000000000000,
                        ...
                    }
                },
                ...
            }
        }
    """
    synapse: Any = get_synapse_from_body(body=body, synapse_model=AllocateAssets)
    bt.logging.debug(f"Synapse:\n{synapse}")
    pools: Any = synapse.assets_and_pools["pools"]
    total_assets: int = synapse.assets_and_pools["total_assets"]

    # return error if total assets is less <= 0
    if total_assets <= MIN_TOTAL_ASSETS_AMOUNT:
        raise HTTPException(
            status_code=400,
            detail="Total assets must be greater than 0",
        )

    new_pools = {}
    for uid, pool in pools.items():
        if pool.pool_type == POOL_TYPES.BT_ALPHA:
            new_pool = PoolFactory.create_pool(
                pool_type=pool.pool_type,
                netuid=int(pool.netuid),
                current_amount=int(pool.current_amount),
                pool_data_provider_type=synapse.pool_data_provider,
            )
        else:
            new_pool = PoolFactory.create_pool(
                pool_type=pool.pool_type,
                web3_provider=core_validator.pool_data_providers[synapse.pool_data_provider],  # type: ignore[]
                user_address=(
                    pool.user_address if pool.user_address != ADDRESS_ZERO else synapse.user_address
                ),  # TODO: is there a cleaner way to do this?
                contract_address=pool.contract_address,
            )

        new_pools[uid] = new_pool

    synapse.assets_and_pools["pools"] = new_pools

    bt.logging.info("Querying miners...")

    chain_data_provider = core_validator.pool_data_providers[synapse.pool_data_provider]

    axon_times, result = await query_top_n_miners(
        core_validator,
        n=body.num_allocs,
        assets_and_pools=synapse.assets_and_pools,
        request_type=synapse.request_type,
        user_address=synapse.user_address,
    )

    request_uuid = uid = str(uuid.uuid4()).replace("-", "")

    to_ret = dict(list(result.items())[: body.num_allocs])
    ret = AllocateAssetsResponse(allocations=to_ret, request_uuid=request_uuid)
    to_log = AllocateAssetsResponse(allocations=to_ret, request_uuid=request_uuid)

    pools = synapse.assets_and_pools["pools"]

    metadata = {}

    with sql.get_db_connection() as conn:
        sql.log_allocations(
            conn,
            to_log.request_uuid,
            core_validator.metagraph.hotkeys,
            synapse.assets_and_pools,
            metadata,
            to_log.allocations,
            axon_times,
            REQUEST_TYPES.ORGANIC,
        )

    return ret


@app.get("/get_allocation/", response_model=list[GetAllocationResponse])
async def get_allocations(
    request_uid: str | None = None,
    miner_uid: str | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
    db_dir: str = DB_DIR,
) -> list[dict]:
    with sql.get_db_connection(db_dir) as conn:
        allocations = sql.get_miner_responses(conn, request_uid, miner_uid, from_ts, to_ts)
    if not allocations:
        raise HTTPException(status_code=404, detail="No allocations found")
    return allocations


@app.get("/request_info/", response_model=list[RequestInfoResponse])
async def request_info(
    request_uid: str | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
    db_dir: str = DB_DIR,
) -> list[dict]:
    with sql.get_db_connection(db_dir) as conn:
        info = sql.get_request_info(conn, request_uid, from_ts, to_ts)
    if not info:
        raise HTTPException(status_code=404, detail="No request info found")
    return info


@app.get("/api_key_info")
async def get_api_key_info(
    request: Request,
    db_dir: str = DB_DIR,
) -> dict:
    """
    Get information about the API key used in the request.

    Returns:
        dict: Contains key details including:
            - balance: Remaining credits
            - rate_limit_per_minute: Maximum requests allowed per minute
            - name: Name associated with the key
            - created_at: When the key was created

    Raises:
        HTTPException: If API key is missing or invalid
    """
    api_key = _get_api_key(request)
    if not api_key:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="API key is missing")

    with sql.get_db_connection(db_dir) as conn:
        api_key_info = sql.get_api_key_info(conn, api_key)

    if api_key_info is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    return {
        "balance": api_key_info[sql.BALANCE],
        "rate_limit_per_minute": api_key_info[sql.RATE_LIMIT_PER_MINUTE],
        "name": api_key_info[sql.NAME],
        "created_at": api_key_info[sql.CREATED_AT],
    }


@app.post("/allocate_bt", response_model=AllocateAssetsResponse)
async def allocate_bt(body: BTAlphaPoolRequest) -> AllocateAssetsResponse | None:
    """
    Simplified endpoint for Bittensor alpha token pool allocations.

    Args:
        body (BTAlphaPoolRequest): Contains:
            - netuids: list of subnet UIDs
            - total_assets: Total assets to allocate (in RAO)
            - num_allocs: Number of miner allocations to receive

    Returns:
        AllocateAssetsResponse: The allocations response
    """
    # Return error if total assets is <= 0
    if body.total_assets <= MIN_TOTAL_ASSETS_AMOUNT:
        raise HTTPException(status_code=400, detail="Total assets must be greater than 0")

    # Construct pools dictionary
    pools = {}
    total_amount_alloced = 0
    for netuid in body.netuids:
        if netuid == 0:
            raise HTTPException(
                status_code=400, detail="Invalid subnet netuid - root (subnet 0) does not have an alpha token pool"
            )
        current_allocation = body.current_allocations.get(netuid, 0)
        pool = PoolFactory.create_pool(
            pool_type=POOL_TYPES.BT_ALPHA,
            netuid=netuid,
            current_amount=current_allocation,
            pool_data_provider_type=POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET,
        )
        total_amount_alloced += pool.current_amount
        pools[str(netuid)] = pool

    # checked that total assets is greater than the sum of current allocations
    if body.total_assets <= total_amount_alloced:
        raise HTTPException(
            status_code=400,
            detail="Total assets must be greater than the sum of current allocations",
        )

    # Construct the assets and pools structure
    assets_and_pools = {"pools": pools, "total_assets": body.total_assets}

    bt.logging.info("Querying miners...")

    axon_times, result = await query_top_n_miners(
        core_validator,
        n=body.num_allocs,
        assets_and_pools=assets_and_pools,
        request_type=REQUEST_TYPES.ORGANIC,
        user_address=ADDRESS_ZERO,
    )

    request_uuid = str(uuid.uuid4()).replace("-", "")
    to_ret = dict(list(result.items())[: body.num_allocs])

    ret = AllocateAssetsResponse(allocations=to_ret, request_uuid=request_uuid)

    with sql.get_db_connection() as conn:
        sql.log_allocations(
            conn,
            ret.request_uuid,
            core_validator.metagraph.hotkeys,
            assets_and_pools,
            {},  # Empty metadata
            ret.allocations,
            axon_times,
            REQUEST_TYPES.ORGANIC,
            None,  # No scoring period
        )

    return ret


async def main() -> None:
    global core_validator  # noqa: PLW0603
    core_validator = await Validator.create()

    try:
        config = uvicorn.Config(app, host="0.0.0.0", port=core_validator.config.api_port)  # noqa: S104
        server = uvicorn.Server(config)

        async with core_validator:
            await server.serve()

    except KeyboardInterrupt:
        bt.logging.info("Shutting down...")


def start() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    start()
