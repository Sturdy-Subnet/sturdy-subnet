import unittest
from unittest import IsolatedAsyncioTestCase

from neurons.validator import Validator


class TestValidator(IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # dont log this in wandb
        config = {"mock": True, "wandb": {"off": True}, "mock_n": 16, "neuron": {"dont_save_events": True}, "netuid": 69}
        cls.validator = Validator(config=config)

    async def test_forward(self):
        await self.validator.forward()


if __name__ == "__main__":
    unittest.main()
