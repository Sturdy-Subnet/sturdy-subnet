import os
import unittest
from web3 import Web3
from web3.contract import Contract

# import brownie
# from brownie import network

from sturdy.pools import AaveV3DefaultInterestRatePool
from sturdy.utils.misc import retry_with_backoff


class TestAavePool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ.get("WEB3_PROVIDER_URL")
        # network.connect("development")
        cls.w3 = Web3(Web3.HTTPProvider(cls.url))
        assert cls.w3.is_connected()

    def test_pool_contract(self):
        print("----==== test_pool_contract ====----")
        # we call the aave3 dai atoken proxy contract in this example
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
            contract_address="0x018008bfb33d285247A21d44E50697654f754e63",
            web3_provider=self.w3,
        )

        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, Contract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, Contract))

    # TODO: test syncing after time travel
    def test_sync(self):
        print("----==== test_sync ====----")
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
            contract_address="0x018008bfb33d285247A21d44E50697654f754e63",
            web3_provider=self.w3,
        )

        # sync pool params
        pool.sync()

        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, Contract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, Contract))

    def test_supply_apy(self):
        print("----==== test_supply_apy ====----")
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
            contract_address="0x018008bfb33d285247A21d44E50697654f754e63",
            web3_provider=self.w3,
        )

        # sync pool params
        pool.sync()

        reserve_data = retry_with_backoff(
            pool._pool_contract.functions.getReserveData(
                pool._underlying_asset_address
            ).call
        )

        apy_before = reserve_data.currentLiquidityRate / 1e27
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 1000 DAI
        apy_after = pool.supply_apy(int(1e23))
        print(f"apy after supplying 100000 DAI: {apy_after}")
        self.assertLess(apy_after, apy_before)


if __name__ == "__main__":
    unittest.main()
