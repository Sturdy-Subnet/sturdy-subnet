import unittest

import numpy as np
import torch

from sturdy.validator.reward import (
    adjust_rewards_for_plagiarism,
    calculate_penalties,
    calculate_rewards_with_adjusted_penalties,
    format_allocations,
    get_similarity_matrix,
    pctl_normalize_rewards,
)


class TestRewardFunctions(unittest.TestCase):
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

    def test_all_positive_values(self) -> None:
        rewards = torch.tensor([10.0, 20.0, 30.0, 40.0, 50.0])
        normalized_rewards = pctl_normalize_rewards(rewards)
        self.assertTrue(torch.all(normalized_rewards >= 0))
        self.assertTrue(torch.all(normalized_rewards <= 1))

    def test_some_negative_values(self) -> None:
        rewards = torch.tensor([-10.0, 0.0, 10.0, 20.0, 30.0])
        normalized_rewards = pctl_normalize_rewards(rewards)
        self.assertTrue(torch.all(normalized_rewards >= 0))
        self.assertTrue(torch.all(normalized_rewards <= 1))

    def test_all_zero_values(self) -> None:
        rewards = torch.tensor([0.0, 0.0, 0.0, 0.0, 0.0])
        normalized_rewards = pctl_normalize_rewards(rewards)
        expected_result = torch.tensor([0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertTrue(torch.equal(normalized_rewards, expected_result))

    def test_single_value(self) -> None:
        rewards = torch.tensor([100.0])
        normalized_rewards = pctl_normalize_rewards(rewards)
        expected_result = torch.tensor([0.0])  # With a single value, normalization should return 0
        self.assertTrue(torch.equal(normalized_rewards, expected_result))

    def test_with_outliers(self) -> None:
        rewards = torch.tensor([1.0, 1.5, 2.0, 100.0, 1000.0])
        normalized_rewards = pctl_normalize_rewards(rewards)
        self.assertTrue(torch.all(normalized_rewards >= 0))
        self.assertTrue(torch.all(normalized_rewards <= 1))
        # The outliers should be normalized to near 1 after clipping
        self.assertAlmostEqual(float(torch.max(normalized_rewards)), 1.0, places=5)

    def test_identical_values(self) -> None:
        rewards = torch.tensor([50.0, 50.0, 50.0, 50.0])
        normalized_rewards = pctl_normalize_rewards(rewards)
        expected_result = torch.tensor([0.0, 0.0, 0.0, 0.0])  # Identical values should all be normalized to 0
        self.assertTrue(torch.equal(normalized_rewards, expected_result))

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
