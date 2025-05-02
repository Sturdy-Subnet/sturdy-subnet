# Validator API Usage

This document provides an overview of how to use the API, including how to request allocation suggestions and check your API key information.

- [Validator API Usage](#validator-api-usage)
  - [Request Allocations](#request-allocations)
    - [Example - lending pools on Ethereum](#example---lending-pools-on-ethereum)
    - [Example - alpha token pools on Bittensor](#example---alpha-token-pools-on-bittensor)
      - [Simple method (recommended)](#simple-method-recommended)
      - [Advanced Method (not recommended)](#advanced-method-not-recommended)
  - [Checking API Key Information](#checking-api-key-information)

---

## Request Allocations
### Example - lending pools on Ethereum
Just for reference - below is an example `curl` command which could be used to interact with an organic validator:

```bash
curl -X POST \
  http://{HOST_ADDRESS}/allocate \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {API_KEY}' \
  -d '{
  "num_allocs": 3,
  "request_type": "ORGANIC",
  "user_address": "0x73E4C11B670Ef9C025A030A20b72CB9150E54523",
  "pool_data_provider_type": "ETHEREUM_MAINNET",
  "assets_and_pools": {
    "total_assets": 1120877955333353905234925,
    "pools": {
      "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227": {
        "pool_model_disc": "EVM_CHAIN_BASED",
        "pool_type": "STURDY_SILO",
        "contract_address": "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227",
        "pool_data_provider_type": "ETHEREUM_MAINNET"
      },
       "0x200723063111f9f8f1d44c0F30afAdf0C0b1a04b": {
        "pool_model_disc": "EVM_CHAIN_BASED",
        "pool_type": "STURDY_SILO",
        "contract_address": "0x200723063111f9f8f1d44c0F30afAdf0C0b1a04b",
        "pool_data_provider_type": "ETHEREUM_MAINNET"
      },
       "0x26fe402A57D52c8a323bb6e09f06489C8216aC88": {
        "pool_model_disc": "EVM_CHAIN_BASED",
        "pool_type": "STURDY_SILO",
        "contract_address": "0x26fe402A57D52c8a323bb6e09f06489C8216aC88",
        "pool_data_provider_type": "ETHEREUM_MAINNET"
      },
       "0x8dDE9A50a91cc0a5DaBdc5d3931c1AF60408c84D": {
        "pool_model_disc": "EVM_CHAIN_BASED",
        "pool_type": "STURDY_SILO",
        "contract_address": "0x8dDE9A50a91cc0a5DaBdc5d3931c1AF60408c84D",
        "pool_data_provider_type": "ETHEREUM_MAINNET"
      }
    }
  }
}'
```

Some annotations are provided below to further help understand the request format:
```json
 "num_allocs": 3, # number of top allocations to return - by default this is set to 1
  "request_type": "ORGANIC", # request type
  "user_address": "0x73E4C11B670Ef9C025A030A20b72CB9150E54523", # this tends to be an aggregator address
  "pool_data_provider_type": "ETHEREUM_MAINNET", # pool data provider type - this is used to determine which pool data provider to use
  "assets_and_pools": {
    "total_assets": 548568963376234830607950, # total assets available to a miner to allocate
    "pools": { # pools available to output allocations for
      "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227": { # address used to get relevant info about the the pool
        "pool_model_disc": "EVM_CHAIN_BASED", # used by endpoint to determine how to postprocess the pool data
        "pool_type": "STURDY_SILO",  # type of pool (i.e sturdy silo, aave pool, yearn vault, etc.)
        "contract_address": "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227" # address used to get relevant info about the the pool
      },
      ...
```

And the corresponding response(example) format from the subnet:
```json
{
    "request_uuid":"1e09d3f1ce574921bd13a2461607f5fe",
    "allocations":{
        "1":{ # miner uid
            "rank":1, # rank of the miner based on past performance
            "allocations":{ # allocations to pools
                "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227":114864688949643874140160,
                "0x200723063111f9f8f1d44c0F30afAdf0C0b1a04b":1109027125282399872,
                "0x26fe402A57D52c8a323bb6e09f06489C8216aC88":71611128603622265323520,
                "0x8dDE9A50a91cc0a5DaBdc5d3931c1AF60408c84D":3594097438744
            }
        },
        "4":{
            "rank":2,
            "allocations":{
                "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227":119201178628424617426944,
                "0x200723063111f9f8f1d44c0F30afAdf0C0b1a04b":1290874337673458688,
                "0x26fe402A57D52c8a323bb6e09f06489C8216aC88":74795928505515430117376,
                "0x8dDE9A50a91cc0a5DaBdc5d3931c1AF60408c84D":4534575558121
            }
        },
        "2":{
            "rank":3,
            "allocations":{
                "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227":45592862828746122461184,
                "0x200723063111f9f8f1d44c0F30afAdf0C0b1a04b":172140896186699296,
                "0x26fe402A57D52c8a323bb6e09f06489C8216aC88":53871255848631538810880,
                "0x8dDE9A50a91cc0a5DaBdc5d3931c1AF60408c84D":465839210713
            }
        }
    }
}
```


### Example - alpha token pools on Bittensor


#### Simple method (recommended)

Here's an example of a request to obtain a suggestion on how to allocate TAO across alpha token pools on Bittensor:
```bash
curl -X POST \
  http://{HOST_ADDRESS}/allocate_bt \
  -H 'Content-Type: application/json
  -H 'Authorization: Bearer {API_KEY}' \
  -d '{
    "netuids": [3, 10, 64],
    "total_assets": 100000000000,
    "num_allocs": 1
}'
```

Optionally, you may also specify how much you may have already allocated across the pools. This is useful information to provide if you want the miners to account for slippage when rebalancing your allocations:

```bash
curl -X POST \
  http://{HOST_ADDRESS}/allocate_bt \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {API_KEY}' \
  -d '{
    "netuids": [3, 10, 64],
    "total_assets": 100000000000,
    "num_allocs": 1
    "current_allocations": {"3": 25000000000}
}'
```

Some annotations are provided below to further help understand the request format:
```json
    "netuids": [3, 10, 64], # netuids of the subnets miners can return allocations for
    "total_assets": 100000000000, # total assets available to a miner to allocate (in RAO - 1e9 RAO = 1 TAO)
    "num_allocs": 1 # number of top allocations to return - by default this is set to 1
    "current_allocations": {"3": 25000000000} # current allocations across the pools - this is used to determine how much to allocate to each pool
}
```

And the corresponding response(example) format from the subnet:
```json
{
    "request_uuid": "08061b749ea44ab1a91fe7c7febb2486", # request uid
    "allocations": { # allocations to pools
        "2": { # miner uid
            "rank": 1, # rank of the miner
            "allocations": {
                "3": { # netuid of the subnet this allocation is for
                    "delegate_ss58": "5F4tQyWrhfGVcNhoqeiNsR6KjD4wMZ2kfhLj4oHYuyHbZAc3", # ss58 address of the validator to delegate alpha to
                    "amount": 33000000000 # amount of TAO allocated to this pool
                },
                "10": {
                    "delegate_ss58": "5F4tQyWrhfGVcNhoqeiNsR6KjD4wMZ2kfhLj4oHYuyHbZAc3",
                    "amount": 33000000000
                },
                "64": {
                    "delegate_ss58": "5F4tQyWrhfGVcNhoqeiNsR6KjD4wMZ2kfhLj4oHYuyHbZAc3",
                    "amount": 33000000000
                }
            }
        }
    }
}
```

#### Advanced Method (not recommended)
Here's an example of a request to allocate assets across alpha token pools on Bittensor:
```bash
curl -X POST \
  http://{HOST_ADDRESS}/allocate \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {API_KEY}' \
  -d '{
    "num_allocs": 1,
    "pool_data_provider": "BITTENSOR_MAINNET",
    "request_type": "ORGANIC",
    "assets_and_pools": {
        "total_assets": 100000000000,
        "pools": {
            "10": {
                "pool_model_disc": "BT_ALPHA",
                "pool_type": "BT_ALPHA",
                "netuid": 10,
                "pool_data_provider_type": "BITTENSOR_MAINNET"
            },
            "3": {
                "pool_model_disc": "BT_ALPHA",
                "pool_type": "BT_ALPHA",
                "netuid": 3,
                "pool_data_provider_type": "BITTENSOR_MAINNET"
            },
            "64": {
                "pool_model_disc": "BT_ALPHA",
                "pool_type": "BT_ALPHA",
                "netuid": 64,
                "pool_data_provider_type": "BITTENSOR_MAINNET"
            }
        }
    }
}'
```

Some annotations are provided below to further help understand the request format:
```json
    "num_allocs": 1, # number of top allocations to return - by default this is set to 1
    "pool_data_provider": "BITTENSOR_MAINNET", # pool data provider type - this is used to determine which pool data provider to use
    "request_type": "ORGANIC", # request type
    "assets_and_pools": {
        "total_assets": 100000000000, # total assets available to a miner to allocate (TAO)
        "pools": { # pools available to output allocations for
            "10": { # netuid of the subnet this allocation is for - this is used as a key to obtain this allocation on the validator
                "pool_model_disc": "BT_ALPHA", # used by endpoint to determine how to postprocess the pool data
                "pool_type": "BT_ALPHA", # type of pool - this is a bittensor alpha token pool so we use BT_ALPHA
                "netuid": 10, # netuid of the subnet this allocation is for
                "pool_data_provider_type": "BITTENSOR_MAINNET" # pool data provider type - we use the bittensor mainnet provider for this pool
            },
      ...
```

And the corresponding response(example) format from the subnet:
```json
{
    "request_uuid": "08061b749ea44ab1a91fe7c7febb2486", # request uid
    "allocations": { # allocations to pools
        "2": { # miner uid
            "rank": 1, # rank of the miner
            "allocations": {
                "3": { # netuid of the subnet this allocation is for
                    "delegate_ss58": "5F4tQyWrhfGVcNhoqeiNsR6KjD4wMZ2kfhLj4oHYuyHbZAc3", # ss58 address of the validator to delegate alpha to
                    "amount": 33000000000 # amount of TAO allocated to this pool
                },
                "10": {
                    "delegate_ss58": "5F4tQyWrhfGVcNhoqeiNsR6KjD4wMZ2kfhLj4oHYuyHbZAc3",
                    "amount": 33000000000
                },
                "64": {
                    "delegate_ss58": "5F4tQyWrhfGVcNhoqeiNsR6KjD4wMZ2kfhLj4oHYuyHbZAc3",
                    "amount": 33000000000
                }
            }
        }
    }
}
```

## Checking API Key Information

You can check your API key's details using the `/api_key_info` endpoint. This endpoint is free to use and doesn't consume any credits.

Here's an example of how to check your API key information:

```bash
curl -X GET \
  http://{HOST_ADDRESS}/api_key_info \
  -H 'Authorization: Bearer {API_KEY}'
```

The response will contain information about your API key:
```json
{
    "balance": 95.0,           # Remaining credits
    "rate_limit_per_minute": 60,   # Maximum requests allowed per minute
    "name": "Test Key",        # Name associated with the key
    "created_at": "2025-04-18 10:30:00"  # When the key was created
}
```

This endpoint is useful for:
- Checking your remaining credit balance
- Verifying your rate limit settings
- Confirming when your API key was created
- Validating that your API key is active and working

Note: This endpoint does not consume any credits from your balance, but it still requires a valid API key and is subject to rate limiting.
