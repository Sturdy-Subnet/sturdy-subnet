import unittest
import torch
import sys

from sturdy.validator.reward import (
    format_allocations,
    reward_miner_apy,
    calculate_penalties,
    calculate_rewards_with_adjusted_penalties,
    adjust_rewards_for_plagiarism,
)


class TestRewardFunctions(unittest.TestCase):
    def test_format_allocations(self):
        allocations = {"1": 0.5, "2": 0.3}
        assets_and_pools = {
            "pools": {
                "1": {"reserve_size": 1000},
                "2": {"reserve_size": 1000},
                "3": {"reserve_size": 1000},
            }
        }

        expected_output = {"1": 0.5, "2": 0.3, "3": 0.0}
        result = format_allocations(allocations, assets_and_pools)

        self.assertEqual(result, expected_output)

    def test_format_allocations_no_pools(self):
        allocations = {"1": 0.5, "2": 0.3}
        assets_and_pools = {"pools": {}}

        expected_output = {"1": 0.5, "2": 0.3}
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

        expected_output = {"1": 0.0, "2": 0.0}
        result = format_allocations(allocations, assets_and_pools)

        self.assertEqual(result, expected_output)

    def test_reward_miner_apy_normal(self):
        result = reward_miner_apy(query=1, max_apy=0.05, miner_apy=0.03)
        expected = (0.03 - sys.float_info.min) / (0.05 - sys.float_info.min + 1e-10)
        self.assertAlmostEqual(result, expected, places=6)

    def test_reward_miner_apy_zero_division(self):
        result = reward_miner_apy(query=1, max_apy=sys.float_info.min, miner_apy=0.03)
        self.assertEqual(result, 0.0)

    def test_reward_miner_apy_large_max_apy(self):
        result = reward_miner_apy(query=1, max_apy=1e10, miner_apy=1e9)
        expected = (1e9 - sys.float_info.min) / (1e10 - sys.float_info.min + 1e-10)
        self.assertAlmostEqual(result, expected, places=6)

    def test_calculate_penalties(self):
        similarity_matrix = {
            "1": {"2": 0.05, "3": 0.2},
            "2": {"1": 0.05, "3": 0.1},
            "3": {"1": 0.2, "2": 0.1},
        }
        axon_times = {"1": 1, "2": 2, "3": 3}
        similarity_threshold = 0.1

        expected_penalties = {"1": 0, "2": 1, "3": 1}
        result = calculate_penalties(
            similarity_matrix, axon_times, similarity_threshold
        )

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
        result = calculate_penalties(
            similarity_matrix, axon_times, similarity_threshold
        )

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
        result = calculate_penalties(
            similarity_matrix, axon_times, similarity_threshold
        )

        self.assertEqual(result, expected_penalties)

    def test_calculate_rewards_with_adjusted_penalties(self):
        miners = ["1", "2", "3"]
        rewards_apy = torch.FloatTensor([0.05, 0.04, 0.03])
        penalties = {"1": 0, "2": 1, "3": 2}

        expected_rewards = torch.FloatTensor([0.05, 0.02666667, 0.01])
        result = calculate_rewards_with_adjusted_penalties(
            miners, rewards_apy, penalties
        )

        torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)

    def test_calculate_rewards_with_no_penalties(self):
        miners = ["1", "2", "3"]
        rewards_apy = torch.FloatTensor([0.05, 0.04, 0.03])
        penalties = {"1": 0, "2": 0, "3": 0}

        expected_rewards = torch.FloatTensor([0.05, 0.04, 0.03])
        result = calculate_rewards_with_adjusted_penalties(
            miners, rewards_apy, penalties
        )

        torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)

    def test_calculate_rewards_with_equal_penalties(self):
        miners = ["1", "2", "3"]
        rewards_apy = torch.FloatTensor([0.05, 0.04, 0.03])
        penalties = {"1": 1, "2": 1, "3": 1}

        expected_rewards = torch.FloatTensor([0.0250, 0.0200, 0.0150])
        result = calculate_rewards_with_adjusted_penalties(
            miners, rewards_apy, penalties
        )

        torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e-5)

    def test_adjust_rewards_for_plagiarism(self):
        rewards_apy = torch.FloatTensor([0.05, 0.04, 0.03])
        apys_and_allocations = {
            "0": {"apy": 0.05, "allocations": {"asset_1": 0.2, "asset_2": 0.3}},
            "1": {"apy": 0.04, "allocations": {"asset_1": 0.25, "asset_2": 0.25}},
            "2": {"apy": 0.03, "allocations": {"asset_1": 0.2, "asset_2": 0.4}},
        }
        assets_and_pools = {"pools": {"asset_1": 1000, "asset_2": 1000}}
        uids = ["0", "1", "2"]
        axon_times = {"0": 1, "1": 2, "2": 3}

        expected_rewards = torch.FloatTensor([0.0500, 0.0267, 0.0100])
        result = adjust_rewards_for_plagiarism(
            rewards_apy, apys_and_allocations, assets_and_pools, uids, axon_times
        )

        torch.testing.assert_close(result, expected_rewards, rtol=0, atol=1e05)


if __name__ == "__main__":
    unittest.main()
