from enum import Enum

import bittensor as bt
from web3 import AsyncWeb3


class POOL_DATA_PROVIDER_TYPE(str, Enum):
    ETHEREUM_MAINNET = "ETHEREUM_MAINNET"
    BITTENSOR_MAINNET = "BITTENSOR_MAINNET"
    BITTENSOR_WEB3 = "BITTENSOR_WEB3"


class PoolProviderFactory:
    @staticmethod
    async def create_pool_provider(
        provider: POOL_DATA_PROVIDER_TYPE, url: str, **kwargs: any
    ) -> AsyncWeb3 | bt.AsyncSubtensor:
        """
        Create a pool provider based on the given provider type.
        :param provider: The provider type to create.
        :param kwargs: Additional arguments to pass to the provider constructor.
        :return: An instance of the specified pool provider.
        """
        if provider == POOL_DATA_PROVIDER_TYPE.ETHEREUM_MAINNET:
            return AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(url, **kwargs))
        if provider == POOL_DATA_PROVIDER_TYPE.BITTENSOR_MAINNET:
            subtensor = bt.AsyncSubtensor(url)
            await subtensor.initialize()
            return subtensor
        # TODO(uniwap_v3_lp): remove this if we believe that the bittensor web3 provider is not needed
        if provider == POOL_DATA_PROVIDER_TYPE.BITTENSOR_WEB3:
            return AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(url, **kwargs))
        raise ValueError(f"Unsupported provider type: {provider}")
