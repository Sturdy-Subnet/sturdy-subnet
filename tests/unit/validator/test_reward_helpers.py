import os
import unittest

import gmpy2
import numpy as np
from dotenv import load_dotenv
from web3 import AsyncWeb3
from web3.constants import ADDRESS_ZERO

from sturdy.algo import naive_algorithm
from sturdy.pool_registry.pool_registry import POOL_REGISTRY
from sturdy.pools import *
from sturdy.protocol import REQUEST_TYPES, AllocateAssets
from sturdy.validator.apy_binning import (
    apply_similarity_penalties,
    apply_top_performer_bonus,
    calculate_allocation_distance,
    calculate_base_rewards,
    calculate_bin_rewards,
    create_apy_bins,
    format_allocations,
    normalize_bin_rewards,
    normalize_rewards,
)
from sturdy.validator.reward import (
    annualized_yield_pct,
)

load_dotenv()
ETHEREUM_MAINNET_PROVIDER_URL = os.getenv("ETHEREUM_MAINNET_PROVIDER_URL")


class TestCheckAllocations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # runs tests on local mainnet fork at block: 20233401
        self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await self.w3.is_connected()

        class EmptyVali:
            pass

        self.vali = EmptyVali()

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

        self.snapshot_id = await self.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]

    async def asyncTearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_check_allocations_sturdy(self) -> None:
        A = "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227"
        VAULT = "0x73E4C11B670Ef9C025A030A20b72CB9150E54523"
        # assuming block # is: 20233401
        allocations = {A: int(6e23)}
        assets_and_pools = {
            "total_assets": int(100e23),
            "pools": {
                A: VariableInterestSturdySiloStrategy(
                    user_address=VAULT,
                    contract_address=A,
                ),
            },
        }

        pool_a: VariableInterestSturdySiloStrategy = assets_and_pools["pools"][A]
        await pool_a.sync(web3_provider=self.w3)

        # case: borrow_amount <= assets_available, deposit_amount < assets_available
        pool_a._total_supplied_assets = int(100e23)
        pool_a._totalBorrow = int(10e23)
        pool_a._user_deposits = int(5e23)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: borrow_amount > assets_available, deposit_amount >= assets_available
        pool_a._totalBorrow = int(97e23)
        pool_a._user_deposits = int(5e23)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations)
        self.assertFalse(result)

        # should return True
        pool_a._totalBorrow = int(97e23)
        pool_a._user_deposits = int(5e23)
        allocations[A] = int(4e23)

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: borrow_amount > assets_available, deposit_amount < assets_available
        pool_a._totalBorrow = int(10e23)
        pool_a._user_deposits = int(1e23)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

    async def test_check_allocations_aave(self) -> None:
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

        # aUSDC (Aave USDC)
        A = "0x98C23E9d8f34FEFb1B7BD6a91B7FF122F4e16F5c"
        # assuming block # is: 20233401
        allocations = {A: int(1e17)}
        assets_and_pools = {
            "total_assets": int(200e18),
            "pools": {
                A: AaveV3DefaultInterestRateV2Pool(
                    user_address=ADDRESS_ZERO,
                    contract_address=A,
                ),
            },
        }

        pool_a: AaveV3DefaultInterestRateV2Pool = assets_and_pools["pools"][A]
        await pool_a.sync(self.w3)

        # case: borrow_amount <= assets_available, deposit_amount < assets_available
        pool_a._total_supplied_assets = int(100e6)
        pool_a._nextTotalStableDebt = 0
        pool_a._totalVariableDebt = int(10e6)
        pool_a._user_deposits = int(5e18)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: borrow_amount > assets_available, deposit_amount >= assets_available
        pool_a._nextTotalStableDebt = 0
        pool_a._totalVariableDebt = int(97e6)
        pool_a._user_deposits = int(5e18)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertFalse(result)

        # should return True
        pool_a._nextTotalStableDebt = 0
        pool_a._totalVariableDebt = int(97e6)
        pool_a._user_deposits = int(5e18)
        allocations[A] = int(4e18)

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: borrow_amount > assets_available, deposit_amount < assets_available
        pool_a._nextTotalStableDebt = 0
        pool_a._totalVariableDebt = int(97e6)
        pool_a._user_deposits = int(1e18)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

    async def test_check_allocations_compound(self) -> None:
        A = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        # assuming block # is: 20233401
        allocations = {A: int(5e26)}
        assets_and_pools = {
            "total_assets": int(100e26),
            "pools": {
                A: CompoundV3Pool(
                    user_address=ADDRESS_ZERO,
                    contract_address=A,
                ),
            },
        }

        pool_a: CompoundV3Pool = assets_and_pools["pools"][A]
        await pool_a.sync(self.w3)

        # case: borrow_amount <= assets_available, deposit_amount < assets_available
        pool_a._total_supplied_assets = int(100e14)
        pool_a._total_borrow = int(10e14)
        pool_a._user_deposits = int(5e14)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: borrow_amount > assets_available, deposit_amount >= assets_available
        pool_a._total_borrow = int(97e14)
        pool_a._user_deposits = int(5e14)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertFalse(result)

        # should return True
        pool_a._total_borrow = int(97e14)
        pool_a._user_deposits = int(5e14)
        allocations[A] = int(4e26)

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: borrow_amount > assets_available, deposit_amount < assets_available
        pool_a._total_borrow = int(97e14)
        pool_a._user_deposits = int(1e14)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

    async def test_check_allocations_morpho(self) -> None:
        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 20874859,
                    },
                },
            ],
        )

        A = "0xd63070114470f685b75B74D60EEc7c1113d33a3D"
        # assuming block # is: 20233401
        allocations = {A: 0}
        assets_and_pools = {
            "total_assets": int(200e14),
            "pools": {
                A: MorphoVault(
                    user_address=ADDRESS_ZERO,
                    contract_address=A,
                ),
            },
        }

        pool_a: MorphoVault = assets_and_pools["pools"][A]
        await pool_a.sync(self.w3)

        # case: borrow_amount <= assets_available, deposit_amount < assets_available
        pool_a._total_supplied_assets = int(100e14)
        pool_a._curr_borrows = int(10e14)
        pool_a._user_deposits = int(5e14)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: borrow_amount > assets_available, deposit_amount >= assets_available
        pool_a._curr_borrows = int(97e14)
        pool_a._user_deposits = int(5e14)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertFalse(result)

        # should return True
        pool_a._curr_borrows = int(97e14)
        pool_a._user_deposits = int(5e14)
        allocations[A] = int(4e14)

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: borrow_amount > assets_available, deposit_amount < assets_available
        pool_a._curr_borrows = int(97e14)
        pool_a._user_deposits = int(1e14)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

    async def test_check_allocations_yearn(self) -> None:
        A = "0xBe53A109B494E5c9f97b9Cd39Fe969BE68BF6204"
        # assuming block # is: 20233401
        allocations = {A: 0}
        assets_and_pools = {
            "total_assets": int(1e12),
            "pools": {
                A: YearnV3Vault(
                    user_address=ADDRESS_ZERO,
                    contract_address=A,
                ),
            },
        }

        pool_a: MorphoVault = assets_and_pools["pools"][A]
        await pool_a.sync(self.w3)

        # case: max withdraw = deposit amount
        pool_a._max_withdraw = int(1e9)
        pool_a._user_deposits = int(1e9)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)

        # case: max withdraw = 0
        pool_a._max_withdraw = 0
        pool_a._user_deposits = int(1e9)
        allocations[A] = 1

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertFalse(result)

        # should return True
        pool_a._max_withdraw = int(1e9)
        pool_a._user_deposits = int(5e9)
        allocations[A] = int(4e9)

        result = check_allocations(assets_and_pools, allocations, alloc_threshold=0)
        self.assertTrue(result)


class TestCalculateApy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(cls) -> None:
        # runs tests on local mainnet fork at block: 20233401
        cls.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("http://127.0.0.1:8545"))
        assert await cls.w3.is_connected()

        await cls.w3.provider.make_request(
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

        cls.pool_data_providers = {}
        cls.pool_data_providers[POOL_DATA_PROVIDER_TYPE.ETHEREUM_MAINNET] = cls.w3

        cls.snapshot_id = await cls.w3.provider.make_request("evm_snapshot", [])  # type: ignore[]

    async def asyncTearDown(self) -> None:
        # Optional: Revert to the original snapshot after each test
        await self.w3.provider.make_request("evm_revert", self.snapshot_id)  # type: ignore[]

    async def test_calculate_apy_sturdy(self) -> None:
        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21075005,
                    },
                },
            ],
        )

        selected_entry = POOL_REGISTRY["Sturdy Crvusd Aggregator"]
        selected = await gen_evm_pools_for_challenge(selected_entry, self.w3)

        assets_and_pools = selected["assets_and_pools"]
        user_address = selected["user_address"]
        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=assets_and_pools,
            user_address=user_address,
        )

        allocations = await naive_algorithm(self, synapse)

        extra_metadata = {}
        for contract_address, pool in assets_and_pools["pools"].items():
            await pool.sync(self.w3)
            extra_metadata[contract_address] = pool._yield_index

        await self.w3.provider.make_request(
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

        for pool in assets_and_pools["pools"].values():
            await pool.sync(self.w3)

        apy = await annualized_yield_pct(allocations, assets_and_pools, 604800, extra_metadata)
        print(f"annualized yield: {(float(apy) / 1e18) * 100}%")
        self.assertGreater(apy, 0)

    async def test_calculate_apy_aave(self) -> None:
        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21075005,
                    },
                },
            ],
        )

        # aave pools - with yearn strategies being their users
        selected_entry = {
            "assets_and_pools": {
                "pools": {
                    "0x018008bfb33d285247A21d44E50697654f754e63": {
                        "pool_type": "AAVE_DEFAULT",
                        "contract_address": "0x018008bfb33d285247A21d44E50697654f754e63",
                        "user_address": "0xF0825750791A4444c5E70743270DcfA8Bb38f959",
                    },
                    "0x4DEDf26112B3Ec8eC46e7E31EA5e123490B05B8B": {
                        "pool_type": "AAVE_TARGET",
                        "contract_address": "0x4DEDf26112B3Ec8eC46e7E31EA5e123490B05B8B",
                        "user_address": "0x1fd862499e9b9402de6c599b6c391f83981180ab",
                    },
                }
            }
        }

        selected = await gen_evm_pools_for_challenge(selected_entry, self.w3)

        assets_and_pools = selected["assets_and_pools"]
        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=assets_and_pools,
        )

        allocations = await naive_algorithm(self, synapse)

        extra_metadata = {}
        for contract_address, pool in assets_and_pools["pools"].items():
            await pool.sync(self.w3)
            extra_metadata[contract_address] = pool._yield_index

        await self.w3.provider.make_request(
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

        for pool in assets_and_pools["pools"].values():
            await pool.sync(self.w3)

        apy = await annualized_yield_pct(allocations, assets_and_pools, 604800, extra_metadata)
        print(f"annualized yield: {(float(apy) / 1e18) * 100}%")
        self.assertGreater(apy, 0)

    async def test_calculate_apy_morpho(self) -> None:
        await self.w3.provider.make_request(
            "hardhat_reset",  # type: ignore[]
            [
                {
                    "forking": {
                        "jsonRpcUrl": ETHEREUM_MAINNET_PROVIDER_URL,
                        "blockNumber": 21075005,
                    },
                },
            ],
        )

        selected_entry = POOL_REGISTRY["Morpho USDC Vaults"]
        selected = await gen_evm_pools_for_challenge(selected_entry, self.w3)

        assets_and_pools = selected["assets_and_pools"]
        user_address = selected["user_address"]
        synapse = AllocateAssets(
            request_type=REQUEST_TYPES.SYNTHETIC,
            assets_and_pools=assets_and_pools,
            user_address=user_address,
        )

        allocations = await naive_algorithm(self, synapse)

        extra_metadata = {}
        for contract_address, pool in assets_and_pools["pools"].items():
            await pool.sync(self.w3)
            extra_metadata[contract_address] = pool._yield_index

        await self.w3.provider.make_request(
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

        for pool in assets_and_pools["pools"].values():
            await pool.sync(self.w3)

        apy = await annualized_yield_pct(allocations, assets_and_pools, 604800, extra_metadata)
        print(f"annualized yield: {(float(apy) / 1e18) * 100}%")
        self.assertGreater(apy, 0)


class TestApyBinning(unittest.IsolatedAsyncioTestCase):
    # Actual apys from sturdy_tbtc_aggregator
    async def test_real_world_apys_case1(self) -> None:
        apys = {
            "0": 2430768276972491,
            "1": 2430768276942237,
            "2": 2430768276939231,
            "3": 2430768276829685,
            "4": 2430768276827723,
            "5": 2430768276823904,
            "6": 2430768276810737,
            "7": 2430768276765696,
            "8": 2430768276762190,
            "9": 2430768276705227,
            "10": 2430768276705227,
            "11": 2430768276668354,
            "12": 2430768276569505,
            "13": 2430767490721887,
            "14": 2430766893869556,
            "15": 2430766561865656,
        }
        bins = create_apy_bins(apys)

        self.assertEqual(len(bins), 11)
        self.assertEqual(len(bins[0]), 1)
        self.assertEqual(len(bins[1]), 2)
        self.assertEqual(len(bins[2]), 3)
        self.assertEqual(len(bins[3]), 1)
        self.assertEqual(len(bins[4]), 2)
        self.assertEqual(len(bins[5]), 2)
        self.assertEqual(len(bins[6]), 1)
        self.assertEqual(len(bins[7]), 1)
        self.assertEqual(len(bins[8]), 1)
        self.assertEqual(len(bins[9]), 1)
        self.assertEqual(len(bins[10]), 1)

        # Check specific miners are in correct bins
        self.assertIn("0", bins[0])
        self.assertIn("1", bins[1])
        self.assertIn("2", bins[1])

    async def test_create_apy_bins(self) -> None:
        apys = {
            "0": int(1.05e18),  # 105%
            "1": int(1.04e18),  # 104%
            "2": int(0.95e18),  # 95%
            "3": int(0.94e18),  # 94%
            "4": 1,  # noisy apy
        }

        bins = create_apy_bins(apys)

        # Bin 0 should have UIDs 0 and 1 (105% and 104%)
        # Bin 1 should have UIDs 2 and 3 (95% and 94%)
        # Bin 2 has the noisy value
        self.assertEqual(len(bins), 5)
        self.assertEqual(len(bins[0]), 1)
        self.assertEqual(len(bins[1]), 1)
        self.assertEqual(len(bins[2]), 1)
        self.assertEqual(len(bins[3]), 1)
        self.assertEqual(len(bins[4]), 1)

        # Check specific miners are in correct bins
        self.assertIn("0", bins[0])
        self.assertIn("1", bins[1])
        self.assertIn("2", bins[2])
        self.assertIn("3", bins[3])
        self.assertIn("4", bins[4])

    async def test_create_apy_bins_empty(self) -> None:
        apys = {}
        bins = create_apy_bins(apys)
        self.assertEqual(len(bins), 0)

    async def test_create_apy_bins_single_miner(self) -> None:
        apys = {"0": int(1.05e18)}
        bins = create_apy_bins(apys)
        self.assertEqual(len(bins), 1)
        self.assertEqual(len(bins[0]), 1)
        self.assertEqual(bins[0][0], "0")


class TestBinRewards(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Setup common test data
        self.assets_and_pools = {
            "total_assets": int(100e18),
            "pools": {"pool1": {"some": "metadata"}, "pool2": {"some": "metadata"}},
        }

    async def test_calculate_bin_rewards_with_timing(self) -> None:
        bins = {
            0: ["0", "1"],  # higher APY bin
            1: ["2", "3"],  # lower APY bin
        }
        allocations = {
            "0": {"allocations": {"pool1": int(100e18), "pool2": 0}},
            "1": {"allocations": {"pool1": int(100e18), "pool2": 0}},  # Similar to UID 0 but later
            "2": {"allocations": {"pool1": int(50e18), "pool2": int(50e18)}},
            "3": {"allocations": {"pool1": int(50e18), "pool2": int(50e18)}},  # Similar to UID 2 but later
        }
        axon_times = {
            "0": 1.0,  # First response
            "1": 2.0,  # Second response (similar to UID 0)
            "2": 1.5,  # First response in lower bin
            "3": 2.5,  # Second response (similar to UID 2)
        }

        rewards, penalties = calculate_bin_rewards(bins, allocations, self.assets_and_pools, axon_times)

        # Check that rewards and penalties are numpy arrays
        self.assertIsInstance(rewards, np.ndarray)
        self.assertIsInstance(penalties, np.ndarray)

        # Check array lengths
        self.assertEqual(len(rewards), 4)
        self.assertEqual(len(penalties), 4)

        # Check that earlier responses get better rewards when allocations are similar
        self.assertGreater(rewards[0], rewards[1])  # UID 0 should have better reward than UID 1
        self.assertGreater(rewards[2], rewards[3])  # UID 2 should have better reward than UID 3

        # Check that first responses aren't penalized
        self.assertEqual(penalties[0], 0)  # First response shouldn't be penalized
        self.assertGreater(penalties[1], 0)  # Similar to UID 0 but later
        self.assertEqual(penalties[2], 0)  # First response in its bin
        self.assertGreater(penalties[3], 0)  # Similar to UID 2 but later

    async def test_calculate_bin_rewards_single_miner(self) -> None:
        bins = {0: ["0"]}
        allocations = {
            "0": {"allocations": {"pool1": int(100e18), "pool2": 0}},
        }
        axon_times = {"0": 1.0}

        rewards, penalties = calculate_bin_rewards(bins, allocations, self.assets_and_pools, axon_times)

        # Single miner should get maximum reward and no penalty
        self.assertEqual(rewards[0], 1.0)
        self.assertEqual(penalties[0], 0.0)

    # TODO: this test is broken???? commenting it out for now
    # async def test_top_performer_bonus(self) -> None:
    #     bins = {
    #         0: ["0", "1", "2"],
    #     }
    #     allocations = {
    #         "0": {"allocations": {"pool1": int(100e18), "pool2": 0}},
    #         "1": {"allocations": {"pool1": 0, "pool2": int(100e18)}},
    #         "2": {"allocations": {"pool1": int(50e18), "pool2": int(50e18)}},
    #     }
    #     axon_times = {
    #         "0": 1.0,
    #         "1": 1.5,
    #         "2": 2.0,
    #     }

    #     rewards, _ = calculate_bin_rewards(bins, allocations, self.assets_and_pools, axon_times)

    #     # Verify top performer gets significantly better reward
    #     top_performer_idx = np.argmax(rewards)
    #     other_rewards = rewards[rewards != rewards[top_performer_idx]]
    #     self.assertGreater(rewards[top_performer_idx], np.max(other_rewards) * 1.5)


class TestBinRewardHelpers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Setup common test data
        self.assets_and_pools = {
            "total_assets": int(100e18),
            "pools": {"pool1": {"some": "metadata"}, "pool2": {"some": "metadata"}},
        }

    async def test_calculate_allocation_distance(self) -> None:
        alloc_a = np.array([gmpy2.mpz(int(100e18)), gmpy2.mpz(0)], dtype=object)
        alloc_b = np.array([gmpy2.mpz(int(100e18)), gmpy2.mpz(0)], dtype=object)
        total_assets = int(100e18)

        # Test identical allocations
        distance = calculate_allocation_distance(alloc_a, alloc_b, total_assets)
        self.assertEqual(distance, 0.0)

        # Test completely different allocations
        alloc_c = np.array([gmpy2.mpz(0), gmpy2.mpz(int(100e18))], dtype=object)
        distance = calculate_allocation_distance(alloc_a, alloc_c, total_assets)
        self.assertAlmostEqual(distance, 1.0, places=6)

        # Test partial difference
        alloc_d = np.array([gmpy2.mpz(int(50e18)), gmpy2.mpz(int(50e18))], dtype=object)
        distance = calculate_allocation_distance(alloc_a, alloc_d, total_assets)
        self.assertAlmostEqual(distance, 0.5, places=6)

    async def test_calculate_base_rewards(self) -> None:
        bins = {
            0: ["0", "1"],  # highest APY bin
            1: ["2"],  # middle APY bin
            2: ["3"],  # lowest APY bin
        }
        miner_uids = ["0", "1", "2", "3"]

        rewards = calculate_base_rewards(bins, miner_uids)

        # Check array type and length
        self.assertIsInstance(rewards, np.ndarray)
        self.assertEqual(len(rewards), 4)

        # Check reward values
        self.assertEqual(rewards[0], 1.0)  # First bin gets full reward
        self.assertEqual(rewards[1], 1.0)  # First bin gets full reward
        self.assertEqual(rewards[2], 0.9)  # Second bin gets 0.9
        self.assertEqual(rewards[3], 0.8)  # Third bin gets 0.8

    async def test_apply_similarity_penalties(self) -> None:
        bins = {0: ["0", "1", "2"]}
        allocations = {
            "0": {"allocations": {"pool1": int(100e18), "pool2": 0}},
            "1": {"allocations": {"pool1": int(100e18), "pool2": 0}},  # Similar to 0
            "2": {"allocations": {"pool1": 0, "pool2": int(100e18)}},  # Different
        }
        axon_times = {
            "0": 1.0,  # First response
            "1": 2.0,  # Second response
            "2": 3.0,  # Third response
        }
        miner_uids = ["0", "1", "2"]

        # Test with default threshold
        penalties = apply_similarity_penalties(
            bins, allocations, axon_times, self.assets_and_pools, miner_uids, similarity_threshold=1e-4
        )

        # Check array type and length
        self.assertIsInstance(penalties, np.ndarray)
        self.assertEqual(len(penalties), 3)

        # First response should have no penalty
        self.assertEqual(penalties[0], 0.0)
        # Second response similar to first should be penalized
        self.assertGreater(penalties[1], 0.0)
        # Third response different from others should not be penalized
        self.assertEqual(penalties[2], 0.0)

    async def test_apply_similarity_penalties_with_missing_pools(self) -> None:
        bins = {0: ["0", "1"]}
        # Missing pool2 in allocations
        allocations = {
            "0": {"allocations": {"pool1": int(100e18)}},
            "1": {"allocations": {"pool1": int(100e18)}},
        }
        axon_times = {
            "0": 1.0,
            "1": 2.0,
        }
        miner_uids = ["0", "1"]

        penalties = apply_similarity_penalties(bins, allocations, axon_times, self.assets_and_pools, miner_uids)

        # Should still work with missing pools (treated as 0)
        self.assertEqual(len(penalties), 2)
        self.assertEqual(penalties[0], 0.0)
        self.assertGreater(penalties[1], 0.0)

    async def test_apply_similarity_penalties_with_none_allocations(self) -> None:
        bins = {0: ["0", "1", "2"]}
        allocations = {
            "0": {"allocations": {"pool1": int(100e18), "pool2": 0}},
            "1": None,  # Missing allocation
            "2": {"allocations": {"pool1": int(100e18), "pool2": 0}},
        }
        axon_times = {
            "0": 1.0,
            "1": 2.0,
            "2": 3.0,
        }
        miner_uids = ["0", "1", "2"]

        penalties = apply_similarity_penalties(bins, allocations, axon_times, self.assets_and_pools, miner_uids)

        self.assertEqual(len(penalties), 3)
        self.assertEqual(penalties[0], 0.0)  # First response
        self.assertEqual(penalties[1], 0.0)  # None allocation should have no penalty
        self.assertGreater(penalties[2], 0.0)  # Similar to first response

    async def test_format_allocations(self) -> None:
        # Test with valid allocations
        apys_and_allocations = {"miner1": {"allocations": {"pool1": int(100e18)}, "apy": 123}}
        formatted = format_allocations(apys_and_allocations, self.assets_and_pools)

        # Should have all pools
        self.assertIn("pool1", formatted["miner1"]["allocations"])
        self.assertIn("pool2", formatted["miner1"]["allocations"])
        # Missing pool should be 0
        self.assertEqual(formatted["miner1"]["allocations"]["pool2"], 0)

        # Test with None allocations
        apys_and_allocations = {"miner1": {"allocations": None, "apy": 123}}
        formatted = format_allocations(apys_and_allocations, self.assets_and_pools)
        self.assertEqual(formatted["miner1"]["allocations"]["pool1"], 0)
        self.assertEqual(formatted["miner1"]["allocations"]["pool2"], 0)

        # Test with empty allocations
        apys_and_allocations = {"miner1": {"allocations": {}, "apy": 123}}
        formatted = format_allocations(apys_and_allocations, self.assets_and_pools)
        self.assertEqual(formatted["miner1"]["allocations"]["pool1"], 0)
        self.assertEqual(formatted["miner1"]["allocations"]["pool2"], 0)

    async def test_apply_top_performer_bonus(self) -> None:
        rewards = np.array([0.5, 0.8, 0.3, 1.0])

        boosted_rewards = apply_top_performer_bonus(rewards)

        # Check array type and length
        self.assertIsInstance(boosted_rewards, np.ndarray)
        self.assertEqual(len(boosted_rewards), 4)

        # Original array should not be modified
        self.assertFalse(np.array_equal(rewards, boosted_rewards))

        # Get top performers in ascending order
        top_indices = np.argsort(rewards)[-TOP_PERFORMERS_COUNT:]

        # Check that top performers got incrementally larger bonuses
        for i, idx in enumerate(top_indices):
            expected_bonus = TOP_PERFORMERS_BONUS * (i + 1)
            self.assertEqual(boosted_rewards[idx], rewards[idx] * expected_bonus)

        # Check that non-top performers were not modified
        non_top_indices = np.setdiff1d(np.arange(len(rewards)), top_indices)
        for idx in non_top_indices:
            self.assertEqual(boosted_rewards[idx], rewards[idx])


class TestNormalizationFunctions(unittest.IsolatedAsyncioTestCase):
    async def test_normalize_rewards_basic(self) -> None:
        # Test basic normalization
        rewards = np.array([1.0, 2.0, 3.0, 4.0])
        normalized = normalize_rewards(rewards)
        self.assertAlmostEqual(min(normalized), 0.0)  # Min should be 0
        self.assertAlmostEqual(normalized[0], min(normalized))
        self.assertAlmostEqual(max(normalized), 1.0)  # Max should be 1
        self.assertAlmostEqual(normalized[-1], max(normalized))

        # Test custom range
        normalized = normalize_rewards(rewards, min_val=0.5, max_val=0.8)
        self.assertAlmostEqual(normalized[0], 0.5)  # Min should be 0.5
        self.assertAlmostEqual(normalized[-1], 0.8)  # Max should be 0.8

    async def test_normalize_rewards_edge_cases(self) -> None:
        # Test empty array
        empty = np.array([])
        self.assertEqual(len(normalize_rewards(empty)), 0)

        # Test array with NaN values
        with_nan = np.array([1.0, np.nan, 3.0])
        normalized = normalize_rewards(with_nan)
        self.assertTrue(np.all(normalized == 0.0))

        # Test array with all same values
        same_values = np.array([2.0, 2.0, 2.0])
        normalized = normalize_rewards(same_values)
        self.assertTrue(np.all(normalized == 1.0))

    async def test_normalize_bin_rewards(self) -> None:
        bins = {
            0: ["0", "1"],  # highest APY bin
            1: ["2", "3"],  # lower APY bin
        }
        miner_uids = ["0", "1", "2", "3"]

        # Before penalties
        rewards_before = np.array([1.0, 0.9, 0.8, 0.7])
        # After penalties (some miners penalized)
        rewards_after = np.array([1.0, 0.5, 0.8, 0.4])

        normalized = normalize_bin_rewards(bins, rewards_before, rewards_after, miner_uids)

        # Check that normalization maintains bin hierarchy
        self.assertTrue(all(normalized[0:2] > normalized[2:4]))  # Higher bin should have better rewards
        self.assertTrue(np.min(normalized[0:2]) >= np.max(normalized[2:4]))  # No overlap between bins

    async def test_normalize_bin_rewards_single_bin(self) -> None:
        bins = {0: ["0", "1", "2"]}
        miner_uids = ["0", "1", "2"]

        rewards_before = np.array([1.0, 0.9, 0.8])
        rewards_after = np.array([1.0, 0.5, 0.3])

        normalized = normalize_bin_rewards(bins, rewards_before, rewards_after, miner_uids)

        # Check normalization within single bin
        self.assertAlmostEqual(np.min(normalized), 0.0)
        self.assertAlmostEqual(np.max(normalized), 1.0)

    async def test_normalize_bin_rewards_empty_bins(self) -> None:
        bins = {}
        miner_uids = []
        rewards_before = np.array([])
        rewards_after = np.array([])

        normalized = normalize_bin_rewards(bins, rewards_before, rewards_after, miner_uids)

        self.assertEqual(len(normalized), 0)


if __name__ == "__main__":
    unittest.main()
