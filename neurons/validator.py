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
import time
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
from sturdy.constants import DB_DIR, ORGANIC_SCORING_PERIOD

# Bittensor Validator Template:
from sturdy.pools import PoolFactory
from sturdy.protocol import (
    REQUEST_TYPES,
    AllocateAssets,
    AllocateAssetsRequest,
    AllocateAssetsResponse,
    GetAllocationResponse,
    RequestInfoResponse,
)
from sturdy.utils.misc import get_synapse_from_body

# api key db
from sturdy.validator import forward, query_and_score_miners, sql


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

    def __init__(self, config=None) -> None:
        super().__init__(config=config)
        bt.logging.info("load_state()")
        self.load_state()
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
    if request.url.path in ["/docs", "/openapi.json", "/favicon.ico", "/redoc"]:
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

    credits_required = 1  # TODO: make this non-constant in the future???? (i.e. dependent on number of pools)????

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
          "assets_and_pools": {
            "total_assets": 1000000000000000000,
            "pools": {
              ...
              "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227": {
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

    new_pools = {}
    for uid, pool in pools.items():
        new_pool = PoolFactory.create_pool(
            pool_type=pool.pool_type,
            web3_provider=core_validator.w3,  # type: ignore[]
            user_address=(
                pool.user_address if pool.user_address != ADDRESS_ZERO else synapse.user_address
            ),  # TODO: is there a cleaner way to do this?
            contract_address=pool.contract_address,
        )
        new_pools[uid] = new_pool

    synapse.assets_and_pools["pools"] = new_pools

    bt.logging.info("Querying miners...")
    axon_times, result = await query_and_score_miners(
        core_validator,
        assets_and_pools=synapse.assets_and_pools,
        request_type=synapse.request_type,
        user_address=synapse.user_address,
    )
    request_uuid = uid = str(uuid.uuid4()).replace("-", "")

    to_ret = dict(list(result.items())[: body.num_allocs])
    ret = AllocateAssetsResponse(allocations=to_ret, request_uuid=request_uuid)
    to_log = AllocateAssetsResponse(allocations=to_ret, request_uuid=request_uuid)

    metadata = {}
    pools = synapse.assets_and_pools["pools"]

    for contract_addr, pool in pools.items():
        pool.sync(core_validator.w3)
        metadata[contract_addr] = pool._share_price

    with sql.get_db_connection() as conn:
        sql.log_allocations(
            conn,
            to_log.request_uuid,
            synapse.assets_and_pools,
            metadata,
            to_log.allocations,
            axon_times,
            REQUEST_TYPES.ORGANIC,
            ORGANIC_SCORING_PERIOD,
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


# Function to run the main loop
async def run_main_loop() -> None:
    try:
        core_validator.run_in_background_thread()  # type: ignore[]
    except KeyboardInterrupt:
        bt.logging.info("Keyboard interrupt received, exiting...")


# Function to run the Uvicorn server
async def run_uvicorn_server() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=core_validator.config.api_port, loop="asyncio")  # noqa: S104 # type: ignore[]
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    global core_validator  # noqa: PLW0603
    core_validator = Validator()
    if not (core_validator.config.synthetic or core_validator.config.organic):
        bt.logging.error(
            "You did not select a validator type to run! Ensure you select to run either a synthetic or organic validator. \
             Shutting down...",
        )
        return

    bt.logging.info(f"organic: {core_validator.config.organic}")

    if core_validator.config.organic:
        await asyncio.gather(run_uvicorn_server(), run_main_loop())
    else:
        with core_validator:
            while True:
                bt.logging.debug("Running synthetic vali...")
                time.sleep(10)  # noqa: ASYNC251


def start() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    start()
