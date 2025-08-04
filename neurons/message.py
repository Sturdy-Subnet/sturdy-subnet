import argparse
import os

import bittensor as bt
import dotenv
from bittensor import Keypair
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

dotenv.load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate message to sign for EVM key association (matching Rust implementation)."
    )
    parser.add_argument("--hotkey", required=True, help="SS58 hotkey address")
    parser.add_argument("--block", required=True, type=int, help="Block number (integer)")

    bt.subtensor.add_args(parser)
    args = bt.config(parser)

    # TODO(commitment): This is a temporary solution to get the private key from an environment variable.
    # In the future we'd likely want to make this entire process more streamlined - i.e. through a frontend interface
    private_key = os.getenv("UNISWAP_POS_OWNER_KEY")

    block_number_bytes = args.block.to_bytes(8, byteorder="little")
    block_number_hash = Web3.keccak(block_number_bytes)

    hotkey_bytes = Keypair(ss58_address=args.hotkey).public_key
    print("Hotkey public key bytes:", hotkey_bytes.hex())
    message_to_sign_bytes = hotkey_bytes + block_number_hash

    signable_message = encode_defunct(primitive=message_to_sign_bytes)
    account = Account.from_key(private_key)
    signed_message = account.sign_message(signable_message)

    # print stuff
    print("Message to sign (hex):", "0x" + message_to_sign_bytes.hex())
    print("Signature (hex):", "0x" + signed_message.signature.hex())
    print("EVM address:", account.address)
    print("Hotkey address:", args.hotkey)
    print("Block number:", args.block)


if __name__ == "__main__":
    main()
