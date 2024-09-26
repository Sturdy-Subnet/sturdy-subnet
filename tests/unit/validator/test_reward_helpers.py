import copy
import unittest

import numpy as np
import torch
from web3 import Web3
from web3.constants import ADDRESS_ZERO

from sturdy.pools import *
from sturdy.validator.reward import (
    adjust_rewards_for_plagiarism,
    calculate_penalties,
    calculate_rewards_with_adjusted_penalties,
    format_allocations,
    get_similarity_matrix,
    dynamic_normalize_zscore,
)

BEEF = "0xDeaDbeefdEAdbeefdEadbEEFdeadbeEFdEaDbeeF"


class TestRewardFunctions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # runs tests on local mainnet fork at block: 20233401
        cls.w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        assert cls.w3.is_connected()

    def test_check_allocations_valid(self) -> None:
        allocations = {ADDRESS_ZERO: int(5e18), BEEF: int(3e18)}
        assets_and_pools = {
            "total_assets": int(10e18),
            "pools": {
                ADDRESS_ZERO: BasePool(
                    contract_address=ADDRESS_ZERO,
                    base_rate=0,
                    base_slope=0,
                    kink_slope=0,
                    optimal_util_rate=0,
                    borrow_amount=int(2e18),
                    reserve_size=0,
                ),
                BEEF: BasePool(
                    contract_address=BEEF,
                    base_rate=0,
                    base_slope=0,
                    kink_slope=0,
                    optimal_util_rate=0,
                    borrow_amount=int(1e18),
                    reserve_size=0,
                ),
            },
        }

        result = check_allocations(assets_and_pools, allocations)
        self.assertTrue(result)

    def test_check_allocations_overallocate(self) -> None:
        allocations = {ADDRESS_ZERO: int(10e18), BEEF: int(3e18)}
        assets_and_pools = {
            "total_assets": int(10e18),
            "pools": {
                ADDRESS_ZERO: BasePool(
                    contract_address=ADDRESS_ZERO,
                    base_rate=0,
                    base_slope=0,
                    kink_slope=0,
                    optimal_util_rate=0,
                    borrow_amount=int(2e18),
                    reserve_size=0,
                ),
                BEEF: BasePool(
                    contract_address=BEEF,
                    base_rate=0,
                    base_slope=0,
                    kink_slope=0,
                    optimal_util_rate=0,
                    borrow_amount=int(1e18),
                    reserve_size=0,
                ),
            },
        }

        result = check_allocations(assets_and_pools, allocations)
        self.assertFalse(result)

    def test_check_allocations_below_borrow(self) -> None:
        allocations = {ADDRESS_ZERO: int(10e18), BEEF: int(3e18)}
        assets_and_pools = {
            "total_assets": int(10e18),
            "pools": {
                ADDRESS_ZERO: BasePool(
                    contract_address=ADDRESS_ZERO,
                    base_rate=0,
                    base_slope=0,
                    kink_slope=0,
                    optimal_util_rate=0,
                    borrow_amount=int(2e18),
                    reserve_size=0,
                ),
                BEEF: BasePool(
                    contract_address=BEEF,
                    base_rate=0,
                    base_slope=0,
                    kink_slope=0,
                    optimal_util_rate=0,
                    borrow_amount=int(1e18),
                    reserve_size=0,
                ),
            },
        }

        result = check_allocations(assets_and_pools, allocations)
        self.assertFalse(result)

    def test_check_allocations_valid_sturdy(self) -> None:
        A = "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227"
        B = "0x200723063111f9f8f1d44c0F30afAdf0C0b1a04b"
        VAULT = "0x73E4C11B670Ef9C025A030A20b72CB9150E54523"
        # assuming block # is: 20233401
        allocations = {A: int(6e23), B: int(6e22)}
        assets_and_pools = {
            "total_assets": int(7e23),
            "pools": {
                A: VariableInterestSturdySiloStrategy(
                    user_address=VAULT,
                    contract_address=A,
                ),
                B: VariableInterestSturdySiloStrategy(
                    user_address=VAULT,
                    contract_address=B,
                ),
            },
        }

        pool_a: VariableInterestSturdySiloStrategy = assets_and_pools["pools"][A]
        pool_b: VariableInterestSturdySiloStrategy = assets_and_pools["pools"][B]
        pool_a.sync(VAULT, web3_provider=self.w3)
        pool_b.sync(VAULT, web3_provider=self.w3)

        result = check_allocations(assets_and_pools, allocations)
        self.assertTrue(result)

    def test_check_allocations_invalid_sturdy(self) -> None:
        A = "0x6311fF24fb15310eD3d2180D3d0507A21a8e5227"
        B = "0x200723063111f9f8f1d44c0F30afAdf0C0b1a04b"
        VAULT = "0x73E4C11B670Ef9C025A030A20b72CB9150E54523"
        # assuming block # is: 20233401
        allocations = {A: int(5e23), B: int(6e22)}
        assets_and_pools = {
            "total_assets": int(7e23),
            "pools": {
                A: VariableInterestSturdySiloStrategy(
                    user_address=VAULT,
                    contract_address=A,
                ),
                B: VariableInterestSturdySiloStrategy(
                    user_address=VAULT,
                    contract_address=B,
                ),
            },
        }

        pool_a: VariableInterestSturdySiloStrategy = assets_and_pools["pools"][A]
        pool_b: VariableInterestSturdySiloStrategy = assets_and_pools["pools"][B]
        pool_a.sync(VAULT, web3_provider=self.w3)
        pool_b.sync(VAULT, web3_provider=self.w3)

        result = check_allocations(assets_and_pools, allocations)
        self.assertFalse(result)

    def test_check_allocations_valid_aave(self) -> None:
        A = "0x018008bfb33d285247A21d44E50697654f754e63"
        # assuming block # is: 20233401
        allocations = {A: int(1.5e26)}
        assets_and_pools = {
            "total_assets": int(2e26),
            "pools": {
                A: AaveV3DefaultInterestRatePool(
                    user_address=ADDRESS_ZERO,
                    contract_address=A,
                ),
            },
        }

        pool_a: AaveV3DefaultInterestRatePool = assets_and_pools["pools"][A]
        pool_a.sync(self.w3)

        result = check_allocations(assets_and_pools, allocations)
        self.assertTrue(result)

    def test_check_allocations_invalid_aave(self) -> None:
        A = "0x018008bfb33d285247A21d44E50697654f754e63"
        # assuming block # is: 20233401
        allocations = {A: int(1e26)}
        assets_and_pools = {
            "total_assets": int(2e26),
            "pools": {
                A: AaveV3DefaultInterestRatePool(
                    user_address=ADDRESS_ZERO,
                    contract_address=A,
                ),
            },
        }

        pool_a: AaveV3DefaultInterestRatePool = assets_and_pools["pools"][A]
        pool_a.sync(self.w3)

        result = check_allocations(assets_and_pools, allocations)
        self.assertFalse(result)

    def test_check_allocations_valid_compound(self) -> None:
        A = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        # assuming block # is: 20233401
        allocations = {A: int(5e14)}
        assets_and_pools = {
            "total_assets": int(6e14),
            "pools": {
                A: CompoundV3Pool(
                    user_address=ADDRESS_ZERO,
                    contract_address=A,
                ),
            },
        }

        pool_a: CompoundV3Pool = assets_and_pools["pools"][A]
        pool_a.sync(self.w3)

        result = check_allocations(assets_and_pools, allocations)
        self.assertTrue(result)

    def test_check_allocations_invalid_compound(self) -> None:
        A = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
        # assuming block # is: 20233401
        allocations = {A: int(4e14)}
        assets_and_pools = {
            "total_assets": int(6e14),
            "pools": {
                A: CompoundV3Pool(
                    user_address=ADDRESS_ZERO,
                    contract_address=A,
                ),
            },
        }

        pool_a: CompoundV3Pool = assets_and_pools["pools"][A]
        pool_a.sync(self.w3)

        result = check_allocations(assets_and_pools, allocations)
        self.assertFalse(result)

    def test_format_allocations(self) -> None:
        allocations = {"1": int(5e18), "2": int(3e18)}
        assets_and_pools = {
            "pools": {
                "1": {"reserve_size": 1000},
                "2": {"reserve_size": 1000},
                "3": {"reserve_size": 1000},
            }
        }

        expected_output = {"1": 5e18, "2": 3e18, "3": 0}
        result = format_allocations(allocations, assets_and_pools)

        self.assertEqual(result, expected_output)

    def test_format_allocations_no_pools(self) -> None:
        allocations = {"1": int(5e18), "2": int(3e18)}
        assets_and_pools = {"pools": {}}

        expected_output = {"1": 5e18, "2": 3e18}
        result = format_allocations(allocations, assets_and_pools)

        self.assertEqual(result, expected_output)

    def test_format_allocations_empty(self) -> None:
        allocations = {}
        assets_and_pools = {
            "pools": {
                "1": {"reserve_size": 1000},
                "2": {"reserve_size": 1000},
            }
        }

        expected_output = {"1": 0, "2": 0}
        result = format_allocations(allocations, assets_and_pools)

        self.assertEqual(result, expected_output)

    def test_basic_normalization(self) -> None:
        # Test a simple tensor with a standard range of values
        rewards = torch.tensor([10.0, 20.0, 30.0, 40.0, 50.0])
        normalized = dynamic_normalize_zscore(rewards)

        # Check if output is normalized between 0 and 1
        self.assertAlmostEqual(normalized.min().item(), 0.0, places=5)
        self.assertAlmostEqual(normalized.max().item(), 1.0, places=5)

    def test_with_low_outliers(self) -> None:
        # Test with low outliers
        rewards = torch.tensor([1.0, 1.0, 1.0, 50.0, 100.0, 200.0])
        normalized = dynamic_normalize_zscore(rewards)

        # Check that outliers don't affect the overall normalization
        self.assertAlmostEqual(normalized.min().item(), 0.0, places=5)
        self.assertAlmostEqual(normalized.max().item(), 1.0, places=5)

    def test_with_high_outliers(self) -> None:
        # Test with high outliers
        rewards = torch.tensor([50.0, 60.0, 70.0, 1000.0, 2000.0])
        normalized = dynamic_normalize_zscore(rewards)

        # Check that the function correctly handles high outliers
        self.assertAlmostEqual(normalized.min().item(), 0.0, places=5)
        self.assertAlmostEqual(normalized.max().item(), 1.0, places=5)

    def test_uniform_values(self) -> None:
        # Test where all values are the same
        rewards = torch.tensor([10.0, 10.0, 10.0, 10.0])
        normalized = dynamic_normalize_zscore(rewards)
        print(normalized)

        # If all values are the same, the output should also be uniform (or handle gracefully)
        self.assertTrue(torch.allclose(normalized, torch.zeros_like(rewards), atol = 1e-8))

    def test_low_variance(self) -> None:
        # Test with low variance data (values are close to each other)
        rewards = torch.tensor([100.0, 101.0, 102.0, 103.0, 104.0])
        normalized = dynamic_normalize_zscore(rewards)

        # Check if normalization happens correctly
        self.assertAlmostEqual(normalized.min().item(), 0.0, places=5)
        self.assertAlmostEqual(normalized.max().item(), 1.0, places=5)

    def test_high_variance(self) -> None:
        # Test with high variance data
        rewards = torch.tensor([1.0, 100.0, 500.0, 1000.0])
        normalized = dynamic_normalize_zscore(rewards)

        # Ensure that the normalization works even with high variance
        self.assertAlmostEqual(normalized.min().item(), 0.0, places=5)
        self.assertAlmostEqual(normalized.max().item(), 1.0, places=5)

    def test_quantile_logic(self) -> None:
        # Test a case where the lower quartile range affects the lower bound decision
        rewards = torch.tensor([1.0, 2.0, 3.0, 4.0, 100.0, 200.0, 300.0, 400.0])
        normalized = dynamic_normalize_zscore(rewards)

        # Ensure that quantile-based clipping works as expected
        self.assertAlmostEqual(normalized.min().item(), 0.0, places=5)
        self.assertAlmostEqual(normalized.max().item(), 1.0, places=5)

    def test_get_similarity_matrix(self) -> None:
        apys_and_allocations = {
            "miner_1": {
                "apy": int(0.05e18),
                "allocations": {"pool_1": 30, "pool_2": 20},
            },
            "miner_2": {
                "apy": int(0.04e18),
                "allocations": {"pool_1": 40, "pool_2": 10},
            },
            "miner_3": {
                "apy": int(0.06e18),
                "allocations": {"pool_1": 30, "pool_2": 20},
            },
        }
        assets_and_pools = {
            "pools": {
                "pool_1": {"reserve_size": 100},
                "pool_2": {"reserve_size": 100},
            },
            "total_assets": 100,
        }

        total_assets = assets_and_pools["total_assets"]
        normalization_factor = np.sqrt(float(2 * total_assets**2))  # √(2 * total_assets^2)

        expected_similarity_matrix = {
            "miner_1": {
                "miner_2": np.linalg.norm(np.array([30, 20]) - np.array([40, 10])) / normalization_factor,
                "miner_3": np.linalg.norm(np.array([30, 20]) - np.array([30, 20])) / normalization_factor,
            },
            "miner_2": {
                "miner_1": np.linalg.norm(np.array([40, 10]) - np.array([30, 20])) / normalization_factor,
                "miner_3": np.linalg.norm(np.array([40, 10]) - np.array([30, 20])) / normalization_factor,
            },
            "miner_3": {
                "miner_1": np.linalg.norm(np.array([30, 20]) - np.array([30, 20])) / normalization_factor,
                "miner_2": np.linalg.norm(np.array([30, 20]) - np.array([40, 10])) / normalization_factor,
            },
        }

        result = get_similarity_matrix(apys_and_allocations, assets_and_pools)

        for miner_a in expected_similarity_matrix:
            for miner_b in expected_similarity_matrix[miner_a]:
                self.assertAlmostEqual(
                    result[miner_a][miner_b],
                    expected_similarity_matrix[miner_a][miner_b],
                    places=5,
                )

    def test_get_similarity_matrix_empty(self) -> None:
        apys_and_allocations = {
            "miner_1": {
                "apy": int(0.05e18),
                "allocations": {"pool_1": 30, "pool_2": 20},
            },
            "miner_2": {
                "apy": int(0.04e18),
                "allocations": {"pool_1": 40, "pool_2": 10},
            },
            "miner_3": {"apy": 0, "allocations": None},
        }
        assets_and_pools = {
            "pools": {
                "pool_1": {"reserve_size": 100},
                "pool_2": {"reserve_size": 100},
            },
            "total_assets": 100,
        }

        total_assets = assets_and_pools["total_assets"]
        normalization_factor = np.sqrt(float(2 * total_assets**2))  # √(2 * total_assets^2)

        expected_similarity_matrix = {
            "miner_1": {
                "miner_2": np.linalg.norm(np.array([30, 20]) - np.array([40, 10])) / normalization_factor,
                "miner_3": float("inf"),
            },
            "miner_2": {
                "miner_1": np.linalg.norm(np.array([40, 10]) - np.array([30, 20])) / normalization_factor,
                "miner_3": float("inf"),
            },
            "miner_3": {"miner_1": float("inf"), "miner_2": float("inf")},
        }

        result = get_similarity_matrix(apys_and_allocations, assets_and_pools)

        for miner_a in expected_similarity_matrix:
            for miner_b in expected_similarity_matrix[miner_a]:
                self.assertAlmostEqual(
                    result[miner_a][miner_b],
                    expected_similarity_matrix[miner_a][miner_b],
                    places=5,
                )

    def test_calculate_penalties(self) -> None:
        similarity_matrix = {
            "1": {"2": 0.05, "3": 0.2},
            "2": {"1": 0.05, "3": 0.1},
            "3": {"1": 0.2, "2": 0.1},
        }
        axon_times = {"1": 1.0, "2": 2.0, "3": 3.0}
        similarity_threshold = 0.1

        expected_penalties = {"1": 0, "2": 1, "3": 1}
        result = calculate_penalties(similarity_matrix, axon_times, similarity_threshold)

        self.assertEqual(result, expected_penalties)

    def test_calculate_penalties_no_similarities(self) -> None:
        similarity_matrix = {
            "1": {"2": 0.5, "3": 0.6},
            "2": {"1": 0.5, "3": 0.7},
            "3": {"1": 0.6, "2": 0.7},
        }
        axon_times = {"1": 1.0, "2": 2.0, "3": 3.0}
        similarity_threshold = 0.1

        expected_penalties = {"1": 0, "2": 0, "3": 0}
        result = calculate_penalties(similarity_matrix, axon_times, similarity_threshold)

        self.assertEqual(result, expected_penalties)

    def test_calculate_penalties_equal_times(self) -> None:
        similarity_matrix = {
            "1": {"2": 0.05, "3": 0.05},
            "2": {"1": 0.05, "3": 0.05},
            "3": {"1": 0.05, "2": 0.05},
        }
        axon_times = {"1": 1.0, "2": 1.0, "3": 1.0}
        similarity_threshold = 0.1

        expected_penalties = {"1": 2, "2": 2, "3": 2}
        result = calculate_penalties(similarity_matrix, axon_times, similarity_threshold)

        self.assertEqual(result, expected_penalties)

    def test_calculate_rewards_with_adjusted_penalties(self) -> None:
        miners = ["1", "2", "3"]
        rewards_apy = torch.Tensor([1.0, 1.0, 1.0])
        penalties = {"1": 0, "2": 1, "3": 2}

        expected_rewards = torch.Tensor([1.0, 0.5, 0.0])
        result = calculate_rewards_with_adjusted_penalties(miners, rewards_apy, penalties)

        torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)

    def test_calculate_rewards_with_no_penalties(self) -> None:
        miners = ["1", "2", "3"]
        rewards_apy = torch.Tensor([0.05, 0.04, 0.03])
        penalties = {"1": 0, "2": 0, "3": 0}

        expected_rewards = torch.Tensor([0.05, 0.04, 0.03])
        result = calculate_rewards_with_adjusted_penalties(miners, rewards_apy, penalties)

        torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)

    def test_adjust_rewards_for_plagiarism(self) -> None:
        rewards_apy = torch.Tensor([0.05 / 0.05, 0.04 / 0.05, 0.03 / 0.05])
        apys_and_allocations = {
            "0": {"apy": 0.05, "allocations": {"asset_1": 200, "asset_2": 300}},
            "1": {"apy": 0.04, "allocations": {"asset_1": 210, "asset_2": 310}},
            "2": {"apy": 0.03, "allocations": {"asset_1": 200, "asset_2": 400}},
        }
        assets_and_pools = {
            "total_assets": 500,
            "pools": {"asset_1": 1000, "asset_2": 1000},
        }
        uids = ["0", "1", "2"]
        axon_times = {"0": 1.0, "1": 2.0, "2": 3.0}

        expected_rewards = torch.Tensor([1.0, 0.0, 0.03 / 0.05])
        result = adjust_rewards_for_plagiarism(rewards_apy, apys_and_allocations, assets_and_pools, uids, axon_times)

        torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)

    def test_adjust_rewards_for_one_plagiarism(self) -> None:
        rewards_apy = torch.Tensor([1.0, 1.0])
        apys_and_allocations = {
            "0": {"apy": 0.05, "allocations": {"asset_1": 200, "asset_2": 300}},
            "1": {"apy": 0.05, "allocations": {"asset_1": 200, "asset_2": 300}},
        }
        assets_and_pools = {
            "total_assets": 500,
            "pools": {"asset_1": 1000, "asset_2": 1000},
        }
        uids = ["0", "1"]
        axon_times = {"0": 1.0, "1": 2.0}

        expected_rewards = torch.Tensor([1.0, 0.0])
        result = adjust_rewards_for_plagiarism(rewards_apy, apys_and_allocations, assets_and_pools, uids, axon_times)

        torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
