# Validator Setup

# Setup steps

### Clone the repo
```bash
git clone https://github.com/Sturdy-Subnet/sturdy-subnet/
cd sturdy-subnet
```

### Install python dependencies
First, install `uv` for fast Python package management:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install the dependencies:
```bash
uv sync
### use the env
source ~/.venv/bin/activate
### Install the local python environment
uv pip install -e .
```

### Install node and pm2

1. Install [node and npm](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm)
2. Install [pm2](https://pm2.io)

## Running a Validator
#### Set up wandb
We ***highly recommend*** that you set up wandb for your validator. Instructions can be found [here](wandb.md).

#### Local subtensor
Before running a validator it is **highly** recommended that you run a local subtensor vs. just connecting to the `finney` endpoint. Instructions for setting up a local subtensor can be found [here](https://github.com/opentensor/subtensor/blob/main/docs/running-subtensor-locally.md).

##### Preparing Environment
We've provided an [.env.example](../.env.example) file which should be copied as a `.env` file in the root of this repository before proceeding.

You will need access to an archive subtensor node for historical data. The environment variables for this is are `BITTENSOR_MAINNET_PROVIDER_URL` and `BITTENSOR_WEB3_PROVIDER_URL`.

#### Starting the validator without PM2
```bash
python neurons/validator.py --netuid NETUID --subtensor.network local --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug
```

#### Starting the validator - with PM2
```
pm2 start --name PROC_NAME --interpreter=python3 neurons/validator.py -- --netuid NETUID --subtensor.network local --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug
```

Replace, `PROC_NAME`, `NAME`, `NETWORK`, `HOTKEY`, with your desired values. As mentioned in our [README](../README.md) we ***highly recommend*** that validators run a local subtensor and use `local` in place of the `NETWORK` parameter.

**Note**: If you would like to participate in the testnet replace `NETUID` with `104`

## Running with Docker

We provide a Docker image for easy deployment of validators. Here's how to run a validator using Docker:

1. Run using `docker compose` on mainnet with environment variables:
```bash
NETUID=10 \
NETWORK=wss://entrypoint-finney.opentensor.ai:443 \
WALLET_NAME=WALLET_NAME \
WALLET_HOTKEY=WALLET_HOTKEY \
WANDB_OFF=false \
docker compose up -d
```

This will:
- Start the validator process with PM2
- Enable auto-updates using watchtower
- Mount your local wallets directory

2. View logs:
```bash
# View all logs
docker compose logs -f

# View only validator logs
docker compose logs -f sturdy-validator
```

3. Stop the validator:
```bash
docker compose down
```

### Docker Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NETUID` | Subnet ID | 10 |
| `NETWORK` | Subtensor network endpoint | wss://entrypoint-finney.opentensor.ai:443 |  
| `WALLET_NAME` | Wallet name | default |
| `WALLET_HOTKEY` | Wallet hotkey | default |
| `WANDB_OFF` | Disable wandb logging | false |

### Docker Volumes

The docker compose configuration mounts these volumes:

- `~/.bittensor/wallets/:/root/.bittensor/wallets` - Mounts wallet directory
- `~/.bittensor/miners/:/root/.bittensor/miners/` - Mounts miners directory which stores saved weights
- `.env/:/app/.env` - Mounts your environment configuration file

### Auto-Updates

The included watchtower service will automatically check for new Docker image versions every 30 seconds and update your validator container if a new version is available.

To disable auto-updates, remove the watchtower service from your docker compose.yml file.

### Examples

Run with custom wallet:
```bash
WALLET_NAME=myvalidator \
WALLET_HOTKEY=mykey \
docker compose up -d
```

Run with wandb disabled:
```bash
WANDB_OFF=true docker compose up -d
```
