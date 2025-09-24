import asyncio
from dataclasses import asdict, dataclass

import bittensor as bt
from web3 import Web3


@dataclass
class AssociateEVMKeyParams:
    netuid: int
    hotkey: str
    evm_key: str
    block_number: int
    signature: str


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
        return False, msg

    bt.logging.info(f"Successfully associated EVM key {evm_addr} with hotkey for netuid {netuid}.")
    return True, msg


async def get_associated_evm_key(netuid: int, uid: int, subtensor: bt.AsyncSubtensor) -> str | None:
    substrate = subtensor.substrate

    result = await substrate.query(module="SubtensorModule", storage_function="AssociatedEvmAddress", params=[netuid, uid])

    if result is None:
        bt.logging.error(f"No associated EVM key found for netuid {netuid} and uid {uid}.")
        return None

    address_bytes = result.value[0][0]
    evm_addr = "0x" + bytes(address_bytes).hex()
    return Web3.to_checksum_address(evm_addr) if evm_addr != "0x" else None


async def get_associated_evm_keys(netuid: int, uids: list[int], subtensor: bt.AsyncSubtensor) -> dict[int, str]:
    """
    Fetches the EVM keys associated with hotkeys for a given network UID.

    Args:
        netuid (int): The network UID to query.
        uids (list[int]): List of UIDs to fetch associated EVM keys for.
        subtensor (bt.AsyncSubtensor): The Bittensor async subtensor instance.

    Returns:
        dict[int, str]: A dictionary mapping UIDs to their associated EVM keys.
    """

    # Start asyncio tasks and use gather to fetch EVM keys concurrently
    tasks = [get_associated_evm_key(netuid, uid, subtensor) for uid in uids]
    results = await asyncio.gather(*tasks)

    # Create a dictionary mapping UIDs to their associated EVM keys
    return dict(zip(uids, results, strict=False))
