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

import math
from typing import Dict, Union
from enum import Enum

import json
from pydantic import BaseModel, Field, PrivateAttr, root_validator
from web3 import Web3
from web3.contract import Contract
import numpy as np
import bittensor as bt
from pathlib import Path

from sturdy.utils.ethmath import wei_div, wei_mul
from sturdy.utils.misc import (
    randrange_float,
    format_num_prec,
    retry_with_backoff,
    rayMul,
    getReserveFactor,
    ttl_cache,
)
from sturdy.constants import *


class BasePoolModel(BaseModel):
    """This model will primarily be used for synthetic requests"""

    pool_id: str = Field(..., description="uid of pool")
    base_rate: int = Field(..., description="base interest rate")
    base_slope: int = Field(..., description="base interest rate slope")
    kink_slope: int = Field(..., description="kink slope")
    optimal_util_rate: int = Field(..., description="optimal utilisation rate")
    borrow_amount: int = Field(..., description="borrow amount in wei")
    reserve_size: int = Field(..., description="pool reserve size in wei")

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
    def util_rate(self) -> int:
        return wei_div(self.borrow_amount, self.reserve_size)

    @property
    def borrow_rate(self) -> int:
        util_rate = self.util_rate
        interest_rate = (
            self.base_rate
            + wei_mul(wei_div(util_rate, self.optimal_util_rate), self.base_slope)
            if util_rate < self.optimal_util_rate
            else self.base_rate
            + self.base_slope
            + wei_mul(
                wei_div(
                    (util_rate - self.optimal_util_rate),
                    (1e18 - self.optimal_util_rate),
                ),
                self.kink_slope,
            )
        )

        return interest_rate

    @property
    def supply_rate(self):
        return wei_mul(self.util_rate, self.borrow_rate)


class ChainBasedPoolModel(BaseModel):
    """This serves as the base model of pools which need to pull data from on-chain

    Args:
        pool_id: (str),
        contract_address: (str),
    """

    pool_id: str = Field(..., description="uid of pool")
    contract_address: str = Field(..., description="address of contract to call")

    @root_validator
    def check_params(cls, values):
        if len(values.get("pool_id")) <= 0:
            raise ValueError("pool id is empty")
        if not Web3.is_address(values.get("contract_address")):
            raise ValueError("pool address is invalid!")

        return values

    def pool_init(self, **args):
        raise NotImplementedError("pool_init() has not been implemented!")

    def sync(self, **args):
        raise NotImplementedError("sync() has not been implemented!")

    def supply_rate(self, **args):
        raise NotImplementedError("sync() has not been implemented!")


class POOL_TYPES(str, Enum):
    DEFAULT = "DEFAULT"
    AAVE_V3 = "AAVE_V3"


class PoolFactory:
    @staticmethod
    def create_pool(
        pool_type: POOL_TYPES, **kwargs
    ) -> Union[BasePoolModel, ChainBasedPoolModel]:
        match pool_type:
            case POOL_TYPES.DEFAULT:
                return BasePool(**kwargs)
            case POOL_TYPES.AAVE_V3:
                return AaveV3DefaultInterestRatePool(**kwargs)
            case _:
                raise ValueError(f"Unknown product type: {pool_type}")


class AaveV3DefaultInterestRatePool(ChainBasedPoolModel):
    """This class defines the default pool type for Aave"""

    _atoken_contract: Contract = PrivateAttr()
    _pool_contract: Contract = PrivateAttr()
    _underlying_asset_contract: Contract = PrivateAttr()
    _underlying_asset_address: str = PrivateAttr()
    _reserve_data = PrivateAttr()
    _strategy_contract = PrivateAttr()
    _nextTotalStableDebt = PrivateAttr()
    _nextAvgStableBorrowRate = PrivateAttr()
    _variable_debt_token_contract = PrivateAttr()
    _totalVariableDebt = PrivateAttr()
    _initted: bool = PrivateAttr(False)
    _reserveFactor = PrivateAttr()
    _decimals: int = PrivateAttr()

    class Config:
        arbitrary_types_allowed = True

    def __hash__(self):
        return hash((self._atoken_contract.address, self._underlying_asset_address))

    def __eq__(self, other):
        if not isinstance(other, AaveV3DefaultInterestRatePool):
            return NotImplemented
        # Compare the attributes for equality
        return (self._atoken_contract.address, self._underlying_asset_address) == (
            other._atoken_contract.address,
            other._underlying_asset_address,
        )

    def pool_init(self, web3_provider: Web3):
        try:
            assert web3_provider.is_connected()
        except Exception as err:
            bt.logging.error("Failed to connect to Web3 instance!")
            bt.logging.error(err)

        try:
            atoken_abi_file_path = Path(__file__).parent / "../abi/AToken.json"
            atoken_abi_file = atoken_abi_file_path.open()
            atoken_abi = json.load(atoken_abi_file)
            atoken_abi_file.close()
            atoken_contract = web3_provider.eth.contract(
                abi=atoken_abi, decode_tuples=True
            )
            self._atoken_contract = retry_with_backoff(
                atoken_contract,
                address=self.contract_address,
            )

            pool_abi_file_path = Path(__file__).parent / "../abi/Pool.json"
            pool_abi_file = pool_abi_file_path.open()
            pool_abi = json.load(pool_abi_file)
            pool_abi_file.close()

            atoken_contract = self._atoken_contract
            pool_address = retry_with_backoff(atoken_contract.functions.POOL().call)

            pool_contract = web3_provider.eth.contract(abi=pool_abi, decode_tuples=True)
            self._pool_contract = retry_with_backoff(
                pool_contract, address=pool_address
            )

            self._underlying_asset_address = retry_with_backoff(
                self._atoken_contract.functions.UNDERLYING_ASSET_ADDRESS().call
            )

            erc20_abi_file_path = Path(__file__).parent / "../abi/IERC20.json"
            erc20_abi_file = erc20_abi_file_path.open()
            erc20_abi = json.load(erc20_abi_file)
            erc20_abi_file.close()

            underlying_asset_contract = web3_provider.eth.contract(
                abi=erc20_abi, decode_tuples=True
            )
            self._underlying_asset_contract = retry_with_backoff(
                underlying_asset_contract, address=self._underlying_asset_address
            )

            self._initted = True

        except Exception as err:
            bt.logging.error("Failed to load contract!")
            bt.logging.error(err)

        return web3_provider

    def sync(self, web3_provider: Web3):
        """Syncs with chain"""
        if not self._initted:
            self.pool_init(web3_provider)
        try:
            pool_abi_file_path = Path(__file__).parent / "../abi/Pool.json"
            pool_abi_file = pool_abi_file_path.open()
            pool_abi = json.load(pool_abi_file)
            pool_abi_file.close()

            atoken_contract_onchain = self._atoken_contract
            pool_address = retry_with_backoff(
                atoken_contract_onchain.functions.POOL().call
            )

            pool_contract = web3_provider.eth.contract(abi=pool_abi, decode_tuples=True)
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

            strategy_contract = web3_provider.eth.contract(abi=reserve_strat_abi)
            self._strategy_contract = retry_with_backoff(
                strategy_contract,
                address=self._reserve_data.interestRateStrategyAddress,
            )

            stable_debt_token_abi_file_path = (
                Path(__file__).parent / "../abi/IStableDebtToken.json"
            )
            stable_debt_token_abi_file = stable_debt_token_abi_file_path.open()
            stable_debt_token_abi = json.load(stable_debt_token_abi_file)
            stable_debt_token_abi_file.close()

            stable_debt_token_contract = web3_provider.eth.contract(
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

            variable_debt_token_contract = web3_provider.eth.contract(
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
            self._totalVariableDebt = rayMul(
                nextScaledVariableDebt, nextVariableBorrowIndex
            )

            reserveConfiguration = self._reserve_data.configuration
            self._reserveFactor = getReserveFactor(reserveConfiguration)
            self._decimals = retry_with_backoff(
                self._underlying_asset_contract.functions.decimals().call
            )

        except Exception as err:
            bt.logging.error("Failed to sync to chain!")
            bt.logging.error(err)

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self, amount: float) -> float:
        """Returns supply rate given new deposit amount"""
        try:
            # TODO: the returned supply rate is accurate only when we haven't already deposited anything into it
            # i.e. if we already have some tokens in the pool, and we would like to rebalance to allocate a certain amount
            # into them, then we wouldn't actually know the resulting supply rate accurately
            (nextLiquidityRate, _, _) = retry_with_backoff(
                self._strategy_contract.functions.calculateInterestRates(
                    (
                        self._reserve_data.unbacked,
                        int((amount * 10**self._decimals) // 1e18),
                        0,
                        self._nextTotalStableDebt,
                        self._totalVariableDebt,
                        self._nextAvgStableBorrowRate,
                        self._reserveFactor,
                        self._underlying_asset_address,
                        self._atoken_contract.address,
                    )
                ).call
            )

            # return liquidity_rate / 1e27
            return Web3.to_wei(nextLiquidityRate / 1e27, "ether")

        except Exception as e:
            bt.logging.error("Failed to retrieve supply apy!")
            bt.logging.error(e)

        return 0.0


# TODO: add different interest rate models in the future - we use a single simple model for now
def generate_assets_and_pools(rng_gen=np.random) -> Dict:  # generate pools
    assets_and_pools = {}

    pools = [
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
            borrow_amount=int(
                format_num_prec(
                    wei_mul(
                        POOL_RESERVE_SIZE,
                        randrange_float(
                            MIN_UTIL_RATE,
                            MAX_UTIL_RATE,
                            UTIL_RATE_STEP,
                            rng_gen=rng_gen,
                        ),
                    )
                )
            ),  # initial borrowed amount from pool
            reserve_size=POOL_RESERVE_SIZE,
        )
        for x in range(NUM_POOLS)
    ]

    pools = {str(pool.pool_id): pool for pool in pools}

    assets_and_pools["total_assets"] = math.floor(
        randrange_float(
            MIN_TOTAL_ASSETS, MAX_TOTAL_ASSETS, TOTAL_ASSETS_STEP, rng_gen=rng_gen
        )
    )
    assets_and_pools["pools"] = pools

    return assets_and_pools


# generate intial allocations for pools
def generate_initial_allocations_for_pools(
    assets_and_pools: Dict, rng_gen=np.random
) -> Dict:
    pools = assets_and_pools["pools"]
    alloc = assets_and_pools["total_assets"] / len(pools)
    allocations = {str(uid): alloc for uid in pools}

    return allocations
