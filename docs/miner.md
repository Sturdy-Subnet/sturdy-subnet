# Miner Setup

### Hardware

See [min_compute.yml](../min_compute.yml)

# Setup steps

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

## Running a Miner

#### Local subtensor
Before running a validator it is **highly** recommended that you run a local subtensor vs. just connecting to the `finney` endpoint. Instructions for setting up a local subtensor can be found [here](https://github.com/opentensor/subtensor/blob/main/docs/running-subtensor-locally.md).

#### Starting a miner

```bash
python3 neurons/miner.py --netuid NETUID --subtensor.network NETWORK --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug --axon.port PORT
```

Replace, `NAME`, `HOTKEY`, `PORT`, `API_PORT`. with your desired values.

**Note**: If you would like to participate in the testnet replace `NETUID` with `104`

## Succeeding as a miner
As mentioned in [here](../README.md#subnet-overview), 80% of a miner's score comes from how much yield their allocation produces relative to other miners. While a default allocation generation script has been provided in [misc.py](./sturdy/utils/misc.py), there is lots of room for optimization. Miners who want to excel in the Sturdy Subnet should try to improve on this algorithm using the information shared above and by taking a close look at how pools (as well as their yields) are defined (e.g. in [pools.py](./sturdy/pools.py)).