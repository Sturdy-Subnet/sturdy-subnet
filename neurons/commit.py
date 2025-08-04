import asyncio
import json
from argparse import ArgumentParser
from dataclasses import asdict, dataclass

import bittensor as bt

from sturdy.protocol import MINER_TYPE


@dataclass
class AssociateEVMKeyParams:
    netuid: int
    hotkey: str
    evm_key: str
    block_number: int
    signature: str


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
        "--evm-address",
        type=str,
        help="The EVM address to associate with the hotkey. This is required for LP miners.",
        default=None,
    )
    parser.add_argument(
        "--signature",
        type=str,
        help="Only needed if for LP miners. A signature of miner's hotkey address, signed EVM wallet's private key.",
        default=None,
    )
    parser.add_argument(
        "--block-number",
        type=int,
        help="The block number which the user specified as a nonce when signing the message.",
        default=None,
    )
    parser.add_argument("--netuid", type=int, help="The netuid to push the signed commitment to.", default=10)


async def associate_evm_key_with_hotkey(
    subtensor: bt.AsyncSubtensor, wallet: bt.Wallet, netuid: int, evm_addr: str, block_num: int, signature: str
) -> bool:
    substrate = subtensor.substrate
    call_params = AssociateEVMKeyParams(
        netuid=netuid,
        hotkey=wallet.hotkey.ss58_address,
        evm_key=evm_addr,
        block_number=block_num,
        signature=signature,
    )

    call = await substrate.compose_call(
        call_module="SubtensorModule",
        call_function="associate_evm_key",
        call_params=asdict(call_params),
    )

    success, msg = await subtensor.sign_and_send_extrinsic(call=call, wallet=wallet, sign_with="hotkey")

    if not success:
        bt.logging.error(f"Failed to associate EVM key with hotkey: {msg}")
        return False

    bt.logging.info(f"Successfully associated EVM key {evm_addr} with hotkey for netuid {netuid}.")
    return True


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
    }

    data_str = json.dumps(data)
    bt.logging.info(f"Committing miner type: {data_str}")

    wallet = bt.wallet(config=config)
    subtensor = bt.AsyncSubtensor(config=config)

    success = await subtensor.commit(netuid=config.netuid, data=data_str, wallet=wallet)
    if success:
        bt.logging.info(f"Successfully committed miner type: {data_str}")
    else:
        bt.logging.error("Failed to commit miner type.")

    # if signature, block_number, and evm_address are provided, associate EVM key with hotkey
    if config.signature and config.block_number is not None and config.evm_address:
        bt.logging.info("Associating EVM key with hotkey...")
        success = await associate_evm_key_with_hotkey(
            subtensor=subtensor,
            wallet=wallet,
            netuid=config.netuid,
            evm_addr=config.evm_address,
            block_num=config.block_number,
            signature=config.signature,
        )
        if not success:
            bt.logging.error("Failed to associate EVM key with hotkey.")
    else:
        bt.logging.warning("Signature or block number or EVM address not provided. Skipping EVM key association.")


if __name__ == "__main__":
    asyncio.run(main())
