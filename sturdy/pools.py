# The MIT License (MIT)
# Copyright © 2023 Syeam Bin Abdullah

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from typing import Dict

import json
from pydantic import BaseModel, Field, PrivateAttr, validator, root_validator
from web3 import Web3
from web3.contract import Contract
import numpy as np
import bittensor as bt
from pathlib import Path

from sturdy.utils.misc import (
    randrange_float,
    format_num_prec,
    retry_with_backoff,
    rayMul,
    getReserveFactor,
)
from sturdy.constants import *


class BasePoolModel(BaseModel):
    """This model will primarily be used for synthetic requests"""

    pool_id: str = Field(..., required=True, description="uid of pool")
    base_rate: float = Field(..., required=True, description="base interest rate")
    base_slope: float = Field(
        ..., required=True, description="base interest rate slope"
    )
    kink_slope: float = Field(..., required=True, description="kink slope")
    optimal_util_rate: float = Field(
        ..., required=True, description="optimal utilisation rate"
    )
    borrow_amount: float = Field(..., required=True, description="borrow amount")
    reserve_size: float = Field(..., required=True, description="pool reserve size")

    @root_validator
    def check_params(cls, values):
        if len(values.get("pool_id")) <= 0:
            raise ValueError("pool id is empty")
        if values.get("base_rate") < 0:
            raise ValueError("base rate is negative")
        if values.get("base_slope") < 0:
            raise ValueError("base slope is negative")
        if values.get("kink_slope") < 0:
            raise ValueError("kink slope is negative")
        if values.get("optimal_util_rate") < 0:
            raise ValueError("optimal utilization rate is negative")
        if values.get("borrow_amount") < 0:
            raise ValueError("borrow amount is negative")
        if values.get("reserve_size") < 0:
            raise ValueError("reserve size is negative")
        return values


class BasePool(BasePoolModel):
    """This class defines the base pool type

    Args:
        pool_id: (str),
        base_rate: (float),
        base_slope: (float),
        kink_slope: (float),
        optimal_util_rate: (float),
        borrow_amount: (float),
        reserve_size: (float),
    """

    @property
    def util_rate(self) -> float:
        return self.borrow_amount / self.reserve_size

    @property
    def borrow_rate(self) -> float:
        util_rate = self.util_rate
        interest_rate = (
            self.base_rate + (util_rate / self.optimal_util_rate) * self.base_slope
            if util_rate < self.optimal_util_rate
            else self.base_rate
            + self.base_slope
            + ((util_rate - self.optimal_util_rate) / (1 - self.optimal_util_rate))
            * self.kink_slope
        )

        return interest_rate

    @property
    def supply_rate(self):
        return self.util_rate * self.borrow_rate


class ChainBasedPoolModel(BaseModel):
    """This serves as the base model of pools which need to pull data from on-chain

    Args:
        pool_id: (str),
        contract_address: (str),
    """

    pool_id: str = Field(..., required=True, description="uid of pool")
    contract_address: str = Field(
        ..., required=True, description="address of contract to call"
    )

    @root_validator
    def check_params(cls, values):
        if len(values.get("pool_id")) <= 0:
            raise ValueError("pool id is empty")
        if not Web3.is_address(values.get("contract_address")):
            raise ValueError("pool address is invalid!")

        return values


class ChainBasedPoolFactory:
    @staticmethod
    def create_product(product_type: str, **kwargs) -> ChainBasedPoolModel:
        if product_type == "default":
            return ChainBasedPoolModel(**kwargs)
        if product_type == "aave_v3":
            return AaveV3DefaultInterestRatePool(**kwargs)
        else:
            raise ValueError(f"Unknown product type: {product_type}")


class AaveV3DefaultInterestRatePool(ChainBasedPoolModel):
    """This class defines the default pool type for Aave"""

    web3_provider: Web3 = Field(
        ..., required=True, description="web3 provider used to query data"
    )

    _atoken_contract: Contract = PrivateAttr()
    _pool_contract: Contract = PrivateAttr()
    _underlying_asset_address: str = PrivateAttr()
    _reserve_data = PrivateAttr()
    _strategy_contract = PrivateAttr()
    _nextTotalStableDebt = PrivateAttr()
    _nextAvgStableBorrowRate = PrivateAttr()
    _variable_debt_token_contract = PrivateAttr()
    _totalVariableDebt = PrivateAttr()

    class Config:
        arbitrary_types_allowed = True

    @validator("web3_provider", pre=False)
    def check_w3_provider(cls, value: Web3, values) -> Web3:
        try:
            assert value.is_connected()
        except Exception as err:
            bt.logging.error("Failed to connect to Web3 instance!")
            bt.logging.error(err)

        try:
            atoken_abi_file_path = Path(__file__).parent / "../abi/AToken.json"
            atoken_abi_file = atoken_abi_file_path.open()
            atoken_abi = json.load(atoken_abi_file)
            atoken_abi_file.close()
            atoken_contract = value.eth.contract(abi=atoken_abi, decode_tuples=True)
            cls._atoken_contract = retry_with_backoff(
                atoken_contract,
                address=values.get("contract_address"),
            )

            pool_abi_file_path = Path(__file__).parent / "../abi/Pool.json"
            pool_abi_file = pool_abi_file_path.open()
            pool_abi = json.load(pool_abi_file)
            pool_abi_file.close()

            atoken_contract = cls._atoken_contract
            pool_address = retry_with_backoff(atoken_contract.functions.POOL().call)

            pool_contract = value.eth.contract(abi=pool_abi, decode_tuples=True)
            cls._pool_contract = retry_with_backoff(pool_contract, address=pool_address)

            cls._underlying_asset_address = retry_with_backoff(
                cls._atoken_contract.functions.UNDERLYING_ASSET_ADDRESS().call
            )

        except Exception as err:
            bt.logging.error("Failed to load contract!")
            bt.logging.error(err)

        return value

    def sync(self):
        """Syncs with chain"""
        try:
            pool_abi_file_path = Path(__file__).parent / "../abi/Pool.json"
            pool_abi_file = pool_abi_file_path.open()
            pool_abi = json.load(pool_abi_file)
            pool_abi_file.close()

            atoken_contract_onchain = self._atoken_contract
            pool_address = retry_with_backoff(
                atoken_contract_onchain.functions.POOL().call
            )

            pool_contract = self.web3_provider.eth.contract(
                abi=pool_abi, decode_tuples=True
            )
            self._pool_contract = retry_with_backoff(
                pool_contract, address=pool_address
            )

            self._underlying_asset_address = retry_with_backoff(
                self._atoken_contract.functions.UNDERLYING_ASSET_ADDRESS().call
            )

            self._reserve_data = retry_with_backoff(
                self._pool_contract.functions.getReserveData(
                    self._underlying_asset_address
                ).call
            )

            reserve_strat_abi_file_path = (
                Path(__file__).parent / "../abi/IReserveInterestRateStrategy.json"
            )
            reserve_strat_abi_file = reserve_strat_abi_file_path.open()
            reserve_strat_abi = json.load(reserve_strat_abi_file)
            reserve_strat_abi_file.close()

            strategy_contract = self.web3_provider.eth.contract(abi=reserve_strat_abi)
            self._strategy_contract = retry_with_backoff(
                strategy_contract, address=self._reserve_data.interestRateStrategyAddress
            )

            stable_debt_token_abi_file_path = (
                Path(__file__).parent / "../abi/IStableDebtToken.json"
            )
            stable_debt_token_abi_file = stable_debt_token_abi_file_path.open()
            stable_debt_token_abi = json.load(stable_debt_token_abi_file)
            stable_debt_token_abi_file.close()

            stable_debt_token_contract = self.web3_provider.eth.contract(
                abi=stable_debt_token_abi
            )
            stable_debt_token_contract = retry_with_backoff(
                stable_debt_token_contract,
                address=self._reserve_data.stableDebtTokenAddress,
            )

            (
                _,
                self._nextTotalStableDebt,
                self._nextAvgStableBorrowRate,
                _,
            ) = retry_with_backoff(
                stable_debt_token_contract.functions.getSupplyData().call
            )

            variable_debt_token_abi_file_path = (
                Path(__file__).parent / "../abi/IVariableDebtToken.json"
            )
            variable_debt_token_abi_file = variable_debt_token_abi_file_path.open()
            variable_debt_token_abi = json.load(variable_debt_token_abi_file)
            variable_debt_token_abi_file.close()

            variable_debt_token_contract = self.web3_provider.eth.contract(
                abi=variable_debt_token_abi
            )
            self._variable_debt_token_contract = retry_with_backoff(
                variable_debt_token_contract,
                address=self._reserve_data.variableDebtTokenAddress,
            )

            nextVariableBorrowIndex = self._reserve_data.variableBorrowIndex

            nextScaledVariableDebt = retry_with_backoff(
                self._variable_debt_token_contract.functions.scaledTotalSupply().call
            )
            self._totalVariableDebt = rayMul(nextScaledVariableDebt, nextVariableBorrowIndex)

        except Exception as err:
            bt.logging.error("Failed to sync to chain!")
            bt.logging.error(err)

    def supply_apy(self, amount: int) -> float:
        """Returns supply rate given new deposit amount"""
        try:
            reserveConfiguration = self._reserve_data.configuration
            reserveFactor = getReserveFactor(reserveConfiguration)

            (nextLiquidityRate, _, _) = retry_with_backoff(
                self._strategy_contract.functions.calculateInterestRates(
                    (
                        self._reserve_data.unbacked,
                        amount,
                        0,
                        self._nextTotalStableDebt,
                        self._totalVariableDebt,
                        self._nextAvgStableBorrowRate,
                        reserveFactor,
                        self._underlying_asset_address,
                        self._atoken_contract.address,
                    )
                ).call
            )

            # return liquidity_rate / 1e27
            return nextLiquidityRate / 1e27

        except Exception as e:
            bt.logging.error("Failed to retrieve supply apy!")
            bt.logging.error(e)

        return 0.0


# TODO: add different interest rate models in the future - we use a single simple model for now
def generate_assets_and_pools(rng_gen=np.random) -> Dict:  # generate pools
    assets_and_pools = {}

    pools = {
        str(x): {
            BasePool(
                pool_id=str(x),
                base_rate=randrange_float(
                    MIN_BASE_RATE, MAX_BASE_RATE, BASE_RATE_STEP, rng_gen=rng_gen
                ),
                base_slope=randrange_float(
                    MIN_SLOPE, MAX_SLOPE, SLOPE_STEP, rng_gen=rng_gen
                ),
                kink_slope=randrange_float(
                    MIN_KINK_SLOPE, MAX_KINK_SLOPE, SLOPE_STEP, rng_gen=rng_gen
                ),  # kink rate - kicks in after pool hits optimal util rate
                optimal_util_rate=randrange_float(
                    MIN_OPTIMAL_RATE,
                    MAX_OPTIMAL_RATE,
                    OPTIMAL_UTIL_STEP,
                    rng_gen=rng_gen,
                ),  # optimal util rate - after which the kink slope kicks in
                borrow_amount=format_num_prec(
                    POOL_RESERVE_SIZE
                    * randrange_float(
                        MIN_UTIL_RATE, MAX_UTIL_RATE, UTIL_RATE_STEP, rng_gen=rng_gen
                    )
                ),  # initial borrowed amount from pool
                reserve_size=POOL_RESERVE_SIZE,
            )
        }
        for x in range(NUM_POOLS)
    }

    assets_and_pools["total_assets"] = TOTAL_ASSETS
    assets_and_pools["pools"] = pools

    return assets_and_pools


# generate intial allocations for pools
def generate_initial_allocations_for_pools(
    assets_and_pools: Dict, size: int = NUM_POOLS, rng_gen=np.random
) -> Dict:
    nums = np.ones(size)
    allocs = nums / np.sum(nums) * assets_and_pools["total_assets"]
    allocations = {str(i): alloc for i, alloc in enumerate(allocs)}

    return allocations
