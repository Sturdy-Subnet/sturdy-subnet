from enum import IntEnum

import bittensor as bt
from web3 import AsyncWeb3


class POOL_DATA_PROVIDER_TYPE(IntEnum):
    ETHEREUM_MAINNET = 0
    BITTENSOR_MAINNET = 1


class PoolProviderFactory:
    @staticmethod
    def create_pool_provider(provider: POOL_DATA_PROVIDER_TYPE, url: str, **kwargs: any) -> AsyncWeb3 | bt.AsyncSubtensor:
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
            return bt.AsyncSubtensor(**kwargs)
        raise ValueError(f"Unsupported provider type: {provider}")
