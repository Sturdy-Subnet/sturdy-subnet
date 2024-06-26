import unittest
import torch

from web3 import Web3

from sturdy.validator.reward import (
    format_allocations,
    get_similarity_matrix,
    reward_miner_apy,
    calculate_penalties,
    calculate_rewards_with_adjusted_penalties,
    adjust_rewards_for_plagiarism,
)

import numpy as np


class TestRewardFunctions(unittest.TestCase):
    def test_format_allocations(self):
        allocations = {"1": 5e18, "2": 3e18}
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

    def test_format_allocations_no_pools(self):
        allocations = {"1": 5e18, "2": 3e18}
        assets_and_pools = {"pools": {}}

        expected_output = {"1": 5e18, "2": 3e18}
        result = format_allocations(allocations, assets_and_pools)

        self.assertEqual(result, expected_output)

    def test_format_allocations_empty(self):
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

    def test_reward_miner_apy_normal(self):
        result = reward_miner_apy(query=1, max_apy=int(0.05e18), miner_apy=int(0.03e18))
        expected = Web3.to_wei((3e16) / (5e16), "ether")
        self.assertEqual(result, expected)

    def test_reward_miner_apy_zero_division(self):
        result = reward_miner_apy(query=1, max_apy=0, miner_apy=3e16)
        self.assertEqual(result, 0)


def test_get_similarity_matrix_normalized_euclidean(self):
    apys_and_allocations = {
        "miner_1": {"apy": int(0.05e18), "allocations": {"pool_1": 30, "pool_2": 20}},
        "miner_2": {"apy": int(0.04e18), "allocations": {"pool_1": 40, "pool_2": 10}},
        "miner_3": {"apy": int(0.06e18), "allocations": {"pool_1": 30, "pool_2": 20}},
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
            "miner_2": np.linalg.norm(np.array([30, 20]) - np.array([40, 10]))
            / normalization_factor,
            "miner_3": np.linalg.norm(np.array([30, 20]) - np.array([30, 20]))
            / normalization_factor,
        },
        "miner_2": {
            "miner_1": np.linalg.norm(np.array([40, 10]) - np.array([30, 20]))
            / normalization_factor,
            "miner_3": np.linalg.norm(np.array([40, 10]) - np.array([30, 20]))
            / normalization_factor,
        },
        "miner_3": {
            "miner_1": np.linalg.norm(np.array([30, 20]) - np.array([30, 20]))
            / normalization_factor,
            "miner_2": np.linalg.norm(np.array([30, 20]) - np.array([40, 10]))
            / normalization_factor,
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


def test_calculate_penalties(self):
    similarity_matrix = {
        "1": {"2": 0.05, "3": 0.2},
        "2": {"1": 0.05, "3": 0.1},
        "3": {"1": 0.2, "2": 0.1},
    }
    axon_times = {"1": 1, "2": 2, "3": 3}
    similarity_threshold = 0.1

    expected_penalties = {"1": 0, "2": 1, "3": 1}
    result = calculate_penalties(similarity_matrix, axon_times, similarity_threshold)

    self.assertEqual(result, expected_penalties)


def test_calculate_penalties_no_similarities(self):
    similarity_matrix = {
        "1": {"2": 0.5, "3": 0.6},
        "2": {"1": 0.5, "3": 0.7},
        "3": {"1": 0.6, "2": 0.7},
    }
    axon_times = {"1": 1, "2": 2, "3": 3}
    similarity_threshold = 0.1

    expected_penalties = {"1": 0, "2": 0, "3": 0}
    result = calculate_penalties(similarity_matrix, axon_times, similarity_threshold)

    self.assertEqual(result, expected_penalties)


def test_calculate_penalties_equal_times(self):
    similarity_matrix = {
        "1": {"2": 0.05, "3": 0.05},
        "2": {"1": 0.05, "3": 0.05},
        "3": {"1": 0.05, "2": 0.05},
    }
    axon_times = {"1": 1, "2": 1, "3": 1}
    similarity_threshold = 0.1

    expected_penalties = {"1": 2, "2": 2, "3": 2}
    result = calculate_penalties(similarity_matrix, axon_times, similarity_threshold)

    self.assertEqual(result, expected_penalties)


def test_calculate_rewards_with_adjusted_penalties(self):
    miners = ["1", "2", "3"]
    rewards_apy = torch.FloatTensor([0.05, 0.04, 0.03])
    penalties = {"1": 0, "2": 1, "3": 2}

    expected_rewards = torch.FloatTensor([0.05, 0.02666667, 0.01])
    result = calculate_rewards_with_adjusted_penalties(miners, rewards_apy, penalties)

    torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)


def test_calculate_rewards_with_no_penalties(self):
    miners = ["1", "2", "3"]
    rewards_apy = torch.FloatTensor([0.05, 0.04, 0.03])
    penalties = {"1": 0, "2": 0, "3": 0}

    expected_rewards = torch.FloatTensor([0.05, 0.04, 0.03])
    result = calculate_rewards_with_adjusted_penalties(miners, rewards_apy, penalties)

    torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)


def test_calculate_rewards_with_equal_penalties(self):
    miners = ["1", "2", "3"]
    rewards_apy = torch.FloatTensor([0.05, 0.04, 0.03])
    penalties = {"1": 1, "2": 1, "3": 1}

    expected_rewards = torch.FloatTensor([0.0250, 0.0200, 0.0150])
    result = calculate_rewards_with_adjusted_penalties(miners, rewards_apy, penalties)

    torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)


def test_adjust_rewards_for_plagiarism(self):
    rewards_apy = torch.FloatTensor([0.05, 0.04, 0.03])
    apys_and_allocations = {
        "0": {"apy": 0.05, "allocations": {"asset_1": 0.2, "asset_2": 0.3}},
        "1": {"apy": 0.04, "allocations": {"asset_1": 0.25, "asset_2": 0.25}},
        "2": {"apy": 0.03, "allocations": {"asset_1": 0.2, "asset_2": 0.4}},
    }
    assets_and_pools = {
        "total_assets": 1,
        "pools": {"asset_1": 1000, "asset_2": 1000},
    }
    uids = ["0", "1", "2"]
    axon_times = {"0": 1, "1": 2, "2": 3}

    expected_rewards = torch.FloatTensor([0.0500, 0.0200, 0.0300])
    result = adjust_rewards_for_plagiarism(
        rewards_apy, apys_and_allocations, assets_and_pools, uids, axon_times
    )

    torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
