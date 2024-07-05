import json
from pathlib import Path
import unittest
from web3 import Web3
from web3.contract import Contract
from eth_account import Account

# import brownie
# from brownie import network

import os
from dotenv import load_dotenv

from sturdy.pools import AaveV3DefaultInterestRatePool, VariableInterestSturdySiloStrategy
from sturdy.utils.misc import retry_with_backoff

load_dotenv()
MAINNET_FORKING_URL = os.getenv("MAINNET_FORKING_URL")


# TODO: test pool_init seperately???
class TestAavePool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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

        weth_abi_file_path = Path(__file__).parent / "../../../abi/IWETH.json"
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

        cls.snapshot_id = cls.w3.provider.make_request("evm_snapshot", [])
        print(f"snapshot id: {cls.snapshot_id}")

    def setUp(self):
        self.snapshot_id = self.w3.provider.make_request("evm_snapshot", [])
        print(f"snapshot id: {self.snapshot_id}")

    def tearDown(self):
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        self.w3.provider.make_request("evm_revert", self.snapshot_id)

    def test_pool_contract(self):
        print("----==== test_pool_contract ====----")
        # we call the aave3 weth atoken proxy contract in this example
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
            contract_address=self.atoken_address,
        )

        pool.pool_init(self.w3)
        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, Contract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, Contract))

    # TODO: test syncing after time travel
    def test_sync(self):
        print("----==== test_sync ====----")
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
            contract_address=self.atoken_address,
        )

        # sync pool params
        pool.sync(web3_provider=self.w3)

        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, Contract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, Contract))

    # TODO: get snapshots working correctly so we are not under the mercy of the automatic ordering of tests
    def test_supply_rate_alloc(self):
        print("----==== test_supply_rate_increase_alloc ====----")
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
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

    def test_supply_rate_decrease_alloc(self):
        print("----==== test_supply_rate_decrease_alloc ====----")
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
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
    def setUpClass(cls):
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
            "hardhat_reset",
            [
                {
                    "forking": {
                        "jsonRpcUrl": MAINNET_FORKING_URL,
                        "blockNumber": 20233401,
                    },
                },
            ],
        )

        cls.snapshot_id = cls.w3.provider.make_request("evm_snapshot", [])
        print(f"snapshot id: {cls.snapshot_id}")

    def setUp(self):
        self.snapshot_id = self.w3.provider.make_request("evm_snapshot", [])
        print(f"snapshot id: {self.snapshot_id}")

    def tearDown(self):
        # Optional: Revert to the original snapshot after each test
        print("reverting to original evm snapshot")
        self.w3.provider.make_request("evm_revert", self.snapshot_id)

    def test_silo_strategy_contract(self):
        print("----==== test_pool_contract ====----")
        # we call the aave3 weth atoken proxy contract in this example
        pool = VariableInterestSturdySiloStrategy(
            pool_id="test",
            contract_address=self.contract_address,
        )
        whale_addr = self.w3.to_checksum_address("0x0669091F451142b3228171aE6aD794cF98288124")

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
        prev_supply_rate = pool.supply_rate(whale_addr, int(630e18), self.w3)
        # increase deposit amount to pool by ~100e18 (~630 pxETH)
        supply_rate_increase = pool.supply_rate(whale_addr, int(730e18), self.w3)
        # decrease deposit amount to pool by ~100e18 (~530 pxETH)
        supply_rate_decrease = pool.supply_rate(whale_addr, int(530e18), self.w3)
        print(f"supply rate unchanged: {prev_supply_rate}")
        print(f"supply rate after increasing deposit: {supply_rate_increase}")
        print(f"supply rate after decreasing deposit: {supply_rate_decrease}")
        self.assertLess(supply_rate_increase, prev_supply_rate)
        self.assertGreater(supply_rate_decrease, prev_supply_rate)


if __name__ == "__main__":
    unittest.main()
