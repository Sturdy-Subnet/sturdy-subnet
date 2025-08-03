import asyncio
import json
from argparse import ArgumentParser

import bittensor as bt

from sturdy.protocol import MINER_TYPE


def add_args(parser: ArgumentParser) -> None:
    """
    Adds miner specific arguments to the parser.
    """
    # Add arguments for miner-specific configurations.
    parser.add_argument(
        "--miner-type",
        type=lambda x: MINER_TYPE[x] if hasattr(MINER_TYPE, x) else MINER_TYPE(x),
        choices=list(MINER_TYPE),
        default=MINER_TYPE.UNISWAP_V3_LP,
        help="Type of miner you want to advertise yourself as. Default is UNISWAP_V3_LP.",
    )
    parser.add_argument(
        "--signature",
        type=str,
        help="Only needed if for LP miners. A signature of miner's hotkey address, signed EVM wallet's private key.",
        default=None,
    )
    parser.add_argument("--netuid", type=int, help="The netuid to push the signed commitment to.", default=10)


async def main() -> None:
    bt.info()
    bt.debug()
    parser = ArgumentParser(description="Miner commitment script.")

    bt.wallet.add_args(parser)
    bt.subtensor.add_args(parser)
    bt.logging.add_args(parser)
    add_args(parser)
    config = bt.config(parser)

    # data to commit
    data = {
        "miner_type": config.miner_type.value,
        "signature": config.signature,
    }
    # dump str json
    data_str = json.dumps(data)

    wallet = bt.wallet(config=config)
    subtensor = bt.AsyncSubtensor(config=config)

    success = await subtensor.commit(netuid=config.netuid, data=data_str, wallet=wallet)
    if success:
        bt.logging.info(f"Successfully committed miner data: {data_str}")
    else:
        bt.logging.error("Failed to commit miner data.")


if __name__ == "__main__":
    asyncio.run(main())
