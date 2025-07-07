import typing

import bittensor as bt
from eth_account.datastructures import SignedMessage
from eth_account.messages import encode_defunct

import sturdy


async def uniswap_v3_lp_forward(
    self, synapse: sturdy.protocol.UniswapV3PoolLiquidity
) -> sturdy.protocol.UniswapV3PoolLiquidity:
    bt.logging.warning("Received UniswapV3PoolLiquidity synapse")
    # set the token ids of your position
    synapse.token_ids = [33, 36, 49, 164]

    # sign the message with your wallet that owns the position(s)
    message = encode_defunct(text=synapse.message)
    signed_msg: SignedMessage = self.test_w3.eth.account.sign_message(message, private_key=self.uniswap_pos_owner_key)
    synapse.signature = signed_msg.signature.hex()

    return synapse


async def blacklist(self, synapse: sturdy.protocol.UniswapV3PoolLiquidity) -> typing.Tuple[bool, str]:
    """
    Determines whether an incoming request should be blacklisted and thus ignored. Your implementation should
    define the logic for blacklisting requests based on your needs and desired security parameters.

    Blacklist runs before the synapse data has been deserialized (i.e. before synapse.data is available).
    The synapse is instead contructed via the headers of the request. It is important to blacklist
    requests before they are deserialized to avoid wasting resources on requests that will be ignored.

    Args:
        synapse (template.protocol.AllocateAssets): A synapse object constructed from the headers of the incoming request.

    Returns:
        Tuple[bool, str]: A tuple containing a boolean indicating whether the synapse's hotkey is blacklisted,
                        and a string providing the reason for the decision.

    This function is a security measure to prevent resource wastage on undesired requests. It should be enhanced
    to include checks against the metagraph for entity registration, validator status, and sufficient stake
    before deserialization of synapse data to minimize processing overhead.

    Example blacklist logic:
    - Reject if the hotkey is not a registered entity within the metagraph.
    - Consider blacklisting entities that are not validators or have insufficient stake.

    In practice it would be wise to blacklist requests from entities that are not validators, or do not have
    enough stake. This can be checked via metagraph.S and metagraph.validator_permit. You can always attain
    the uid of the sender via a metagraph.hotkeys.index( synapse.dendrite.hotkey ) call.

    Otherwise, allow the request to be processed further.
    """

    bt.logging.info("Checking miner blacklist")

    if synapse.dendrite.hotkey not in self.metagraph.hotkeys:  # type: ignore[]
        return True, "Hotkey is not registered"

    requesting_uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)  # type: ignore[]
    stake = self.metagraph.S[requesting_uid].item()

    bt.logging.info(f"Requesting UID: {requesting_uid} | Stake at UID: {stake}")

    if stake <= self.config.validator.min_stake:
        bt.logging.info(
            f"Hotkey: {synapse.dendrite.hotkey}: stake below minimum threshold of {self.config.validator.min_stake}"  # type: ignore[]
        )
        return True, "Stake below minimum threshold"

    validator_permit = self.metagraph.validator_permit[requesting_uid].item()
    if not validator_permit:
        return True, "Requesting UID has no validator permit"

    bt.logging.trace(f"Allowing request from UID: {requesting_uid}")
    return False, "Allowed"


async def priority(self, synapse: sturdy.protocol.UniswapV3PoolLiquidity) -> float:
    """
    The priority function determines the order in which requests are handled. More valuable or higher-priority
    requests are processed before others. You should design your own priority mechanism with care.

    This implementation assigns priority to incoming requests based on the calling entity's stake in the metagraph.

    Args:
        synapse (template.protocol.AllocateAssets): The synapse object that contains metadata about the incoming request.

    Returns:
        float: A priority score derived from the stake of the calling entity.

    Miners may recieve messages from multiple entities at once. This function determines which request should be
    processed first. Higher values indicate that the request should be processed first. Lower values indicate
    that the request should be processed later.

    Example priority logic:
    - A higher stake results in a higher priority value.
    """
    caller_uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)  # Get the caller index. # type: ignore[]
    priority = float(self.metagraph.S[caller_uid])  # Return the stake as the priority.
    bt.logging.trace(f"Prioritizing {synapse.dendrite.hotkey} with value: ", priority)  # type: ignore[]
    return priority
