# Miner Setup

Welcome to the Sturdy Subnet miner documentation! There are two different types of tasks that can be performed by participants in the subnet:

## Miner Types

### 1. Pool Allocators 🏦
Pool allocators are responsible for allocating assets across alpha token pools and lending pools on EVM-based chains. They focus on yield optimization and algorithmic improvements.

**👉 [Pool Allocation Miner Setup Guide](allocation_miner.md)**

### 2. TaoFi Liquidity Providers 💧
TaoFi liquidity providers are responsible for providing liquidity to the TaoFi TAO<>USDC pool on TaoFi platform.

**👉 [TaoFi Liquidity Provider Miner Setup Guide](taofi_lp.md)**

## Important Information

- **Exclusive Types**: Miners can only be one type at a time
- **Limited Slots**: There can only be a certain number of miners in each group
- **Emission Distribution**: Emissions are split amongst them as defined in [constants.py](../sturdy/constants.py) by `MINER_GROUP_THRESHOLDS` and `MINER_GROUP_EMISSIONS` respectively
- **Type Declaration**: Miners advertise themselves by defining the response to the `QueryMinerType` synapse (see `miner_type` function in [miner.py](../sturdy/base/miner.py))
