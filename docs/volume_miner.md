# Earning Rewards by Generating Volume on TaoFi 📈

Volume generator miners are responsible for generating trading volume on the TaoFi TAO<>USDC pool. Validators track swap transactions and reward miners based on the total USD value of volume they generate.

## How Volume Generation Works

Volume generator miners earn rewards by executing swaps on the TaoFi platform. The Sturdy Subnet validators track all swaps in the TAO<>USDC Uniswap V3 pool and attribute volume to miners based on their associated EVM addresses.

## Running a Miner

You may optionally register a hotkey and run a miner to earn SN10 alpha tokens, and instead of receiving rewards directly to your wallet, you will receive them to your miner's hotkey address.

### Setup Environment
- Edit your `.env` file to include the private key for the EVM wallet you used to provide liquidity to the pool:
```plaintext
EVM_KEY="your_private_key_here"
```

### Commit Miner Type
Before starting your TaoFi liquidity provider miner, you need to commit your miner type to the network:

```bash
python3 scripts/commit.py --netuid NETUID --subtensor.network NETWORK --wallet.name NAME --wallet.hotkey HOTKEY --miner-type VOLUME_GENERATOR
```

This script will:
1. Commit your miner type as `VOLUME_GENERATOR`
2. Automatically generate a signature and associate your EVM address with your hotkey

Now, go to [https://www.taofi.com/swap](https://www.taofi.com/swap) and start generating some volume `:^)` !