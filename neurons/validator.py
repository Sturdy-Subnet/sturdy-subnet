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
import fastapi
import threading
import uvicorn

# Bittensor Validator Template:
from sturdy.validator import forward, query_and_score_miners
from sturdy.utils.misc import get_synapse_from_body
from sturdy.protocol import AllocateAssets, AllocateAssetsRequest, AllocateAssetsResponse

# import base validator class which takes care of most of the boilerplate
from sturdy.base.validator import BaseValidatorNeuron

class Validator(BaseValidatorNeuron):
    """
    Your validator neuron class. You should use this class to define your validator's behavior. In particular, you should replace the forward function with your own logic.

    This class inherits from the BaseValidatorNeuron class, which in turn inherits from BaseNeuron. The BaseNeuron class takes care of routine tasks such as setting up wallet, subtensor, metagraph, logging directory, parsing config, etc. You can override any of the methods in BaseNeuron if you need to customize the behavior.

    This class provides reasonable default behavior for a validator such as keeping a moving average of the scores of the miners and using them to set weights at the end of each epoch. Additionally, the scores are reset for new hotkeys at the end of each epoch.
    """

    def __init__(self, config=None):
        super(Validator, self).__init__(config=config)
        bt.logging.info("load_state()")
        self.load_state()
        self.uid_to_response = {}


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
app = fastapi.FastAPI(debug=False)

@app.get("/test")
async def test():
    return {"Hello": "World"}

@app.get("/vali")
async def vali(validator=fastapi.Depends(lambda: core_validator)):
    ret = {"step": validator.step, "config": validator.config}
    return ret

@app.post("/allocate")
async def allocate(body: AllocateAssetsRequest, validator=fastapi.Depends(lambda: core_validator)) -> AllocateAssetsResponse:
    synapse = get_synapse_from_body(body=body, synapse_model=AllocateAssets)
    # TODO: surely we can make this cleaner right?

    api_loop = asyncio.get_running_loop()
    core_loop = core_validator.loop
    assert api_loop != core_loop
    # asyncio.set_event_loop(core_loop)
    result = core_loop.run_until_complete(query_and_score_miners(core_validator, synapse.assets_and_pools))
    # asyncio.set_event_loop(api_loop)
    ret = AllocateAssetsResponse(allocations=result)    
    return ret

# Function to run the main loop
def run_main_loop():
    try:
        with core_validator:
            while True:
                # if asyncio.get_running_loop() 
                time.sleep(10)
    except KeyboardInterrupt:
        print("Keyboard interrupt received, exiting...")

# Function to run the Uvicorn server
def run_uvicorn_server():
    if core_validator.config.api_port is not None:
        uvicorn.run(app, host="0.0.0.0", port=core_validator.config.api_port, loop="asyncio")

async def create_validator():
    global core_validator
    core_validator = Validator()

# The main function parses the configuration and runs the validator.
# if __name__ == "__main__":
async def main():
    await create_validator()
    if not (core_validator.config.synthetic or core_validator.config.organic):
        bt.logging.error("You did not select a validator type to run! Ensure you select to run either a synthetic or organic validator. Shutting down...")
        exit()
    bt.logging.info(f"organic: {core_validator.config.organic}")
    if core_validator.config.organic:
        # Run the Uvicorn server and the main loop in separate threads
        uvicorn_thread = threading.Thread(target=run_uvicorn_server)
        main_loop_thread = threading.Thread(target=run_main_loop)

        uvicorn_thread.start()
        main_loop_thread.start()

        uvicorn_thread.join()
        main_loop_thread.join()
    else:
        run_main_loop()

if __name__ == "__main__":
    asyncio.run(main())