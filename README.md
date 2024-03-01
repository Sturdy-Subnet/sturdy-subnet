<div align="center">

# **Sturdy Finance Subnet** <!-- omit in toc -->
[![Discord Chat](https://img.shields.io/discord/308323056592486420.svg)](https://discord.gg/bittensor)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) 

---

## Decentralized Allocation Protocol for DeFi Lending Pools <!-- omit in toc -->
</div>

- [Introduction](#introduction)
  - [Subnet Overview](#subnet-overview)
- [Installation](#installation)
  - [Before you proceed](#before-you-proceed)
  - [Install](#install)
- [License](#license)

---

## Introduction

This is split into three primary files. 
1. `sturdy/protocol.py`: Contains the definition of the protocol used by subnet miners and subnet validators. At the moment it only has one kind of synapse - `AllocateAssets` - which contains the inputs (`assets_and_pools`) validators need to send to miners to generate return `allocations` for. See `generate_assets_in_pools()` in [pools.py](./sturdy/pools.py) to see how assets and pools are defined.
2. `neurons/miner.py`: Script that defines the subnet miner's behavior, i.e., how the subnet miner responds to requests from subnet validators.
3. `neurons/validator.py`: This script defines the subnet validator's behavior, i.e., how the subnet validator requests information from the subnet miners and determines the scores.

### Subnet Overview
- Validators are reponsible for distributing lists of pools (of which contain relevant parameters such as base interest rate, base interest rate slope, minimum borrow amount, etc), as well as a maximum token balance miners can allocate to pools. Below is the function present in the codebase used for generating a dummy `assets_and_pools` taken from [pools.py](./sturdy/pools.py):
```python
def generate_assets_and_pools() -> typing.Dict:  # generate pools
    assets_and_pools = {}
    pools = {
        x: {
            "pool_id": x,
            "base_rate": randrange_float(
                MIN_BASE_RATE, MAX_BASE_RATE + BASE_RATE_STEP, BASE_RATE_STEP
            ),
            "base_slope": randrange_float(
                MIN_SLOPE, MAX_SLOPE + SLOPE_STEP, SLOPE_STEP
            ),
            "kink_slope": randrange_float(
                MIN_KINK_SLOPE, MAX_KINK_SLOPE + SLOPE_STEP, SLOPE_STEP
            ),  # kink rate - kicks in after pool hits
            "optimal_util_rate": OPTIMAL_UTIL_RATE,  # optimal utility rate - after which the kink slope kicks in >:)
            "borrow_amount": randrange_float(
                MIN_BORROW_AMOUNT,
                MAX_BORROW_AMOUNT + BORROW_AMOUNT_STEP,
                BORROW_AMOUNT_STEP,
            ),
        }
        for x in range(NUM_POOLS)
    }

    assets_and_pools["total_assets"] = TOTAL_ASSETS
    assets_and_pools["pools"] = pools

    return assets_and_pools
```
- The miners, after receiving these pools from validators, must then attempt to allocate the `TOTAL_ASSETS` into the given pools, with the ultimate goal of trying to maximize their yield. This repository comes with a default asset allocation algorithm in the form of `greedy_allocation_algorithm` (a greedy allocation algorithm) in [misc.py](./sturdy/utils/misc.py). The greedy allocation essentially works by breaking its assets into many chunks of small sizes, and allocating them into the pools by utilizing their current yields to determine its allocations to each pool (it is done this way because the yields of the pools are dynamic based on their various parameters - most notably it's `utilization rate = borrow amount / total available tokens`). A diagram is provided below for the more visually attuned: 

![allocations](./assets/allocations.png)

- After generating allocations, miners then send their outputs to validators to be scored. The scores of miners are determined based on their relative yields their response latency. This means that the fastest, best allocating miner will receive the most emissions, with an `80%` weight placed on yield alone, and the other `20%` being dependent on miner latency. The resulting is between a range of `0-1`. In math speak: $$s_{{k}} = 0.8y_k + 0.2r_k $$ where $s_k$, $y_k$, and $r_k$ are the score, yield, latency of miner $k$ respectively. The reward curve of $r_k$ is determined by a sigmoid curve with response time being the function (see below). Note: The timeout for a miner is 10 seconds, hence why the reward for >= 10s of response time is 0. For more information on how miners are rewarded - please see [reward.py](./sturdy/validator/reward.py).

<div align="center"> 
    <img src="./assets/latency_scaling.png" />
</div> 

---

## Installation

### Before you proceed
Before you proceed with the installation, note the following: 

- **IMPORTANT:** Make sure you are aware of the minimum compute requirements for your subnet. See the [Minimum compute YAML configuration](./min_compute.yml).
- Note that installation instructions differ based on your situation: For example, installing for local development and testing will require a few additional steps compared to installing for testnet or mainnet. For running a local subtensor - please visit: [https://github.com/opentensor/subtensor](https://github.com/opentensor/subtensor).

### Install
```bash
git clone https://github.com/Shr1ftyy/sturdy-subnet/
cd sturdy-subnet
python -m pip install -e .
```

<!-- - **Running locally**: Follow the step-by-step instructions described in this section: [Running Subnet Locally](./docs/running_on_staging.md).
- **Running on Bittensor testnet**: Follow the step-by-step instructions described in this section: [Running on the Test Network](./docs/running_on_testnet.md).
- **Running on Bittensor mainnet**: Follow the step-by-step instructions described in this section: [Running on the Main Network](./docs/running_on_mainnet.md). -->

---

## Running

### Validator
```bash
python3 neurons/validator.py --netuid NETUID --subtensor.network NETWORK --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug --axon.port PORT
```

### Miner
```bash
python3 neurons/miner.py --netuid NETUID --subtensor.network NETWORK --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug --axon.port PORT
```
---

## License
This repository is licensed under the MIT License.
```text
# The MIT License (MIT)
# Copyright © 2023 Yuma Rao

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
```
