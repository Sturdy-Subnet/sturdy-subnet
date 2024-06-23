import unittest
from web3 import Web3
from web3.contract import Contract

# import brownie
# from brownie import network

from sturdy.pools import AaveV3DefaultInterestRatePool
from sturdy.utils.misc import retry_with_backoff


# TODO: test pool_init seperately???
class TestAavePool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # runs tests on local mainnet fork at block: 20018411
        cls.w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        assert cls.w3.is_connected()

    def test_pool_contract(self):
        print("----==== test_pool_contract ====----")
        # we call the aave3 dai atoken proxy contract in this example
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
            contract_address="0x018008bfb33d285247A21d44E50697654f754e63",
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
            contract_address="0x018008bfb33d285247A21d44E50697654f754e63",
        )

        # sync pool params
        pool.sync(web3_provider=self.w3)

        self.assertTrue(hasattr(pool, "_atoken_contract"))
        self.assertTrue(isinstance(pool._atoken_contract, Contract))

        self.assertTrue(hasattr(pool, "_pool_contract"))
        self.assertTrue(isinstance(pool._pool_contract, Contract))

    def test_supply_rate(self):
        print("----==== test_supply_rate ====----")
        pool = AaveV3DefaultInterestRatePool(
            pool_id="test",
            contract_address="0x018008bfb33d285247A21d44E50697654f754e63",
        )

        # sync pool params
        pool.sync(web3_provider=self.w3)

        reserve_data = retry_with_backoff(
            pool._pool_contract.functions.getReserveData(
                pool._underlying_asset_address
            ).call
        )

        apy_before = reserve_data.currentLiquidityRate / 1e27
        print(f"apy before supplying: {apy_before}")

        # calculate predicted future supply rate after supplying 100000 DAI
        apy_after = pool.supply_rate(100000.0)
        print(f"apy after supplying 100000 DAI: {apy_after}")
        self.assertLess(apy_after, apy_before)


if __name__ == "__main__":
    unittest.main()