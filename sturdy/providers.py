from enum import Enum

import bittensor as bt
from web3 import AsyncWeb3


class POOL_DATA_PROVIDER_TYPE(str, Enum):
    ETHEREUM_MAINNET = "ETHEREUM_MAINNET"
    BITTENSOR_MAINNET = "BITTENSOR_MAINNET"


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
            # a dict of keyword arguments to pass to the constructor
            config = {
                "subtensor": {
                    "chain_endpoint": url,
                }
            }
            args_config = kwargs.get("config", {})
            # Merge the default config with the provided config
            config.update(args_config)
            kwargs["config"] = bt.config.fromDict(config)
            subtensor = bt.AsyncSubtensor(**kwargs)
            await subtensor.initialize()
            return subtensor
        raise ValueError(f"Unsupported provider type: {provider}")
