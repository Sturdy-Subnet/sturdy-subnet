import asyncio
import json
import os
from argparse import ArgumentParser

import bittensor as bt
import dotenv
from bittensor import Keypair
from bittensor.core.async_subtensor import get_async_subtensor
from eth_account import Account
from eth_account.messages import SignableMessage, encode_defunct
from web3 import Web3

from sturdy.protocol import MINER_TYPE
from sturdy.utils.association import associate_evm_key_with_hotkey

dotenv.load_dotenv()


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
        "--block-number",
        type=int,
        help="The block number which the user specified as a nonce when signing the message.",
        default=None,
    )
    parser.add_argument("--netuid", type=int, help="The netuid to push the signed commitment to.", default=10)


def get_signature_for_evm_key_association(hotkey: str, block: int) -> tuple[str, str]:
    """
    Generates a signature for associating an EVM key with a hotkey.

    Args:
        hotkey (str): The hotkey address to associate with the EVM key.
        block (int): The block number to use as a nonce for the signature.

    Returns:
        str: The generated signature.
    """
    bt.logging.info("Generating signature for EVM key association...")
    # TODO(commitment): This is a temporary solution to get the private key from an environment variable.
    # In the future we'd likely want to make this entire process more streamlined - i.e. through a frontend interface
    private_key = os.getenv("UNISWAP_POS_OWNER_KEY")

    block_number_bytes = block.to_bytes(8, byteorder="little")
    block_number_hash = Web3.keccak(block_number_bytes)

    hotkey_bytes = Keypair(ss58_address=hotkey).public_key
    bt.logging.info(f"Hotkey public key bytes: {hotkey_bytes.hex()}")
    message_to_sign_bytes = hotkey_bytes + block_number_hash

    signable_message = encode_defunct(primitive=message_to_sign_bytes)
    account = Account.from_key(private_key)
    signed_message: SignableMessage = account.sign_message(signable_message)
    signed_message = "0x" + signed_message.signature.hex()

    bt.logging.info(f"Message to sign (hex): 0x{message_to_sign_bytes.hex()}")
    bt.logging.info(f"Signature (hex): {signed_message}")
    bt.logging.info(f"EVM address: {account.address}")
    bt.logging.info(f"Hotkey address: {hotkey}")
    bt.logging.info(f"Block number: {block}")

    return signed_message, account.address


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
    bt.logging.info(f"Committing miner type: {data_str}...")

    wallet = bt.wallet(config=config)
    subtensor = await get_async_subtensor(config=config)

    success = await subtensor.commit(netuid=config.netuid, data=data_str, wallet=wallet)
    if success:
        bt.logging.info(f"Successfully committed miner type: {data_str}")
    else:
        bt.logging.error("Failed to commit miner type.")

    # if signature, and evm address are provided, associate the EVM key with the hotkey
    if os.getenv("UNISWAP_POS_OWNER_KEY") and config.miner_type == MINER_TYPE.UNISWAP_V3_LP:
        bt.logging.info("Getting block number to use as nonce...")
        try:
            block_number = await subtensor.get_current_block()
        except Exception as e:
            bt.logging.error(f"Failed to get current block number: {e}")
            return
        bt.logging.info(f"Block number to use as nonce: {block_number}")
        bt.logging.info(f"Getting signature for EVM key association with hotkey {wallet.hotkey.ss58_address}...")
        signature, evm_address = get_signature_for_evm_key_association(hotkey=wallet.hotkey.ss58_address, block=block_number)
        bt.logging.info("Associating EVM key with hotkey...")
        success, msg = await associate_evm_key_with_hotkey(
            subtensor=subtensor,
            wallet=wallet,
            netuid=config.netuid,
            evm_addr=evm_address,
            block_num=block_number,
            signature=signature,
        )
        if not success:
            bt.logging.error(f"Failed to associate EVM key with hotkey: {msg}")
    else:
        bt.logging.warning(
            "EVM key association skipped. Set miner type to be UNISWAP_V3_LP and UNISWAP_POS_OWNER_KEY env var. to enable."
        )


if __name__ == "__main__":
    asyncio.run(main())
