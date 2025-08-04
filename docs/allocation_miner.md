# Pool Allocation Miner Setup

Pool allocators are responsible for allocating assets across alpha token pools and lending pools on EVM-based chains. They aim to obtain the highest yield possible whilst responding very quickly to validators with unique responses.

### Hardware

See [min_compute.yml](../min_compute.yml)

## Setup steps

### Clone the repo
```bash
git clone https://github.com/Sturdy-Subnet/sturdy-subnet/
cd sturdy-subnet
```

### Install python dependencies
Make sure you have installed the correct python version, and then follow these steps:

```bash
### Install the local python environment
pip install --upgrade pip
pip install -e .
```

#### Local subtensor
Before running a validator it is **highly** recommended that you run a local subtensor vs. just connecting to the `finney` endpoint. Instructions for setting up a local subtensor can be found [here](https://github.com/opentensor/subtensor/blob/main/docs/running-subtensor-locally.md).

#### Connecting to Ethereum
Miners are required to have a connection to an Ethereum RPC to handle requests. It is required to interact with relevant smart contracts in order to perform certain operations i.e. calculate miner allocation yields.

##### Preparing Environment
The next step involves interacting with an API. We've provided an [.env.example](../.env.example) file which should be copied as a `.env` file in the root of this repository before proceeding.

#### Connecting to a Web3 Provider
We recommend using a third party service to connect to an RPC to perform on-chain calls to evm-based chains (e.g. Ethereum) such as [Infura](https://docs.infura.io/dashboard/create-api) and [Alchemy](https://docs.alchemy.com/docs/alchemy-quickstart-guide#1key-create-an-alchemy-api-key) (click on hyperlinks links for documentation) by obtaining there API key and adding their URL to the `.env` file under the `ETHEREUM_MAINNET_PROVIDER_URL` alias.

We also support bittensor alpha token pools, so you may want access to an archive subtensor node for historical data. The environment variable for this is `BITTENSOR_MAINNET_PROVIDER_URL`. Thankfully, there is already a public one that can be used (see `.env.example`).

## Running a Pool Allocation Miner

#### Committing Miner Type

Before starting your miner, you need to commit your miner type to the network using the `commit.py` script:

```bash
python3 scripts/commit.py --netuid NETUID --subtensor.network NETWORK --wallet.name NAME --wallet.hotkey HOTKEY --miner-type POOL_ALLOCATOR
```

#### Starting a miner

```bash
python3 neurons/miner.py --netuid NETUID --subtensor.network NETWORK --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug --axon.port PORT
```

#### Participating in Testnet
If you would like to participate in the testnet replace `NETUID` with `104` and add the `--validator.min_stake -1` parameter.

First, commit your miner type for testnet:
```bash
python3 scripts/commit.py --netuid 104 --subtensor.network test --wallet.name NAME --wallet.hotkey HOTKEY --miner-type POOL_ALLOCATOR
```

Then start your miner:
```bash
python3 neurons/miner.py --netuid 104 --subtensor.network test --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug --axon.port PORT --validator.min_stake -1
```

## Succeeding as a Pool Allocation Miner

A pool allocation miner should aim to obtain the highest yield possible whilst responding very quickly to validators with unique responses. While a default allocation generation script has been provided in [algo.py](../sturdy/algo.py), there is lots of room for optimization. 

Miners who want to excel in the Sturdy Subnet should try to improve on this algorithm using the information shared above and by taking a close look at how pools (as well as their yields) are defined (e.g. in [pools.py](../sturdy/pools.py)).

The key to success as a pool allocation miner is:

1. **Speed**: Respond to validators as quickly as possible
2. **Uniqueness**: Provide unique allocation responses compared to other miners
3. **Yield Optimization**: Maximize the yield of your allocations
4. **Algorithm Improvement**: Enhance the default allocation algorithm in [algo.py](../sturdy/algo.py)
