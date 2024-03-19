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

## Running a Validator

#### Local subtensor
Before running a validator it is **highly** recommended that you run a local subtensor vs. just connecting to the `finney` endpoint. Instructions for setting up a local subtensor can be found [here](https://github.com/opentensor/subtensor/blob/main/docs/running-subtensor-locally.md).

Now - let's get to the good stuff.

#### Validator types
You have the option of running two kinds of validators:
 - [Synthetic](#synthetic-validator)
 - [Organic](#organic-validator)

## Synthetic Validator 
This is the most simple of the two. Synthetic validators generate dummy (fake) pools to send to miners to challenge them. To run a synthetic validator, run:
#### Starting the validator
```bash
python3 neurons/validator.py --netuid NETUID --subtensor.network local --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug --axon.port PORT --organic False
```

Replace, `NAME`, `HOTKEY`, `PORT`. with your desired values.

**Note**: If you would like to participate in the testnet replace `NETUID` with `104`


## Organic Validator 
This is the less simple but more exciting of the two! Now you get to sell your bandwidth to whoever you want, with a very simple to use CLI!

The steps are similar to synthetic only validators:

Before you start the validator, run the command
```bash
lsof -i -P -n | grep LISTEN
```

This shows you all the ports currently in use. When you come to choose a port for running the api server, make sure the ports you choose aren't already in use.

Example output:

![image](../assets/ports_in_use.png)

This shows that ports 9091, 3001, .., 34579, 41133 etc, are currently in use, so pick address that don't include these.

#### Starting the validator and API server

```bash
python3 neurons/validator.py --netuid NETUID --subtensor.network local --wallet.name NAME --wallet.hotkey HOTKEY --logging.debug --axon.port PORT --organic True --api_port API_PORT
```

Replace, `NAME`, `HOTKEY`, `PORT`, `API_PORT`. with your desired values.

**Note**: If you would like to participate in the testnet replace `NETUID` with `104`

## Selling your bandwidth

### Creating the database
Used to store api keys & scoring logs

First, [install dbmate](https://github.com/amacneil/dbmate?tab=readme-ov-file#installation)

```bash
dbmate --url "sqlite:validator_database.db" up
```

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

# Examples

For example:

```bash
sturdy create-key 10 60 test
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