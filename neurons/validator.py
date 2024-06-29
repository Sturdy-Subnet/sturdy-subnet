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


import time
import asyncio

# Bittensor
import bittensor as bt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_429_TOO_MANY_REQUESTS,
)
import uvicorn

# api key db
from db import sql

# Bittensor Validator Template:
from sturdy.pools import POOL_TYPES, PoolFactory
from sturdy.validator import forward, query_and_score_miners
from sturdy.utils.misc import get_synapse_from_body
from sturdy.protocol import (
    AllocateAssets,
    AllocateAssetsRequest,
    AllocateAssetsResponse,
)
from sturdy.validator.simulator import Simulator

# import base validator class which takes care of most of the boilerplate
from sturdy.base.validator import BaseValidatorNeuron


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

    def __init__(self, config=None):
        super(Validator, self).__init__(config=config)
        bt.logging.info("load_state()")
        self.load_state()
        self.uid_to_response = {}
        self.simulator = Simulator()

    async def forward(self):
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


def _get_api_key(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    else:
        return auth_header


@app.middleware("http")
async def api_key_validator(request, call_next):
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
        return JSONResponse(
            status_code=HTTP_401_UNAUTHORIZED, content={"detail": "Invalid API key"}
        )
    # endpoint = request.url.path.split("/")[-1]
    # credits_required = ENDPOINT_TO_CREDITS_USED.get(endpoint, 1)
    credits_required = 1  # TODO: make this non-constant in the future???? (i.e. dependent on number of pools)????

    # Now check credits
    if (
        api_key_info[sql.BALANCE] is not None
        and api_key_info[sql.BALANCE] <= credits_required
    ):
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
core_validator = None


@app.get("/vali")
async def vali():
    ret = {"step": core_validator.step, "config": core_validator.config}
    return ret


@app.get("/status")
async def status():
    ret = {"status": "OK"}
    return ret


@app.post("/allocate", response_model=AllocateAssetsResponse)
async def allocate(body: AllocateAssetsRequest):
    synapse = get_synapse_from_body(body=body, synapse_model=AllocateAssets)
    bt.logging.debug(f"Synapse:\n{synapse}")
    pools = synapse.assets_and_pools["pools"]
    if synapse.type == POOL_TYPES.DEFAULT:
        bt.logging.debug("converting to BasePool...")
        new_pools = {
            uid: PoolFactory.create_pool(
                pool_type=synapse.type,
                pool_id=pool.pool_id,
                base_rate=pool.base_rate,
                base_slope=pool.base_slope,
                kink_slope=pool.kink_slope,
                optimal_util_rate=pool.optimal_util_rate,
                borrow_amount=pool.borrow_amount,
                reserve_size=pool.reserve_size,
            )
            for uid, pool in pools.items()
        }
        synapse.assets_and_pools["pools"] = new_pools
    else:
        bt.logging.debug("converting to chain based pool...")
        new_pools = {
            uid: PoolFactory.create_pool(
                pool_type=synapse.type,
                web3_provider=core_validator.w3,
                pool_id=pool.pool_id,
                user_address=pool.user_address,  # TODO: is there a cleaner way to do this?
                contract_address=pool.contract_address,
            )
            for uid, pool in pools.items()
        }
        synapse.assets_and_pools["pools"] = new_pools

    result = await query_and_score_miners(
        core_validator,
        pool_type=synapse.type,
        assets_and_pools=synapse.assets_and_pools,
        organic=True,
    )
    ret = AllocateAssetsResponse(allocations=result)
    return ret


# Function to run the main loop
async def run_main_loop():
    try:
        core_validator.run_in_background_thread()
    except KeyboardInterrupt:
        print("Keyboard interrupt received, exiting...")


# Function to run the Uvicorn server
async def run_uvicorn_server():
    config = uvicorn.Config(
        app, host="0.0.0.0", port=core_validator.config.api_port, loop="asyncio"
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    global core_validator
    core_validator = Validator()
    if not (core_validator.config.synthetic or core_validator.config.organic):
        bt.logging.error(
            "You did not select a validator type to run! Ensure you select to run either a synthetic or organic validator. \
             Shutting down..."
        )
        return

    bt.logging.info(f"organic: {core_validator.config.organic}")

    if core_validator.config.organic:
        await asyncio.gather(run_uvicorn_server(), run_main_loop())
    else:
        # await run_main_loop()
        with core_validator:
            while True:
                bt.logging.debug("Running synthetic vali...")
                time.sleep(10)


def start():
    asyncio.run(main())


if __name__ == "__main__":
    start()
