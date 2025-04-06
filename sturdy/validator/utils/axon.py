import traceback

import bittensor as bt
from aiohttp.client_exceptions import InvalidUrlClientError

from sturdy.constants import (
    QUERY_TIMEOUT,
)
from sturdy.validator.request import Request


async def query_single_axon(dendrite: bt.dendrite, request: Request, query_timeout: int = QUERY_TIMEOUT) -> Request | None:
    """
    Query a single axon with a request.

    Args:
        dendrite (bt.dendrite): The dendrite to use for querying.
        request (Request): The request to send.

    Returns:
        Request | None: The request with results populated, or None if the request failed.
    """

    try:
        result = await dendrite.call(
            target_axon=request.axon,
            synapse=request.synapse,
            timeout=query_timeout,
            deserialize=False,
        )

        if not result:
            return None
        request.synapse = result
        request.response_time = result.dendrite.process_time if result.dendrite.process_time is not None else query_timeout

        request.deserialized = result.deserialize()
        return request

    except InvalidUrlClientError:
        bt.logging.error(f"Ignoring UID as axon is not a valid URL: {request.uid}. {request.axon.ip}:{request.axon.port}")
        return None

    except Exception as e:
        bt.logging.error(f"Failed to query axon for UID: {request.uid}. Error: {e}")
        traceback.print_exc()
        return None
