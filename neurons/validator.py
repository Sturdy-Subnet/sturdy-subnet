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

# Bittensor
import bittensor as bt

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

    async def _init_async(self, config=None) -> None:
        await super()._init_async(config=config)


async def main() -> None:
    global core_validator  # noqa: PLW0603
    core_validator = await Validator.create()

    try:
        async with core_validator:
            while True:
                bt.logging.info("Validator running...")
                # sleep for a bit till we print something
                # TODO: make this a constant?
                await asyncio.sleep(300)

    except KeyboardInterrupt:
        bt.logging.info("Shutting down...")


def start() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    start()
