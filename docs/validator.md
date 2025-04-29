# Validator Setup

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

### Install node and pm2
You will need `pm2` if you would like to utilize the auto update scripts that comes with this repository

1. Install [node and npm](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm)
2. Install [pm2](https://pm2.io)

### Creating the database
Used to store api keys, scoring logs, and "active" miner allocations for scoring

First, [install dbmate](https://github.com/amacneil/dbmate?tab=readme-ov-file#installation). then run the command below
```bash
dbmate --url "sqlite:validator_database.db" up
```


## Running a Validator

#### Local subtensor
Before running a validator it is **highly** recommended that you run a local subtensor vs. just connecting to the `finney` endpoint. Instructions for setting up a local subtensor can be found [here](https://github.com/opentensor/subtensor/blob/main/docs/running-subtensor-locally.md).

Now - let's get to the good stuff.

Before we get to the differences between them, and how to set each of them up, we must first ensure we have a connection to the Ethereum network.

#### Connecting to Ethereum
All validators are required to have a connection to an Ethereum RPC to handle requests. It is required to interact with relevant smart contracts in order to perform certain operations i.e. calculate miner allocation yields.

##### Preparing Environment
The next step involves interacting with an API. We've provided an [.env.example](../.env.example) file which should be copied as a `.env` file in the root of this repository before proceeding.

##### Connecting to chain providers for pool data
We recommend using a third party service to connect to an RPC to perform on-chain calls to evm-based chains (e.g. Ethereum) such as [Infura](https://docs.infura.io/dashboard/create-api) and [Alchemy](https://docs.alchemy.com/docs/alchemy-quickstart-guide#1key-create-an-alchemy-api-key) (click on hyperlinks links for documentation) by obtaining there API key and adding their URL to the `.env` file under the `ETHEREUM_MAINNET_PROVIDER_URL` alias.

We also support bittensor alpha token pools, and as a validator you will need access to an archive subtensor node for historical data. The environment variable for this is `BITTENSOR_MAINNET_PROVIDER_URL`. Thankfully, there is already a public one that can be used (see `.env.example`).

### Spinning Up Validator

Before you start the validator, run the command
```bash
lsof -i -P -n | grep LISTEN
```

This shows you all the ports currently in use. When you come to choose a port for running the api server, make sure the ports you choose aren't already in use.

Example output:

![image](../assets/ports_in_use.png)

This shows that ports 9091, 3001, .., 34579, 41133 etc, are currently in use, so pick address that don't include these.

#### Starting the validator and API server - without PM2
```bash
python neurons/validator.py --netuid NETUID --subtensor.network local --wallet.name NAME --wallet.hotkey HOTKEY --logging.trace --axon.port PORT --api_port API_PORT
```

#### Starting the validator and API server - with PM2 (REQUIRED FOR AUTOUPDATES)
```
pm2 start --name PROC_NAME --interpreter=python3 neurons/validator.py -- --netuid NETUID --subtensor.network local --wallet.name NAME --wallet.hotkey HOTKEY --logging.trace --axon.port PORT --api_port API_PORT
```

Replace, `PROC_NAME`, `NAME`, `NETWORK`, `HOTKEY`, `PORT`, `API_PORT` with your desired values. As mentioned in our [README](../README.md) we ***highly recommend*** that validators run a local subtensor and use `local` in place of the `NETWORK` parameter.

**Note**: If you would like to participate in the testnet replace `NETUID` with `104`

### Autoupdate script

List pm2 processes:
```
pm2 ls
```
You should see a list of processes as show below: \
![pm2ls](../assets/pm_list.png) \
Take note of either the `id` or `name` of the process - you'll need it going forward. For our case (as seen in the picture above) our validator's id is `6` and it's name is `vali0` 

Run the following command to run the auto updater script. This will periodically scan the upstream branch, pull when there are changes, reinstall the repo, and finall restart the validator automatically:

```
pm2 start --name run_validator_auto_update --interpreter=python3 run_validator_auto_update.py -- --proc ID_OR_PROCESS_NAME
```

Where `ID_OR_PROCESS_NAME` is the `name` OR `id` of the process as noted per the previous step. 

## Selling your bandwidth

### Managing access

To manage access to the your api server and sell access to anyone you like, using the sturdy-cli is the easiest way.

```bash
sturdy --help
```

Shows all the commands and should give self explanatory instructions.

You can also do

```bash
sturdy some-command --help
```

To get more info about that command!

#### Examples

For example:

```bash
sturdy create-key --balance 10 --rate-limit-per-minute 60 --name test
```
Creates a test key with a balance of 10 (which corresponds to 10 requests), a rate limit of 60 requests per minute = 1/s, and a name 'test'.

<!-- **Recommend values:**
- Balance: Depends on how much you want to sell! Each credit is a image (so a balance of 1000 will allow 1000 images to be generated)
- Rate limit: I would recommend a rate limit of ~20/minute for casual users trying out the API, and around ~120/minute for production users
- Name: Just for you to remember who you want to use that key :) -->

Now you can do:
```bash
sturdy list-keys
```
To see the API key. Give / sell this access to whoever you want to have access to your API server to query the network organically - these will be scored too!

## Allowing people to access your server
For them to use your server, you will need to communicate:

- Your server address (IP_ADDRESS:PORT)
- Use /redoc or /docs for automatic documentation on how to use it!
- The API key you generated for them

Please see [docs/api_usage.md](api_usage.md) for more information on how to use the API.

## Running with Docker

We provide a Docker image for easy deployment of validators. Here's how to run a validator using Docker:

1. Run using `docker compose` on mainnet with environment variables:
```bash
NETUID=10 \
NETWORK=wss://entrypoint-finney.opentensor.ai:443 \
WALLET_NAME=WALLET_NAME \
WALLET_HOTKEY=WALLET_HOTKEY \
AXON_PORT=AXON_PORT \
API_PORT=API_PORT \
WANDB_OFF=false \
docker compose up -d
```

This will:
- Initialize the SQLite database
- Start the validator process with PM2
- Enable auto-updates using watchtower
- Mount your local wallets directory
- Expose the API and Axon ports

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
| `AXON_PORT` | Port for Axon server | 8001 |
| `API_PORT` | Port for API server | 8000 |
| `WANDB_OFF` | Disable wandb logging | false |

### Docker Volumes

The docker compose configuration mounts these volumes:

- `.:/app` - Mounts the current directory to allow database persistence
- `~/.bittensor/wallets/:/root/.bittensor/wallets` - Mounts your local wallet directory

### Auto-Updates

The included watchtower service will automatically check for new Docker image versions every 30 seconds and update your validator container if a new version is available.

To disable auto-updates, remove the watchtower service from your docker compose.yml file.

### Examples

Run with custom wallet and ports:
```bash
WALLET_NAME=myvalidator \
WALLET_HOTKEY=mykey \
AXON_PORT=9001 \
API_PORT=9000 \
docker compose up -d
```

Run with wandb disabled:
```bash
WANDB_OFF=true docker compose up -d
```
