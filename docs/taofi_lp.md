# Earning Rewards by providing Liquidity to the TaoFi TAO<>USDC pool

## Providing liquidity to the TaoFi TAO<>USDC pool

### EVM Wallet
The first step is to actually start providing liquidity to the TaoFi TAO<>USDC pool. To do this you'll need to set up an EVM wallet that is compatible with the TaoFi platform.
We recommend using [MetaMask](https://metamask.io/) for this.

### Providing Liquidity
- First, head to [https://www.taofi.com/swap](https://www.taofi.com/swap)
- Connect your wallet to the TaoFi platform:

    ![wallet](../assets/taofi_connect.png)
- You can now swap some TAO for USDC, or vice versa. You will need both tokens in your wallet to provide liquidity.

    ![swap](../assets/swap.png)

- Once you have both tokens, head to [https://www.taofi.com/pool](https://www.taofi.com/pool), select the amount of TAO you want to deposit into the pool, the tick price range. Then, you will need to Approve the USDC token to be deposited into the pool, and finally, click on the "Add Liquidity" button to provide liquidity to the pool.

Approve             |  Add Liquidity
:-------------------------:|:-------------------------:
 ![approve](../assets/approve.png) | ![add_liquidity](../assets/liquidity.png)

- You will then be able to view your position in the pool. Make sure to note down it's position ID, as you will need it later to receive rewards from the Sturdy Subnet.

    ![position](../assets/position.png)

- You will now earn rewards from the pool as long as your position(s) are in-range, and receive fees from the trades that occur in the pool. Rewards will be automatically distributed on a daily basis to your wallet address, and can be viewed and transferred here: [https://sturdy-subnet.github.io/alpha/](https://sturdy-subnet.github.io/alpha/)

    ![staking_precompile](../assets/staking_precompile.png)

## Running a Miner (OPTIONAL)

You may optionally register a hotkey and run a miner to earn SN10 alpha tokens, and instead of receiving rewards directly to your wallet, you will receive them to your miner's hotkey address.

- Edit your `.env` file to include the seed phrase for the EVM wallet you used to provide liquidity to the pool:

```plaintext
UNISWAP_POS_OWNER_KEY="your seed phrase here"
```
- Change the token ids that the miner will respond with in `uniswap_v3_lp_forward` in [uniswap_lp.py](../neurons/uniswap_lp.py) to bethe positions you own:
```python
async def uniswap_v3_lp_forward(
    self, synapse: sturdy.protocol.UniswapV3PoolLiquidity
) -> sturdy.protocol.UniswapV3PoolLiquidity:
    bt.logging.warning("Received UniswapV3PoolLiquidity synapse")
    # set the token ids of your position
    synapse.token_ids = [36] # <-- replace with your position token id(s)
    # sign the message with your wallet that owns the position(s)
    message = encode_defunct(text=synapse.message)
    signed_msg: SignedMessage = self.test_w3.eth.account.sign_message(message, private_key=self.uniswap_pos_owner_key)
    synapse.signature = signed_msg.signature.hex()

    return synapse
```
- Then start your miner as shown shown in [Starting a miner](miner.md#starting-a-miner)