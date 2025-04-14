import asyncio
import json
import os
import unittest
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from web3 import AsyncWeb3
from web3.contract.async_contract import AsyncContract

from sturdy.constants import APR_ORACLE
from sturdy.pools import (
    AaveV3DefaultInterestRateV2Pool,
    AaveV3RateTargetBaseInterestRatePool,
    CompoundV3Pool,
    DaiSavingsRate,
    MorphoVault,
    VariableInterestSturdySiloStrategy,
    YearnV3Vault,
)
from sturdy.utils.misc import async_retry_with_backoff, retry_with_backoff

load_dotenv()
ETHEREUM_MAINNET_PROVIDER_URL = os.getenv("ETHEREUM_MAINNET_PROVIDER_URL")


# TODO: test pool_init seperately???
class TestAavePool(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 20233401
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

        self.atoken_address = "0x4d5F47FA6A74757f35C14fD3a6Ef8E3C9BC514E8"
        # Create a funded account for testing
        self.account = Account.create()
        await self.w3.eth.send_transaction(
            {
                "to": self.account.address,
                "from": (await self.w3.eth.accounts)[0],
                "value": self.w3.to_wei(200000, "ether"),
            }
        )

        weth_abi_file_path = Path(__file__).parent / "../../../sturdy/abi/IWETH.json"
        weth_abi_file = weth_abi_file_path.open()
        weth_abi = json.load(weth_abi_file)
        weth_abi_file.close()

        weth_contract = self.w3.eth.contract(abi=weth_abi)
        self.weth_contract = retry_with_backoff(
            weth_contract,
            address=AsyncWeb3.to_checksum_address("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"),
        )

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    async def asyncTearDown(self) -> None:
        # Create new web3 instance for teardown
        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))

        # Reset the hardhat network
        await w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_pool_contract(self) -> None:
        print("----==== test_pool_contract ====----")
        # we call the aave3 weth atoken proxy contract in this example
        pool = AaveV3RateTargetBaseInterestRatePool(
            contract_address=self.atoken_address,
        )

        await pool.pool_init(self.w3)
        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, AsyncContract))

    # TODO: test syncing after time travel
    async def test_sync(self) -> None:
        print("----==== TestAavePool | test_sync ====----")
        pool = AaveV3DefaultInterestRateV2Pool(
            contract_address=self.atoken_address,
        )

        # sync pool params
        await pool.sync(web3_provider=self.w3)

        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_yield_index"))
        self.assertTrue(isinstance(pool._yield_index, int))
        self.assertGreaterEqual(pool._yield_index, int(1e27))
        print(f"normalized income: {pool._yield_index}")

    async def test_supply_rate_alloc(self) -> None:
        print("----==== TestAavePool | test_supply_rate_increase_alloc ====----")
        pool = AaveV3DefaultInterestRateV2Pool(
            contract_address=self.atoken_address,
        )

        # sync pool params
        await pool.sync(web3_provider=self.w3)

        reserve_data = await async_retry_with_backoff(
            pool._pool_contract.functions.getReserveData(pool._underlying_asset_address).call
        )

        apy_before = AsyncWeb3.to_wei(reserve_data.currentLiquidityRate / 1e27, "ether")
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 2000000 ETH
        apy_after = await pool.supply_rate(int(2000000e18))
        print(f"apy after supplying 2000000 ETH: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertLess(apy_after, apy_before)

    async def test_supply_rate_decrease_alloc(self) -> None:
        print("----==== TestAavePool | test_supply_rate_decrease_alloc ====----")
        pool = AaveV3DefaultInterestRateV2Pool(contract_address=self.atoken_address, user_address=self.account.address)

        # sync pool params
        await pool.sync(web3_provider=self.w3)

        tx = await self.weth_contract.functions.deposit().build_transaction(
            {
                "from": self.w3.to_checksum_address(self.account.address),
                "gas": 100000,
                "gasPrice": await self.w3.eth.gas_price,
                "nonce": await self.w3.eth.get_transaction_count(self.account.address),
                "value": self.w3.to_wei(10000, "ether"),
            }
        )

        signed_tx = self.w3.eth.account.sign_transaction(transaction_dict=tx, private_key=self.account.key)

        # Send the transaction
        tx_hash = await self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"weth deposit tx hash: {tx_hash}")

        # check if we received some weth
        weth_balance = await self.weth_contract.functions.balanceOf(self.account.address).call()
        self.assertGreaterEqual(int(weth_balance), self.w3.to_wei(10000, "ether"))

        # approve aave pool to use weth
        tx = await self.weth_contract.functions.approve(
            pool._pool_contract.address, self.w3.to_wei(1e9, "ether")
        ).build_transaction(
            {
                "from": self.w3.to_checksum_address(self.account.address),
                "gas": 1000000,
                "gasPrice": await self.w3.eth.gas_price,
                "nonce": await self.w3.eth.get_transaction_count(self.account.address),
            }
        )

        signed_tx = self.w3.eth.account.sign_transaction(transaction_dict=tx, private_key=self.account.key)

        # Send the transaction
        tx_hash = await self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"pool approve weth tx hash: {tx_hash}")

        # deposit tokens into the pool
        tx = await pool._pool_contract.functions.supply(
            self.weth_contract.address,
            self.w3.to_wei(10000, "ether"),
            self.account.address,
            0,
        ).build_transaction(
            {
                "from": self.w3.to_checksum_address(self.account.address),
                "gas": 1000000,
                "gasPrice": await self.w3.eth.gas_price,
                "nonce": await self.w3.eth.get_transaction_count(self.account.address),
            }
        )

        signed_tx = self.w3.eth.account.sign_transaction(transaction_dict=tx, private_key=self.account.key)

        # Send the transaction
        tx_hash = await async_retry_with_backoff(self.w3.eth.send_raw_transaction, signed_tx.rawTransaction)
        print(f"supply weth tx hash: {tx_hash}")

        reserve_data = await async_retry_with_backoff(
            pool._pool_contract.functions.getReserveData(pool._underlying_asset_address).call
        )

        apy_before = AsyncWeb3.to_wei(reserve_data.currentLiquidityRate / 1e27, "ether")
        print(f"apy before rebalancing ether: {apy_before}")

        # calculate predicted future supply rate after removing 1000 ETH to end up with 9000 ETH in the pool
        await pool.sync(self.w3)
        apy_after = await pool.supply_rate(int(9000e18))
        print(f"apy after rebalancing ether: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertGreater(apy_after, apy_before)


class TestSturdySiloStrategy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 20225081
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        # previously: "blockNumber": 20233401,
                        "blockNumber": 21080765,
                    },
                },
            ],
        )

        self.contract_address = "0x0669091F451142b3228171aE6aD794cF98288124"
        # Create a funded account for testing
        self.account = Account.create()
        await self.w3.eth.send_transaction(
            {
                "to": self.account.address,
                "from": (await self.w3.eth.accounts)[0],
                "value": self.w3.to_wei(200000, "ether"),
            }
        )

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    async def asyncTearDown(self) -> None:
        # Create new web3 instance for teardown
        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))

        # Reset the hardhat network
        await w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21080765,
                    },
                },
            ],
        )

        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_silo_strategy_contract(self) -> None:
        print("----==== test_pool_contract ====----")
        whale_addr = self.w3.to_checksum_address("0x0669091F451142b3228171aE6aD794cF98288124")

        pool = VariableInterestSturdySiloStrategy(contract_address=self.contract_address, user_address=whale_addr)  # type: ignore[]

        await pool.sync(self.w3)

        self.assertTrue(hasattr(pool, "_silo_strategy_contract"))
        self.assertTrue(isinstance(pool._silo_strategy_contract, AsyncContract))
        print(f"silo contract: {pool._silo_strategy_contract.address}")

        self.assertTrue(hasattr(pool, "_pair_contract"))
        self.assertTrue(isinstance(pool._pair_contract, AsyncContract))
        print(f"pair contract: {pool._pair_contract.address}")

        self.assertTrue(hasattr(pool, "_rate_model_contract"))
        self.assertTrue(isinstance(pool._rate_model_contract, AsyncContract))
        print(f"rate model contract: {pool._rate_model_contract.address}")

        self.assertTrue(hasattr(pool, "_yield_index"))
        self.assertTrue(isinstance(pool._yield_index, int))
        print(f"price per share: {pool._yield_index}")

        # don't change deposit amount to pool by much
        prev_supply_rate = await pool.supply_rate(int(630e18))
        # increase deposit amount to pool by ~100e18 (~630 pxETH)
        supply_rate_increase = await pool.supply_rate(int(730e18))
        # decrease deposit amount to pool by ~100e18 (~530 pxETH)
        supply_rate_decrease = await pool.supply_rate(int(530e18))
        print(f"supply rate unchanged: {prev_supply_rate}")
        print(f"supply rate after increasing deposit: {supply_rate_increase}")
        print(f"supply rate after decreasing deposit: {supply_rate_decrease}")
        self.assertLess(supply_rate_increase, prev_supply_rate)
        self.assertGreater(supply_rate_decrease, prev_supply_rate)


class TestCompoundV3Pool(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 20233401
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 20233401,
                    },
                },
            ],
        )

        self.ctoken_address = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        self.user_address = "0x2b2E894f08F1BF8C93a82297c347EbdC8717d99a"
        # Create a funded account for testing
        self.account = Account.create()
        await self.w3.eth.send_transaction(
            {
                "to": self.account.address,
                "from": (await self.w3.eth.accounts)[0],
                "value": self.w3.to_wei(200000, "ether"),
            }
        )

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    async def asyncTearDown(self) -> None:
        # Create new web3 instance for teardown
        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))

        # Reset the hardhat network
        await w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21080765,
                    },
                },
            ],
        )

        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_compound_pool_model(self) -> None:
        print("----==== test_compound_pool_model ====----")
        pool = CompoundV3Pool(
            contract_address=self.ctoken_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        self.assertTrue(hasattr(pool, "_ctoken_contract"))
        self.assertTrue(isinstance(pool._ctoken_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_base_oracle_contract"))
        self.assertTrue(isinstance(pool._base_oracle_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_reward_oracle_contract"))
        self.assertTrue(isinstance(pool._reward_oracle_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_base_token_price"))
        self.assertTrue(isinstance(pool._base_token_price, float))

        self.assertTrue(hasattr(pool, "_reward_token_price"))
        self.assertTrue(isinstance(pool._reward_token_price, float))

        # check pool supply_rate
        print(f"pool supply rate: {await pool.supply_rate(0)}")

    async def test_supply_rate_increase_alloc(self) -> None:
        print("----==== test_supply_rate_increase_alloc ====----")

        pool = CompoundV3Pool(
            contract_address=self.ctoken_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        # get current balance of the user
        current_balance = await pool._ctoken_contract.functions.balanceOf(self.user_address).call()
        new_balance = current_balance + int(1000000e6)

        apy_before = await pool.supply_rate(current_balance)
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 1000000 USDC
        apy_after = await pool.supply_rate(new_balance)
        print(f"apy after supplying 1000000 USDC: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertLess(apy_after, apy_before)

    async def test_supply_rate_decrease_alloc(self) -> None:
        print("----==== test_supply_rate_decrease_alloc ====----")

        pool = CompoundV3Pool(
            contract_address=self.ctoken_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        # get current balance of the user
        current_balance = await pool._ctoken_contract.functions.balanceOf(self.user_address).call()
        new_balance = current_balance - int(1000000e6)

        apy_before = await pool.supply_rate(current_balance)
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after removing 1000000 USDC
        apy_after = await pool.supply_rate(new_balance)
        print(f"apy after removing 1000000 USDC: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertGreater(apy_after, apy_before)


class TestDaiSavingsRate(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 20225081
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 20233401,
                    },
                },
            ],
        )

        self.contract_address = self.w3.to_checksum_address("0x83f20f44975d03b1b09e64809b757c47f942beea")
        # Create a funded account for testing
        self.account = Account.create()
        await self.w3.eth.send_transaction(
            {
                "to": self.account.address,
                "from": (await self.w3.eth.accounts)[0],
                "value": self.w3.to_wei(200000, "ether"),
            }
        )

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    async def asyncTearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_dai_savings_rate_contract(self) -> None:
        print("----==== test_dai_savings_rate_contract ====----")
        # we call the aave3 weth atoken proxy contract in this example
        pool = DaiSavingsRate(
            contract_address=self.contract_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        self.assertTrue(hasattr(pool, "_sdai_contract"))
        self.assertTrue(isinstance(pool._sdai_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_pot_contract"))
        self.assertTrue(isinstance(pool._pot_contract, AsyncContract))

        print(f"sdai contract: {pool._sdai_contract.address}")
        print(f"pot contract: {pool._pot_contract.address}")

        # get supply rate
        supply_rate = await pool.supply_rate()
        print(f"supply rate: {supply_rate}")


class TestMorphoVault(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 20233401
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 20892138,
                    },
                },
            ],
        )

        # Usual Boosted USDC Vault
        self.vault_address = "0xd63070114470f685b75B74D60EEc7c1113d33a3D"
        # USDC whale
        self.user_address = "0x4B16c5dE96EB2117bBE5fd171E4d203624B014aa"
        # Create a funded account for testing
        self.account = Account.create()
        await self.w3.eth.send_transaction(
            {
                "to": self.account.address,
                "from": (await self.w3.eth.accounts)[0],
                "value": self.w3.to_wei(200000, "ether"),
            }
        )

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]

        print(f"snapshot id: {self.snapshot_id}")

    async def asyncTearDown(self) -> None:
        # Create new web3 instance for teardown
        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))

        # Reset the hardhat network
        await w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21080765,
                    },
                },
            ],
        )

        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_morphovault_pool_model(self) -> None:
        print("----==== test_morphovault_pool_model ====----")
        pool = MorphoVault(
            contract_address=self.vault_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        self.assertTrue(hasattr(pool, "_vault_contract"))
        self.assertTrue(isinstance(pool._vault_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_morpho_contract"))
        self.assertTrue(isinstance(pool._morpho_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_decimals"))
        self.assertTrue(isinstance(pool._decimals, int))

        self.assertTrue(hasattr(pool, "_DECIMALS_OFFSET"))
        self.assertTrue(isinstance(pool._DECIMALS_OFFSET, int))

        self.assertTrue(hasattr(pool, "_asset_decimals"))
        self.assertTrue(isinstance(pool._asset_decimals, int))

        self.assertTrue(hasattr(pool, "_total_supplied_assets"))
        self.assertTrue(isinstance(pool._total_supplied_assets, int))
        self.assertTrue(hasattr(pool, "_user_deposits"))
        self.assertTrue(isinstance(pool._user_deposits, int))
        self.assertTrue(hasattr(pool, "_curr_borrows"))
        self.assertTrue(isinstance(pool._curr_borrows, int))

        self.assertTrue(hasattr(pool, "_underlying_asset_contract"))
        self.assertTrue(isinstance(pool._underlying_asset_contract, AsyncContract))
        self.assertTrue(hasattr(pool, "_user_asset_balance"))
        self.assertTrue(isinstance(pool._user_asset_balance, int))
        print(f"user asset balance: {pool._user_asset_balance}")
        self.assertGreater(pool._user_asset_balance, 0)

        self.assertTrue(hasattr(pool, "_yield_index"))
        self.assertTrue(isinstance(pool._yield_index, int))
        print(f"morpho vault share price: {pool._yield_index}")
        self.assertGreater(pool._yield_index, 0)

        # check pool supply_rate
        supply_rate = await pool.supply_rate(0)
        print(f"supply rate: {supply_rate}")

        self.assertTrue(hasattr(pool, "_irm_contracts"))
        self.assertTrue(isinstance(pool._irm_contracts, dict))

    async def test_supply_rate_increase_alloc(self) -> None:
        print("----==== test_supply_rate_increase_alloc ====----")

        pool = MorphoVault(
            contract_address=self.vault_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        # get current balance of the user
        curr_user_shares = await async_retry_with_backoff(pool._vault_contract.functions.balanceOf(self.user_address).call)
        current_balance = await async_retry_with_backoff(pool._vault_contract.functions.convertToAssets(curr_user_shares).call)
        new_balance = current_balance + int(1000000e6)

        apy_before = await pool.supply_rate(current_balance)
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 1000000 USDC
        apy_after = await pool.supply_rate(new_balance)
        print(f"apy after supplying 1000000 USDC: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertLess(apy_after, apy_before)

    async def test_supply_rate_decrease_alloc(self) -> None:
        print("----==== test_supply_rate_decrease_alloc ====----")

        pool = MorphoVault(
            contract_address=self.vault_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        # get current balance of the user
        curr_user_shares = await async_retry_with_backoff(pool._vault_contract.functions.balanceOf(self.user_address).call)
        current_balance = await async_retry_with_backoff(pool._vault_contract.functions.convertToAssets(curr_user_shares).call)
        new_balance = current_balance - int(1000000e6)

        apy_before = await pool.supply_rate(current_balance)
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after removing 1000000 USDC
        apy_after = await pool.supply_rate(new_balance)
        print(f"apy after removing 1000000 USDC: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertGreater(apy_after, apy_before)


class TestYearnV3Vault(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 20233401
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 20976304,
                    },
                },
            ],
        )

        # USDC Vault
        self.vault_address = "0xBe53A109B494E5c9f97b9Cd39Fe969BE68BF6204"
        # yearn usdc vault whale (yearn treasury)
        self.user_address = "0x93A62dA5a14C80f265DAbC077fCEE437B1a0Efde"
        # Create a funded account for testing
        self.account = Account.create()
        await self.w3.eth.send_transaction(
            {
                "to": self.account.address,
                "from": (await self.w3.eth.accounts)[0],
                "value": self.w3.to_wei(200000, "ether"),
            }
        )

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]

        print(f"snapshot id: {self.snapshot_id}")

    async def asyncTearDown(self) -> None:
        # Create new web3 instance for teardown
        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))

        # Reset the hardhat network
        await w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21080765,
                    },
                },
            ],
        )

        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_vault_pool_model(self) -> None:
        print("----==== TestYearnV3Vault | test_vault_pool_model ====----")
        pool = YearnV3Vault(
            contract_address=self.vault_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        self.assertTrue(hasattr(pool, "_vault_contract"))
        self.assertTrue(isinstance(pool._vault_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_apr_oracle"))
        self.assertTrue(isinstance(pool._apr_oracle, AsyncContract))
        self.assertEqual(pool._apr_oracle.address, APR_ORACLE)

        self.assertTrue(hasattr(pool, "_user_deposits"))
        self.assertTrue(isinstance(pool._user_deposits, int))

        self.assertTrue(hasattr(pool, "_user_asset_balance"))
        self.assertTrue(isinstance(pool._user_asset_balance, int))
        print(f"user asset balance: {pool._user_asset_balance}")
        self.assertGreater(pool._user_asset_balance, 0)

        self.assertTrue(hasattr(pool, "_yield_index"))
        self.assertTrue(isinstance(pool._yield_index, int))
        print(f"morpho vault share price: {pool._yield_index}")
        self.assertGreater(pool._yield_index, 0)

        # check pool supply_rate
        supply_rate = await pool.supply_rate(0)
        print(f"supply rate: {supply_rate}")

    async def test_supply_rate_increase_alloc(self) -> None:
        print("----==== TestYearnV3Vault | test_supply_rate_increase_alloc ====----")

        pool = YearnV3Vault(
            contract_address=self.vault_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        # get current balance of the user
        curr_user_shares = await async_retry_with_backoff(pool._vault_contract.functions.balanceOf(self.user_address).call)
        current_balance = await async_retry_with_backoff(pool._vault_contract.functions.convertToAssets(curr_user_shares).call)
        new_balance = current_balance + int(1000000e6)

        apy_before = await pool.supply_rate(current_balance)
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 1000000 USDC
        apy_after = await pool.supply_rate(new_balance)
        print(f"apy after supplying 1000000 USDC: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertLess(apy_after, apy_before)

    async def test_supply_rate_decrease_alloc(self) -> None:
        print("----==== TestYearnV3Vault | test_supply_rate_decrease_alloc ====----")

        pool = YearnV3Vault(
            contract_address=self.vault_address,
            user_address=self.user_address,
        )  # type: ignore[]

        await pool.sync(self.w3)

        # get current balance of the user
        curr_user_shares = await async_retry_with_backoff(pool._vault_contract.functions.balanceOf(self.user_address).call)
        current_balance = await async_retry_with_backoff(pool._vault_contract.functions.convertToAssets(curr_user_shares).call)
        new_balance = current_balance - int(1000000e6)

        apy_before = await pool.supply_rate(current_balance)
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after removing 1000000 USDC
        apy_after = await pool.supply_rate(new_balance)
        print(f"apy after removing 1000000 USDC: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertGreater(apy_after, apy_before)


# TODO: make testaavepool and this test use the same block number but different address
# right now they both use the same pool but from different blocks in the past.
class TestAaveTargetPool(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 20233401
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

        # spark dai
        self.atoken_address = "0x4DEDf26112B3Ec8eC46e7E31EA5e123490B05B8B"
        # Create a funded account for testing
        self.account_address = "0x0Fd6abA4272a96Bb8CcbbA69B825075cb2047D1D"  # spDai holder (~17.5k spDai at time of writing)
        await self.w3.eth.send_transaction(
            {
                "to": self.account_address,
                "from": (await self.w3.eth.accounts)[0],
                "value": self.w3.to_wei(200000, "ether"),
            }
        )

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    async def asyncTearDown(self) -> None:
        # Create new web3 instance for teardown
        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))

        # Reset the hardhat network
        await w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21150770,
                    },
                },
            ],
        )

        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_pool_contract(self) -> None:
        print("----==== test_pool_contract ====----")
        # we call the aave3 weth atoken proxy contract in this example
        pool = AaveV3RateTargetBaseInterestRatePool(
            contract_address=self.atoken_address,
        )

        await pool.pool_init(self.w3)
        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, AsyncContract))

    # TODO: test syncing after time travel
    async def test_sync(self) -> None:
        print("----==== test_sync ====----")
        pool = AaveV3RateTargetBaseInterestRatePool(
            contract_address=self.atoken_address,
        )

        # sync pool params
        await pool.sync(web3_provider=self.w3)

        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, AsyncContract))

        self.assertTrue(hasattr(pool, "_yield_index"))
        self.assertTrue(isinstance(pool._yield_index, int))
        self.assertGreaterEqual(pool._yield_index, int(1e27))
        print(f"normalized income: {pool._yield_index}")

    # TODO: get snapshots working correctly so we are not under the mercy of the automatic ordering of tests
    async def test_supply_rate_alloc(self) -> None:
        print("----==== test_supply_rate_increase_alloc ====----")
        pool = AaveV3RateTargetBaseInterestRatePool(contract_address=self.atoken_address, user_address=self.account_address)

        # sync pool params
        await pool.sync(web3_provider=self.w3)

        reserve_data = await async_retry_with_backoff(
            pool._pool_contract.functions.getReserveData(pool._underlying_asset_address).call
        )

        apy_before = AsyncWeb3.to_wei(reserve_data.currentLiquidityRate / 1e27, "ether")
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 100000 DAI
        apy_after = await pool.supply_rate(int(100000e18))
        print(f"apy after supplying 100000 DAI: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertLess(apy_after, apy_before)

    async def test_supply_rate_decrease_alloc(self) -> None:
        print("----==== test_supply_rate_decrease_alloc ====----")
        pool = AaveV3RateTargetBaseInterestRatePool(contract_address=self.atoken_address, user_address=self.account_address)

        # sync pool params
        await pool.sync(web3_provider=self.w3)

        reserve_data = await async_retry_with_backoff(
            pool._pool_contract.functions.getReserveData(pool._underlying_asset_address).call
        )

        apy_before = AsyncWeb3.to_wei(reserve_data.currentLiquidityRate / 1e27, "ether")
        print(f"apy before rebalancing ether: {apy_before}")

        # calculate predicted future supply rate after removing 100000 DAI to end up with 9000 DAI in the pool
        await pool.sync(self.w3)
        apy_after = await pool.supply_rate(int(9000e18))
        print(f"apy after rebalancing ether: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertGreater(apy_after, apy_before)


if __name__ == "__main__":
    unittest.main()
