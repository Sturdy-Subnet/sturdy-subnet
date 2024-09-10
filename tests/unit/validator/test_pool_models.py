import json
import os
import unittest
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3
from web3.contract.contract import Contract

from sturdy.pools import (
    AaveV3DefaultInterestRatePool,
    CompoundV3Pool,
    DaiSavingsRate,
    VariableInterestSturdySiloStrategy,
)
from sturdy.utils.misc import retry_with_backoff

load_dotenv()
WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL")


# TODO: test pool_init seperately???
class TestAavePool(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # runs tests on local mainnet fork at block: 20233401
        cls.w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        assert cls.w3.is_connected()

        cls.atoken_address = "0x4d5F47FA6A74757f35C14fD3a6Ef8E3C9BC514E8"
        # Create a funded account for testing
        cls.account = Account.create()
        cls.w3.eth.send_transaction(
            {
                "to": cls.account.address,
                "from": cls.w3.eth.accounts[0],
                "value": cls.w3.to_wei(200000, "ether"),
            }
        )

        weth_abi_file_path = Path(__file__).parent / "../../../sturdy/abi/IWETH.json"
        weth_abi_file = weth_abi_file_path.open()
        weth_abi = json.load(weth_abi_file)
        weth_abi_file.close()

        weth_contract = cls.w3.eth.contract(abi=weth_abi)
        cls.weth_contract = retry_with_backoff(
            weth_contract,
            address=Web3.to_checksum_address(
                "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
            ),
        )

        cls.snapshot_id = cls.w3.provider.make_request("evm_snapshot", []) # type: ignore[]
        print(f"snapshot id: {cls.snapshot_id}")

    def setUp(self) -> None:
        self.snapshot_id = self.w3.provider.make_request("evm_snapshot", []) # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    def tearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        self.w3.provider.make_request("evm_revert", self.snapshot_id) # type: ignore[]

    def test_pool_contract(self) -> None:
        print("----==== test_pool_contract ====----")
        # we call the aave3 weth atoken proxy contract in this example
        pool = AaveV3DefaultInterestRatePool(
            contract_address=self.atoken_address,
        )

        pool.pool_init(self.w3)
        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, Contract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, Contract))

    # TODO: test syncing after time travel
    def test_sync(self) -> None:
        print("----==== test_sync ====----")
        pool = AaveV3DefaultInterestRatePool(
            contract_address=self.atoken_address,
        )

        # sync pool params
        pool.sync(web3_provider=self.w3)

        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, Contract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, Contract))

    # TODO: get snapshots working correctly so we are not under the mercy of the automatic ordering of tests
    def test_supply_rate_alloc(self) -> None:
        print("----==== test_supply_rate_increase_alloc ====----")
        pool = AaveV3DefaultInterestRatePool(
            contract_address=self.atoken_address,
        )

        # sync pool params
        pool.sync(web3_provider=self.w3)

        reserve_data = retry_with_backoff(
            pool._pool_contract.functions.getReserveData(
                pool._underlying_asset_address
            ).call
        )

        apy_before = Web3.to_wei(reserve_data.currentLiquidityRate / 1e27, "ether")
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 10000 ETH
        apy_after = pool.supply_rate(self.account.address, int(10000e18))
        print(f"apy after supplying 10000 ETH: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertLess(apy_after, apy_before)

    def test_supply_rate_decrease_alloc(self) -> None:
        print("----==== test_supply_rate_decrease_alloc ====----")
        pool = AaveV3DefaultInterestRatePool(
            contract_address=self.atoken_address,
        )

        # sync pool params
        pool.sync(web3_provider=self.w3)

        tx = self.weth_contract.functions.deposit().build_transaction(
            {
                "from": self.w3.to_checksum_address(self.account.address),
                "gas": 100000,
                "gasPrice": self.w3.eth.gas_price,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "value": self.w3.to_wei(10000, "ether"),
            }
        )

        signed_tx = self.w3.eth.account.sign_transaction(
            transaction_dict=tx, private_key=self.account.key
        )

        # Send the transaction
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"weth deposit tx hash: {tx_hash}")

        # check if we received some weth
        weth_balance = self.weth_contract.functions.balanceOf(
            self.account.address
        ).call()
        self.assertGreaterEqual(int(weth_balance), self.w3.to_wei(10000, "ether"))

        # approve aave pool to use weth
        tx = self.weth_contract.functions.approve(
            pool._pool_contract.address, self.w3.to_wei(1e9, "ether")
        ).build_transaction(
            {
                "from": self.w3.to_checksum_address(self.account.address),
                "gas": 1000000,
                "gasPrice": self.w3.eth.gas_price,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
            }
        )

        signed_tx = self.w3.eth.account.sign_transaction(
            transaction_dict=tx, private_key=self.account.key
        )

        # Send the transaction
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"pool approve weth tx hash: {tx_hash}")

        # deposit tokens into the pool
        tx = pool._pool_contract.functions.supply(
            self.weth_contract.address,
            self.w3.to_wei(10000, "ether"),
            self.account.address,
            0,
        ).build_transaction(
            {
                "from": self.w3.to_checksum_address(self.account.address),
                "gas": 1000000,
                "gasPrice": self.w3.eth.gas_price,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
            }
        )

        signed_tx = self.w3.eth.account.sign_transaction(
            transaction_dict=tx, private_key=self.account.key
        )

        # Send the transaction
        tx_hash = retry_with_backoff(
            self.w3.eth.send_raw_transaction, signed_tx.rawTransaction
        )
        print(f"supply weth tx hash: {tx_hash}")

        reserve_data = retry_with_backoff(
            pool._pool_contract.functions.getReserveData(
                pool._underlying_asset_address
            ).call
        )

        apy_before = Web3.to_wei(reserve_data.currentLiquidityRate / 1e27, "ether")
        print(f"apy before rebalancing ether: {apy_before}")

        # calculate predicted future supply rate after removing 1000 ETH to end up with 9000 ETH in the pool
        apy_after = pool.supply_rate(self.account.address, int(9000e18))
        print(f"apy after rebalancing ether: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertGreater(apy_after, apy_before)


class TestSturdySiloStrategy(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # runs tests on local mainnet fork at block: 20225081
        cls.w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        assert cls.w3.is_connected()

        cls.contract_address = "0x0669091F451142b3228171aE6aD794cF98288124"
        # Create a funded account for testing
        cls.account = Account.create()
        cls.w3.eth.send_transaction(
            {
                "to": cls.account.address,
                "from": cls.w3.eth.accounts[0],
                "value": cls.w3.to_wei(200000, "ether"),
            }
        )

        cls.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": WEB3_PROVIDER_URL,
                        "blockNumber": 20233401,
                    },
                },
            ],
        )

        cls.snapshot_id = cls.w3.provider.make_request("evm_snapshot", []) # type: ignore[]
        print(f"snapshot id: {cls.snapshot_id}")

    def setUp(self) -> None:
        self.snapshot_id = self.w3.provider.make_request("evm_snapshot", []) # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    def tearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        self.w3.provider.make_request("evm_revert", self.snapshot_id) # type: ignore[]

    def test_silo_strategy_contract(self) -> None:
        print("----==== test_pool_contract ====----")
        # we call the aave3 weth atoken proxy contract in this example
        pool = VariableInterestSturdySiloStrategy(
            contract_address=self.contract_address,
        ) # type: ignore[]
        whale_addr = self.w3.to_checksum_address(
            "0x0669091F451142b3228171aE6aD794cF98288124"
        )

        pool.sync(whale_addr, self.w3)

        self.assertTrue(hasattr(pool, "_silo_strategy_contract"))
        self.assertTrue(isinstance(pool._silo_strategy_contract, Contract))
        print(f"silo contract: {pool._silo_strategy_contract.address}")

        self.assertTrue(hasattr(pool, "_pair_contract"))
        self.assertTrue(isinstance(pool._pair_contract, Contract))
        print(f"pair contract: {pool._pair_contract.address}")

        self.assertTrue(hasattr(pool, "_rate_model_contract"))
        self.assertTrue(isinstance(pool._rate_model_contract, Contract))
        print(f"rate model contract: {pool._rate_model_contract.address}")

        # don't change deposit amount to pool by much
        prev_supply_rate = pool.supply_rate(int(630e18))
        # increase deposit amount to pool by ~100e18 (~630 pxETH)
        supply_rate_increase = pool.supply_rate(int(730e18))
        # decrease deposit amount to pool by ~100e18 (~530 pxETH)
        supply_rate_decrease = pool.supply_rate(int(530e18))
        print(f"supply rate unchanged: {prev_supply_rate}")
        print(f"supply rate after increasing deposit: {supply_rate_increase}")
        print(f"supply rate after decreasing deposit: {supply_rate_decrease}")
        self.assertLess(supply_rate_increase, prev_supply_rate)
        self.assertGreater(supply_rate_decrease, prev_supply_rate)


class TestCompoundV3Pool(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # runs tests on local mainnet fork at block: 20233401
        cls.w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        assert cls.w3.is_connected()

        cls.ctoken_address = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        cls.user_address = "0x2b2E894f08F1BF8C93a82297c347EbdC8717d99a"
        # Create a funded account for testing
        cls.account = Account.create()
        cls.w3.eth.send_transaction(
            {
                "to": cls.account.address,
                "from": cls.w3.eth.accounts[0],
                "value": cls.w3.to_wei(200000, "ether"),
            }
        )

        cls.snapshot_id = cls.w3.provider.make_request("evm_snapshot", []) # type: ignore[]
        print(f"snapshot id: {cls.snapshot_id}")

    def setUp(self) -> None:
        self.snapshot_id = self.w3.provider.make_request("evm_snapshot", []) # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    def tearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        self.w3.provider.make_request("evm_revert", self.snapshot_id) # type: ignore[]

    def test_compound_pool_model(self) -> None:
        print("----==== test_compound_pool_model ====----")
        pool = CompoundV3Pool(
            contract_address=self.ctoken_address,
            user_address=self.user_address,
        ) # type: ignore[]

        pool.sync(self.w3)

        self.assertTrue(hasattr(pool, "_ctoken_contract"))
        self.assertTrue(isinstance(pool._ctoken_contract, Contract))

        self.assertTrue(hasattr(pool, "_base_oracle_contract"))
        self.assertTrue(isinstance(pool._base_oracle_contract, Contract))

        self.assertTrue(hasattr(pool, "_reward_oracle_contract"))
        self.assertTrue(isinstance(pool._reward_oracle_contract, Contract))

        self.assertTrue(hasattr(pool, "_base_token_price"))
        self.assertTrue(isinstance(pool._base_token_price, float))

        self.assertTrue(hasattr(pool, "_reward_token_price"))
        self.assertTrue(isinstance(pool._reward_token_price, float))

        # check pool supply_rate
        pool.supply_rate(0)

    def test_supply_rate_increase_alloc(self) -> None:
        print("----==== test_supply_rate_increase_alloc ====----")

        pool = CompoundV3Pool(
            contract_address=self.ctoken_address,
            user_address=self.user_address,
        ) # type: ignore[]

        pool.sync(self.w3)

        # get current balance of the user
        current_balance = pool._ctoken_contract.functions.balanceOf(
            self.user_address
        ).call()
        new_balance = current_balance + int(1000000e6)

        apy_before = pool.supply_rate(current_balance)
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 1000000 USDC
        apy_after = pool.supply_rate(new_balance)
        print(f"apy after supplying 1000000 USDC: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertLess(apy_after, apy_before)

    def test_supply_rate_decrease_alloc(self) -> None:
        print("----==== test_supply_rate_decrease_alloc ====----")

        pool = CompoundV3Pool(
            contract_address=self.ctoken_address,
            user_address=self.user_address,
        ) # type: ignore[]

        pool.sync(self.w3)

        # get current balance of the user
        current_balance = pool._ctoken_contract.functions.balanceOf(
            self.user_address
        ).call()
        new_balance = current_balance - int(1000000e6)

        apy_before = pool.supply_rate(current_balance)
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after removing 1000000 USDC
        apy_after = pool.supply_rate(new_balance)
        print(f"apy after removing 1000000 USDC: {apy_after}")
        self.assertNotEqual(apy_after, 0)
        self.assertGreater(apy_after, apy_before)


class TestDaiSavingsRate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # runs tests on local mainnet fork at block: 20225081
        cls.w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        assert cls.w3.is_connected()
        cls.contract_address = cls.w3.to_checksum_address(
            "0x83f20f44975d03b1b09e64809b757c47f942beea"
        )
        # Create a funded account for testing
        cls.account = Account.create()
        cls.w3.eth.send_transaction(
            {
                "to": cls.account.address,
                "from": cls.w3.eth.accounts[0],
                "value": cls.w3.to_wei(200000, "ether"),
            }
        )

        cls.w3.provider.make_request(
            "hardhat_reset", # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": WEB3_PROVIDER_URL,
                        "blockNumber": 20233401,
                    },
                },
            ],
        )

        cls.snapshot_id = cls.w3.provider.make_request("evm_snapshot", []) # type: ignore[]
        print(f"snapshot id: {cls.snapshot_id}")

    def setUp(self) -> None:
        self.snapshot_id = self.w3.provider.make_request("evm_snapshot", []) # type: ignore[]
        print(f"snapshot id: {self.snapshot_id}")

    def tearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        self.w3.provider.make_request("evm_revert", self.snapshot_id) # type: ignore[]

    def test_dai_savings_rate_contract(self) -> None:
        print("----==== test_dai_savings_rate_contract ====----")
        # we call the aave3 weth atoken proxy contract in this example
        pool = DaiSavingsRate(
            contract_address=self.contract_address,
        ) # type: ignore[]

        pool.sync(self.w3)

        self.assertTrue(hasattr(pool, "_sdai_contract"))
        self.assertTrue(isinstance(pool._sdai_contract, Contract))

        self.assertTrue(hasattr(pool, "_pot_contract"))
        self.assertTrue(isinstance(pool._pot_contract, Contract))

        print(f"sdai contract: {pool._sdai_contract.address}")
        print(f"pot contract: {pool._pot_contract.address}")

        # get supply rate
        supply_rate = pool.supply_rate()
        print(f"supply rate: {supply_rate}")


if __name__ == "__main__":
    unittest.main()
