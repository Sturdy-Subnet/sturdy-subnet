import random
import unittest
from unittest import TestCase

from sturdy.protocol import AllocateAssets
from sturdy.pools import generate_assets_and_pools
from sturdy.utils.misc import greedy_allocation_algorithm
from sturdy.validator.reward import sigmoid_scale, get_response_times
from parameterized import parameterized


class TestLatencyScaling(TestCase):
    @parameterized.expand(
        [
            [0.01, 0.99871, 4, 10, 1.0, 1.5, 10],
            [0.05, 0.99866, 4, 10, 1.0, 1.5, 10],
            [1.00, 0.99655, 4, 10, 1.0, 1.5, 10],
            [5.00, 0.84113, 4, 10, 1.0, 1.5, 10],
            [7.00, 0.41742, 4, 10, 1.0, 1.5, 10],
            [10.00, 0, 4, 10, 1.0, 1.5, 10],
            [11.00, 0, 4, 10, 1.0, 1.5, 10],
        ]
    )
    def test_latency_scaling(
        self,
        process_time: float,
        expected: float,
        places: int,
        num_pools: int,
        steepness: float,
        div_factor: float,
        timeout: float,
    ):
        output = sigmoid_scale(
            process_time,
            num_pools=num_pools,
            steepness=steepness,
            div_factor=div_factor,
            timeout=timeout,
        )
        self.assertAlmostEqual(output, expected, places=places)


if __name__ == "__main__":
    unittest.main()
