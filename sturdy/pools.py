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

import json
import math
from decimal import Decimal
from enum import IntEnum
from pathlib import Path
from typing import Any, ClassVar

import bittensor as bt
import numpy as np
from eth_account import Account
from pydantic import BaseModel, Field, PrivateAttr, root_validator, validator
from web3 import Web3
from web3.constants import ADDRESS_ZERO
from web3.contract.contract import Contract
from web3.types import BlockData

from sturdy.constants import *
from sturdy.pool_registry.pool_registry import POOL_REGISTRY
from sturdy.utils.ethmath import wei_div, wei_mul
from sturdy.utils.misc import (
    getReserveFactor,
    rayMul,
    retry_with_backoff,
    ttl_cache,
)


class POOL_TYPES(IntEnum):
    STURDY_SILO = 1
    AAVE_DEFAULT = 2
    DAI_SAVINGS = 3
    COMPOUND_V3 = 4
    MORPHO = 5
    YEARN_V3 = 6
    AAVE_TARGET = 7


def get_minimum_allocation(pool: "ChainBasedPoolModel") -> int:
    borrow_amount = 0
    our_supply = 0
    assets_available = 0
    match pool.pool_type:
        case POOL_TYPES.STURDY_SILO:
            borrow_amount = pool._totalBorrow
            our_supply = pool._user_deposits
            assets_available = max(0, pool._total_supplied_assets - borrow_amount)
        case T if T in (POOL_TYPES.AAVE_DEFAULT, POOL_TYPES.AAVE_TARGET):
            # borrow amount for aave pools is total_stable_debt + total_variable_debt
            borrow_amount = ((pool._nextTotalStableDebt * int(1e18)) // int(10**pool._decimals)) + (
                (pool._totalVariableDebt * int(1e18)) // int(10**pool._decimals)
            )
            our_supply = pool._user_deposits
            assets_available = max(0, ((pool._total_supplied_assets * int(1e18)) // int(10**pool._decimals)) - borrow_amount)
        case POOL_TYPES.COMPOUND_V3:
            borrow_amount = pool._total_borrow
            our_supply = pool._user_deposits
            assets_available = max(0, pool._total_supplied_assets - borrow_amount)
        case POOL_TYPES.MORPHO:
            borrow_amount = pool._curr_borrows
            our_supply = pool._user_deposits
            assets_available = max(0, pool._total_supplied_assets - borrow_amount)
        case POOL_TYPES.YEARN_V3:
            return max(0, pool._user_deposits - pool._max_withdraw)
        case POOL_TYPES.DAI_SAVINGS:
            pass  # TODO: is there a more appropriate way to go about this?
        case _:  # not a valid pool type
            return 1

    return 0 if borrow_amount <= assets_available else assets_available if our_supply >= assets_available else 0


def check_allocations(
    assets_and_pools: dict, allocations: dict[str, int], alloc_threshold: float = TOTAL_ALLOC_THRESHOLD
) -> bool:
    """
    Checks allocations from miner.

    Args:
    - assets_and_pools (dict[str, Union[dict[str, int], int]]): The assets and pools which the allocations are for.
    - allocations (dict[str, int]): The allocations to validate.

    Returns:
    - bool: Represents if allocations are valid.
    """

    # Ensure the allocations are provided and valid
    if not allocations or not isinstance(allocations, dict):
        return False

    # Ensure the 'total_assets' key exists in assets_and_pools and is a valid number
    to_allocate = assets_and_pools.get("total_assets")
    if to_allocate is None or not isinstance(to_allocate, int):
        return False

    to_allocate = Decimal(str(to_allocate))
    total_allocated = Decimal(0)
    total_assets = assets_and_pools["total_assets"]

    # Check allocations
    for allocation in allocations.values():
        try:
            allocation_value = Decimal(str(allocation))
        except (ValueError, TypeError):
            return False

        if allocation_value < 0:
            return False

        total_allocated += allocation_value

        if total_allocated > to_allocate:
            return False

    # Ensure total allocated does not exceed the total assets, and that most assets have been allocated
    if total_allocated > to_allocate or total_allocated < int(alloc_threshold * total_assets):
        return False

    pools = assets_and_pools["pools"]
    # check if allocations are above the borrow amounts
    for pool_uid, pool in pools.items():
        allocation = allocations.get(pool_uid, 0)
        min_alloc = get_minimum_allocation(pool)

        if allocation < min_alloc:
            return False

    return True


class ChainBasedPoolModel(BaseModel):
    """This serves as the base model of pools which need to pull data from on-chain

    Args:
        contract_address: (str),
    """

    class Config:
        use_enum_values = True  # This will use the enum's value instead of the enum itself
        smart_union = True

    pool_type: POOL_TYPES | int | str = Field(..., description="type of pool")
    user_address: str = Field(
        default=ADDRESS_ZERO,
        description="address of the 'user' - used for various on-chain calls",
    )
    contract_address: str = Field(default=ADDRESS_ZERO, description="address of contract to call")

    _initted: bool = PrivateAttr(False)  # noqa: FBT003

    @validator("pool_type", pre=True)
    def validator_pool_type(cls, value) -> POOL_TYPES | int | str:
        if isinstance(value, POOL_TYPES):
            return value
        if isinstance(value, int):
            return POOL_TYPES(value)
        if isinstance(value, str):
            try:
                return POOL_TYPES[value]
            except KeyError:
                raise ValueError(f"Invalid enum name: {value}")  # noqa: B904
        raise ValueError(f"Invalid value: {value}")

    @root_validator
    def check_params(cls, values):  # noqa: ANN201
        if not Web3.is_address(values.get("contract_address")):
            raise ValueError("pool address is invalid!")
        if not Web3.is_address(values.get("user_address")):
            raise ValueError("user address is invalid!")

        return values

    def pool_init(self, **args: Any) -> None:
        raise NotImplementedError("pool_init() has not been implemented!")

    def sync(self, **args: Any) -> None:
        raise NotImplementedError("sync() has not been implemented!")

    def supply_rate(self, **args: Any) -> int:
        raise NotImplementedError("supply_rate() has not been implemented!")


class PoolFactory:
    @staticmethod
    def create_pool(pool_type: POOL_TYPES, **kwargs: Any) -> ChainBasedPoolModel:
        match pool_type:
            case POOL_TYPES.AAVE_DEFAULT:
                return AaveV3DefaultInterestRateV2Pool(**kwargs)
            case POOL_TYPES.STURDY_SILO:
                return VariableInterestSturdySiloStrategy(**kwargs)
            case POOL_TYPES.DAI_SAVINGS:
                return DaiSavingsRate(**kwargs)
            case POOL_TYPES.COMPOUND_V3:
                return CompoundV3Pool(**kwargs)
            case POOL_TYPES.MORPHO:
                return MorphoVault(**kwargs)
            case POOL_TYPES.YEARN_V3:
                return YearnV3Vault(**kwargs)
            case POOL_TYPES.AAVE_TARGET:
                return AaveV3RateTargetBaseInterestRatePool(**kwargs)
            case _:
                raise ValueError(f"Unknown pool type: {pool_type}")


class AaveV3DefaultInterestRateV2Pool(ChainBasedPoolModel):
    """This class defines the default pool type for Aave"""

    pool_type: POOL_TYPES = Field(default=POOL_TYPES.AAVE_DEFAULT, const=True, description="type of pool")

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
    _reserveFactor = PrivateAttr()
    _user_deposits: int = PrivateAttr()
    _total_supplied_assets: int = PrivateAttr()
    _decimals: int = PrivateAttr()
    _user_asset_balance: int = PrivateAttr()
    _normalized_income: int = PrivateAttr()

    class Config:
        arbitrary_types_allowed = True

    def __hash__(self) -> int:
        return hash((self._atoken_contract.address, self._underlying_asset_address))

    def __eq__(self, other) -> bool:
        if not isinstance(other, AaveV3DefaultInterestRateV2Pool):
            return NotImplemented
        # Compare the attributes for equality
        return (self._atoken_contract.address, self._underlying_asset_address) == (
            other._atoken_contract.address,
            other._underlying_asset_address,
        )

    def pool_init(self, web3_provider: Web3) -> None:
        try:
            assert web3_provider.is_connected()
        except Exception as err:
            bt.logging.error("Failed to connect to Web3 instance!")
            bt.logging.error(err)  # type: ignore[]

        try:
            atoken_abi_file_path = Path(__file__).parent / "abi/AToken.json"
            atoken_abi_file = atoken_abi_file_path.open()
            atoken_abi = json.load(atoken_abi_file)
            atoken_abi_file.close()
            atoken_contract = web3_provider.eth.contract(abi=atoken_abi, decode_tuples=True)
            self._atoken_contract = retry_with_backoff(
                atoken_contract,
                address=self.contract_address,
            )

            pool_abi_file_path = Path(__file__).parent / "abi/Pool.json"
            pool_abi_file = pool_abi_file_path.open()
            pool_abi = json.load(pool_abi_file)
            pool_abi_file.close()

            atoken_contract = self._atoken_contract
            pool_address = retry_with_backoff(atoken_contract.functions.POOL().call)

            pool_contract = web3_provider.eth.contract(abi=pool_abi, decode_tuples=True)
            self._pool_contract = retry_with_backoff(pool_contract, address=pool_address)

            self._underlying_asset_address = retry_with_backoff(
                self._atoken_contract.functions.UNDERLYING_ASSET_ADDRESS().call,
            )

            erc20_abi_file_path = Path(__file__).parent / "abi/IERC20.json"
            erc20_abi_file = erc20_abi_file_path.open()
            erc20_abi = json.load(erc20_abi_file)
            erc20_abi_file.close()

            underlying_asset_contract = web3_provider.eth.contract(abi=erc20_abi, decode_tuples=True)
            self._underlying_asset_contract = retry_with_backoff(
                underlying_asset_contract,
                address=self._underlying_asset_address,
            )

            self._total_supplied_assets = retry_with_backoff(self._atoken_contract.functions.totalSupply().call)

            self._initted = True

        except Exception as err:
            bt.logging.error("Failed to load contract!")
            bt.logging.error(err)  # type: ignore[]

    def sync(self, web3_provider: Web3) -> None:
        """Syncs with chain"""
        if not self._initted:
            self.pool_init(web3_provider)
        try:
            pool_abi_file_path = Path(__file__).parent / "abi/Pool.json"
            pool_abi_file = pool_abi_file_path.open()
            pool_abi = json.load(pool_abi_file)
            pool_abi_file.close()

            atoken_contract_onchain = self._atoken_contract
            pool_address = retry_with_backoff(atoken_contract_onchain.functions.POOL().call)

            pool_contract = web3_provider.eth.contract(abi=pool_abi, decode_tuples=True)
            self._pool_contract = retry_with_backoff(pool_contract, address=pool_address)

            self._underlying_asset_address = retry_with_backoff(
                self._atoken_contract.functions.UNDERLYING_ASSET_ADDRESS().call,
            )

            self._reserve_data = retry_with_backoff(
                self._pool_contract.functions.getReserveData(self._underlying_asset_address).call,
            )

            reserve_strat_abi_file_path = Path(__file__).parent / "abi/IReserveInterestRateStrategy.json"
            reserve_strat_abi_file = reserve_strat_abi_file_path.open()
            reserve_strat_abi = json.load(reserve_strat_abi_file)
            reserve_strat_abi_file.close()

            strategy_contract = web3_provider.eth.contract(abi=reserve_strat_abi)
            self._strategy_contract = retry_with_backoff(
                strategy_contract,
                address=self._reserve_data.interestRateStrategyAddress,
            )

            stable_debt_token_abi_file_path = Path(__file__).parent / "abi/IStableDebtToken.json"
            stable_debt_token_abi_file = stable_debt_token_abi_file_path.open()
            stable_debt_token_abi = json.load(stable_debt_token_abi_file)
            stable_debt_token_abi_file.close()

            stable_debt_token_contract = web3_provider.eth.contract(abi=stable_debt_token_abi)
            stable_debt_token_contract = retry_with_backoff(
                stable_debt_token_contract,
                address=self._reserve_data.stableDebtTokenAddress,
            )

            (
                _,
                self._nextTotalStableDebt,
                self._nextAvgStableBorrowRate,
                _,
            ) = retry_with_backoff(stable_debt_token_contract.functions.getSupplyData().call)

            variable_debt_token_abi_file_path = Path(__file__).parent / "abi/IVariableDebtToken.json"
            variable_debt_token_abi_file = variable_debt_token_abi_file_path.open()
            variable_debt_token_abi = json.load(variable_debt_token_abi_file)
            variable_debt_token_abi_file.close()

            variable_debt_token_contract = web3_provider.eth.contract(abi=variable_debt_token_abi)
            self._variable_debt_token_contract = retry_with_backoff(
                variable_debt_token_contract,
                address=self._reserve_data.variableDebtTokenAddress,
            )

            nextVariableBorrowIndex = self._reserve_data.variableBorrowIndex

            nextScaledVariableDebt = retry_with_backoff(self._variable_debt_token_contract.functions.scaledTotalSupply().call)
            self._totalVariableDebt = rayMul(nextScaledVariableDebt, nextVariableBorrowIndex)

            reserveConfiguration = self._reserve_data.configuration
            self._reserveFactor = getReserveFactor(reserveConfiguration)
            self._decimals = retry_with_backoff(self._underlying_asset_contract.functions.decimals().call)
            self._user_deposits = retry_with_backoff(
                self._atoken_contract.functions.balanceOf(Web3.to_checksum_address(self.user_address)).call
            )

            self._user_asset_balance = retry_with_backoff(
                self._underlying_asset_contract.functions.balanceOf(Web3.to_checksum_address(self.user_address)).call
            )

            self._normalized_income = retry_with_backoff(
                self._pool_contract.functions.getReserveNormalizedIncome(self._underlying_asset_address).call
            )

        except Exception as err:
            bt.logging.error("Failed to sync to chain!")
            bt.logging.error(err)  # type: ignore[]

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self, amount: int) -> int:
        """Returns supply rate given new deposit amount"""
        try:
            already_deposited = self._user_deposits
            delta = amount - already_deposited
            to_deposit = max(0, delta)
            to_remove = abs(delta) if delta < 0 else 0

            (nextLiquidityRate, _) = retry_with_backoff(
                self._strategy_contract.functions.calculateInterestRates(
                    (
                        self._reserve_data.unbacked,
                        int(to_deposit),
                        int(to_remove),
                        self._nextTotalStableDebt + self._totalVariableDebt,
                        self._reserveFactor,
                        self._underlying_asset_address,
                        True,
                        already_deposited,
                    ),
                ).call,
            )

            return Web3.to_wei(nextLiquidityRate / 1e27, "ether")

        except Exception as e:
            bt.logging.error("Failed to retrieve supply apy!")
            bt.logging.error(e)  # type: ignore[]

        return 0


class AaveV3RateTargetBaseInterestRatePool(ChainBasedPoolModel):
    """This class defines the default pool type for Aave"""

    pool_type: POOL_TYPES = Field(default=POOL_TYPES.AAVE_TARGET, const=True, description="type of pool")

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
    _reserveFactor = PrivateAttr()
    _user_deposits: int = PrivateAttr()
    _total_supplied_assets: int = PrivateAttr()
    _decimals: int = PrivateAttr()
    _user_asset_balance: int = PrivateAttr()
    _normalized_income: int = PrivateAttr()

    class Config:
        arbitrary_types_allowed = True

    def __hash__(self) -> int:
        return hash((self._atoken_contract.address, self._underlying_asset_address))

    def __eq__(self, other) -> bool:
        if not isinstance(other, AaveV3DefaultInterestRateV2Pool):
            return NotImplemented
        # Compare the attributes for equality
        return (self._atoken_contract.address, self._underlying_asset_address) == (
            other._atoken_contract.address,
            other._underlying_asset_address,
        )

    def pool_init(self, web3_provider: Web3) -> None:
        try:
            assert web3_provider.is_connected()
        except Exception as err:
            bt.logging.error("Failed to connect to Web3 instance!")
            bt.logging.error(err)  # type: ignore[]

        try:
            atoken_abi_file_path = Path(__file__).parent / "abi/AToken.json"
            atoken_abi_file = atoken_abi_file_path.open()
            atoken_abi = json.load(atoken_abi_file)
            atoken_abi_file.close()
            atoken_contract = web3_provider.eth.contract(abi=atoken_abi, decode_tuples=True)
            self._atoken_contract = retry_with_backoff(
                atoken_contract,
                address=self.contract_address,
            )

            pool_abi_file_path = Path(__file__).parent / "abi/Pool.json"
            pool_abi_file = pool_abi_file_path.open()
            pool_abi = json.load(pool_abi_file)
            pool_abi_file.close()

            atoken_contract = self._atoken_contract
            pool_address = retry_with_backoff(atoken_contract.functions.POOL().call)

            pool_contract = web3_provider.eth.contract(abi=pool_abi, decode_tuples=True)
            self._pool_contract = retry_with_backoff(pool_contract, address=pool_address)

            self._underlying_asset_address = retry_with_backoff(
                self._atoken_contract.functions.UNDERLYING_ASSET_ADDRESS().call,
            )

            erc20_abi_file_path = Path(__file__).parent / "abi/IERC20.json"
            erc20_abi_file = erc20_abi_file_path.open()
            erc20_abi = json.load(erc20_abi_file)
            erc20_abi_file.close()

            underlying_asset_contract = web3_provider.eth.contract(abi=erc20_abi, decode_tuples=True)
            self._underlying_asset_contract = retry_with_backoff(
                underlying_asset_contract,
                address=self._underlying_asset_address,
            )

            self._total_supplied_assets = retry_with_backoff(self._atoken_contract.functions.totalSupply().call)

            self._initted = True

        except Exception as err:
            bt.logging.error("Failed to load contract!")
            bt.logging.error(err)  # type: ignore[]

    def sync(self, web3_provider: Web3) -> None:
        """Syncs with chain"""
        if not self._initted:
            self.pool_init(web3_provider)
        try:
            pool_abi_file_path = Path(__file__).parent / "abi/Pool.json"
            pool_abi_file = pool_abi_file_path.open()
            pool_abi = json.load(pool_abi_file)
            pool_abi_file.close()

            atoken_contract_onchain = self._atoken_contract
            pool_address = retry_with_backoff(atoken_contract_onchain.functions.POOL().call)

            pool_contract = web3_provider.eth.contract(abi=pool_abi, decode_tuples=True)
            self._pool_contract = retry_with_backoff(pool_contract, address=pool_address)

            self._underlying_asset_address = retry_with_backoff(
                self._atoken_contract.functions.UNDERLYING_ASSET_ADDRESS().call,
            )

            self._reserve_data = retry_with_backoff(
                self._pool_contract.functions.getReserveData(self._underlying_asset_address).call,
            )

            reserve_strat_abi_file_path = Path(__file__).parent / "abi/RateTargetBaseInterestRateStrategy.json"
            reserve_strat_abi_file = reserve_strat_abi_file_path.open()
            reserve_strat_abi = json.load(reserve_strat_abi_file)
            reserve_strat_abi_file.close()

            strategy_contract = web3_provider.eth.contract(abi=reserve_strat_abi)
            self._strategy_contract = retry_with_backoff(
                strategy_contract,
                address=self._reserve_data.interestRateStrategyAddress,
            )

            stable_debt_token_abi_file_path = Path(__file__).parent / "abi/IStableDebtToken.json"
            stable_debt_token_abi_file = stable_debt_token_abi_file_path.open()
            stable_debt_token_abi = json.load(stable_debt_token_abi_file)
            stable_debt_token_abi_file.close()

            stable_debt_token_contract = web3_provider.eth.contract(abi=stable_debt_token_abi)
            stable_debt_token_contract = retry_with_backoff(
                stable_debt_token_contract,
                address=self._reserve_data.stableDebtTokenAddress,
            )

            (
                _,
                self._nextTotalStableDebt,
                self._nextAvgStableBorrowRate,
                _,
            ) = retry_with_backoff(stable_debt_token_contract.functions.getSupplyData().call)

            variable_debt_token_abi_file_path = Path(__file__).parent / "abi/IVariableDebtToken.json"
            variable_debt_token_abi_file = variable_debt_token_abi_file_path.open()
            variable_debt_token_abi = json.load(variable_debt_token_abi_file)
            variable_debt_token_abi_file.close()

            variable_debt_token_contract = web3_provider.eth.contract(abi=variable_debt_token_abi)
            self._variable_debt_token_contract = retry_with_backoff(
                variable_debt_token_contract,
                address=self._reserve_data.variableDebtTokenAddress,
            )

            nextVariableBorrowIndex = self._reserve_data.variableBorrowIndex

            nextScaledVariableDebt = retry_with_backoff(self._variable_debt_token_contract.functions.scaledTotalSupply().call)
            self._totalVariableDebt = rayMul(nextScaledVariableDebt, nextVariableBorrowIndex)

            reserveConfiguration = self._reserve_data.configuration
            self._reserveFactor = getReserveFactor(reserveConfiguration)
            self._decimals = retry_with_backoff(self._underlying_asset_contract.functions.decimals().call)
            self._user_deposits = retry_with_backoff(
                self._atoken_contract.functions.balanceOf(Web3.to_checksum_address(self.user_address)).call
            )

            self._user_asset_balance = retry_with_backoff(
                self._underlying_asset_contract.functions.balanceOf(Web3.to_checksum_address(self.user_address)).call
            )

            self._normalized_income = retry_with_backoff(
                self._pool_contract.functions.getReserveNormalizedIncome(self._underlying_asset_address).call
            )

        except Exception as err:
            bt.logging.error("Failed to sync to chain!")
            bt.logging.error(err)  # type: ignore[]

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self, amount: int) -> int:
        """Returns supply rate given new deposit amount"""
        try:
            already_deposited = self._user_deposits
            delta = amount - already_deposited
            to_deposit = max(0, delta)
            to_remove = abs(delta) if delta < 0 else 0

            (nextLiquidityRate, _, _) = retry_with_backoff(
                self._strategy_contract.functions.calculateInterestRates(
                    (
                        self._reserve_data.unbacked,
                        int(to_deposit),
                        int(to_remove),
                        self._nextTotalStableDebt,
                        self._totalVariableDebt,
                        self._nextAvgStableBorrowRate,
                        self._reserveFactor,
                        self._underlying_asset_address,
                        self._atoken_contract.address,
                    ),
                ).call,
            )

            return Web3.to_wei(nextLiquidityRate / 1e27, "ether")

        except Exception as e:
            bt.logging.error("Failed to retrieve supply apy!")
            bt.logging.error(e)  # type: ignore[]

        return 0


class VariableInterestSturdySiloStrategy(ChainBasedPoolModel):
    pool_type: POOL_TYPES = Field(POOL_TYPES.STURDY_SILO, const=True, description="type of pool")

    _silo_strategy_contract: Contract = PrivateAttr()
    _pair_contract: Contract = PrivateAttr()
    _rate_model_contract: Contract = PrivateAttr()

    _user_deposits: int = PrivateAttr()
    _util_prec: int = PrivateAttr()
    _fee_prec: int = PrivateAttr()
    _total_supplied_assets: Any = PrivateAttr()
    _totalBorrow: Any = PrivateAttr()
    _current_rate_info = PrivateAttr()
    _rate_prec: int = PrivateAttr()

    _block: BlockData = PrivateAttr()

    _decimals: int = PrivateAttr()
    _asset: Contract = PrivateAttr()
    _user_asset_balance: int = PrivateAttr()
    _user_total_assets: int = PrivateAttr()
    _share_price: Contract = PrivateAttr()

    def __hash__(self) -> int:
        return hash((self._silo_strategy_contract.address, self._pair_contract))

    def __eq__(self, other) -> bool:
        if not isinstance(other, VariableInterestSturdySiloStrategy):
            return NotImplemented
        # Compare the attributes for equality
        return (self._silo_strategy_contract.address, self._pair_contract) == (
            other._silo_strategy_contract.address,
            other._pair_contract.address,
        )

    def pool_init(self, web3_provider: Web3) -> None:
        try:
            assert web3_provider.is_connected()
        except Exception as err:
            bt.logging.error("Failed to connect to Web3 instance!")
            bt.logging.error(err)  # type: ignore[]

        try:
            silo_strategy_abi_file_path = Path(__file__).parent / "abi/SturdySiloStrategy.json"
            silo_strategy_abi_file = silo_strategy_abi_file_path.open()
            silo_strategy_abi = json.load(silo_strategy_abi_file)
            silo_strategy_abi_file.close()

            silo_strategy_contract = web3_provider.eth.contract(abi=silo_strategy_abi, decode_tuples=True)
            self._silo_strategy_contract = retry_with_backoff(silo_strategy_contract, address=self.contract_address)

            pair_abi_file_path = Path(__file__).parent / "abi/SturdyPair.json"
            pair_abi_file = pair_abi_file_path.open()
            pair_abi = json.load(pair_abi_file)
            pair_abi_file.close()

            pair_contract_address = retry_with_backoff(self._silo_strategy_contract.functions.pair().call)
            pair_contract = web3_provider.eth.contract(abi=pair_abi, decode_tuples=True)
            self._pair_contract = retry_with_backoff(pair_contract, address=pair_contract_address)

            rate_model_abi_file_path = Path(__file__).parent / "abi/VariableInterestRate.json"
            rate_model_abi_file = rate_model_abi_file_path.open()
            rate_model_abi = json.load(rate_model_abi_file)
            rate_model_abi_file.close()

            rate_model_contract_address = retry_with_backoff(self._pair_contract.functions.rateContract().call)
            rate_model_contract = web3_provider.eth.contract(abi=rate_model_abi, decode_tuples=True)
            self._rate_model_contract = retry_with_backoff(rate_model_contract, address=rate_model_contract_address)
            self._decimals = retry_with_backoff(self._pair_contract.functions.decimals().call)

            erc20_abi_file_path = Path(__file__).parent / "abi/IERC20.json"
            erc20_abi_file = erc20_abi_file_path.open()
            erc20_abi = json.load(erc20_abi_file)
            erc20_abi_file.close()

            asset_address = retry_with_backoff(self._pair_contract.functions.asset().call)
            asset_contract = web3_provider.eth.contract(abi=erc20_abi, decode_tuples=True)
            self._asset = retry_with_backoff(asset_contract, address=asset_address)

            self._initted = True

        except Exception as e:
            bt.logging.error(e)  # type: ignore[]

    def sync(self, web3_provider: Web3) -> None:
        """Syncs with chain"""
        if not self._initted:
            self.pool_init(web3_provider)

        user_shares = retry_with_backoff(self._pair_contract.functions.balanceOf(self.contract_address).call)
        self._user_deposits = retry_with_backoff(self._pair_contract.functions.convertToAssets(user_shares).call)

        constants = retry_with_backoff(self._pair_contract.functions.getConstants().call)
        self._util_prec = constants[2]
        self._fee_prec = constants[3]
        self._total_supplied_assets: Any = retry_with_backoff(self._pair_contract.functions.totalAssets().call)
        self._totalBorrow: Any = retry_with_backoff(self._pair_contract.functions.totalBorrow().call).amount

        self._block = web3_provider.eth.get_block("latest")

        self._current_rate_info = retry_with_backoff(self._pair_contract.functions.currentRateInfo().call)

        self._rate_prec = retry_with_backoff(self._rate_model_contract.functions.RATE_PREC().call)

        self._user_asset_balance = retry_with_backoff(self._asset.functions.balanceOf(self.user_address).call)

        # get current price per share
        self._share_price = retry_with_backoff(self._pair_contract.functions.pricePerShare().call)

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self, amount: int) -> int:
        # amount scaled down to the asset's decimals from 18 decimals (wei)
        delta = amount - self._user_deposits

        """Returns supply rate given new deposit amount"""
        util_rate = int((self._util_prec * self._totalBorrow) // (self._total_supplied_assets + delta))

        last_update_timestamp = self._current_rate_info.lastTimestamp
        current_timestamp = self._block["timestamp"]
        delta_time = int(current_timestamp - last_update_timestamp)

        protocol_fee = self._current_rate_info.feeToProtocolRate
        (new_rate_per_sec, _) = retry_with_backoff(
            self._rate_model_contract.functions.getNewRate(
                delta_time,
                util_rate,
                int(self._current_rate_info.fullUtilizationRate),
            ).call,
        )

        return int(
            new_rate_per_sec
            * 31536000
            * 1e18
            * util_rate
            // self._rate_prec
            // self._util_prec
            * (1 - (protocol_fee / self._fee_prec)),
        )  # (rate_per_sec_pct * seconds_in_year * util_rate_pct) * 1e18


class CompoundV3Pool(ChainBasedPoolModel):
    """Model for Compound V3 Pools"""

    pool_type: POOL_TYPES = Field(POOL_TYPES.COMPOUND_V3, const=True, description="type of pool")

    _ctoken_contract: Contract = PrivateAttr()
    _base_oracle_contract: Contract = PrivateAttr()
    _reward_oracle_contract: Contract = PrivateAttr()
    _base_token_contract: Contract = PrivateAttr()
    _reward_token_contract: Contract = PrivateAttr()
    _base_token_price: float = PrivateAttr()
    _reward_token_price: float = PrivateAttr()
    _base_decimals: int = PrivateAttr()
    _total_borrow: int = PrivateAttr()
    _user_deposits: int = PrivateAttr()
    _total_supplied_assets: int = PrivateAttr()

    _CompoundTokenMap: dict = {
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",  # WETH -> ETH
    }

    def pool_init(self, web3_provider: Web3) -> None:
        comet_abi_file_path = Path(__file__).parent / "abi/Comet.json"
        comet_abi_file = comet_abi_file_path.open()
        comet_abi = json.load(comet_abi_file)
        comet_abi_file.close()

        # ctoken contract
        ctoken_contract = web3_provider.eth.contract(abi=comet_abi, decode_tuples=True)
        self._ctoken_contract = retry_with_backoff(ctoken_contract, address=self.contract_address)

        oracle_abi_file_path = Path(__file__).parent / "abi/EACAggregatorProxy.json"
        oracle_abi_file = oracle_abi_file_path.open()
        oracle_abi = json.load(oracle_abi_file)
        oracle_abi_file.close()

        feed_registry_abi_file_path = Path(__file__).parent / "abi/FeedRegistry.json"
        feed_registry_abi_file = feed_registry_abi_file_path.open()
        feed_registry_abi = json.load(feed_registry_abi_file)
        feed_registry_abi_file.close()

        chainlink_registry_address = "0x47Fb2585D2C56Fe188D0E6ec628a38b74fCeeeDf"  # chainlink registry address on eth mainnet
        usd_address = "0x0000000000000000000000000000000000000348"  # follows: https://en.wikipedia.org/wiki/ISO_4217
        chainlink_registry = web3_provider.eth.contract(abi=feed_registry_abi, decode_tuples=True)

        chainlink_registry_contract = retry_with_backoff(chainlink_registry, address=chainlink_registry_address)

        base_token_address = retry_with_backoff(self._ctoken_contract.functions.baseToken().call)
        asset_address = self._CompoundTokenMap.get(base_token_address, base_token_address)

        base_oracle_address = retry_with_backoff(
            chainlink_registry_contract.functions.getFeed(asset_address, usd_address).call,
        )
        base_oracle_contract = web3_provider.eth.contract(abi=oracle_abi, decode_tuples=True)
        self._base_oracle_contract = retry_with_backoff(base_oracle_contract, address=base_oracle_address)

        reward_oracle_address = "0xdbd020CAeF83eFd542f4De03e3cF0C28A4428bd5"  # TODO: COMP price feed address
        reward_oracle_contract = web3_provider.eth.contract(abi=oracle_abi, decode_tuples=True)
        self._reward_oracle_contract = retry_with_backoff(reward_oracle_contract, address=reward_oracle_address)

        self._initted = True

    def sync(self, web3_provider: Web3) -> None:
        if not self._initted:
            self.pool_init(web3_provider)

        # get token prices - in wei
        base_decimals = retry_with_backoff(self._base_oracle_contract.functions.decimals().call)
        self._base_decimals = base_decimals
        reward_decimals = retry_with_backoff(self._reward_oracle_contract.functions.decimals().call)
        self._total_borrow = retry_with_backoff(self._ctoken_contract.functions.totalBorrow().call)

        self._base_token_price = (
            retry_with_backoff(self._base_oracle_contract.functions.latestAnswer().call) / 10**base_decimals
        )
        self._reward_token_price = (
            retry_with_backoff(self._reward_oracle_contract.functions.latestAnswer().call) / 10**reward_decimals
        )

        self._user_deposits = retry_with_backoff(self._ctoken_contract.functions.balanceOf(self.user_address).call)
        self._total_supplied_assets = retry_with_backoff(self._ctoken_contract.functions.totalSupply().call)

    def supply_rate(self, amount: int) -> int:
        # amount scaled down to the asset's decimals from 18 decimals (wei)
        # get pool supply rate (base token)
        already_in_pool = self._user_deposits

        delta = amount - already_in_pool
        new_supply = self._total_supplied_assets + delta
        current_borrows = self._total_borrow

        utilization = wei_div(current_borrows, new_supply)
        seconds_per_year = 31536000
        seconds_per_day = 86400

        pool_rate = retry_with_backoff(self._ctoken_contract.functions.getSupplyRate(utilization).call) * seconds_per_year

        base_scale = retry_with_backoff(self._ctoken_contract.functions.baseScale().call)
        conv_total_supply = new_supply / base_scale

        base_index_scale = retry_with_backoff(self._ctoken_contract.functions.baseIndexScale().call)
        base_tracking_supply_speed = retry_with_backoff(self._ctoken_contract.functions.baseTrackingSupplySpeed().call)
        reward_per_day = base_tracking_supply_speed / base_index_scale * seconds_per_day
        comp_rate = 0

        if conv_total_supply * self._base_token_price > 0:
            comp_rate = Web3.to_wei(
                self._reward_token_price * reward_per_day / (conv_total_supply * self._base_token_price) * 365,
                "ether",
            )

        return int(pool_rate + comp_rate)


class DaiSavingsRate(ChainBasedPoolModel):
    """Model for DAI Savings Rate"""

    pool_type: POOL_TYPES = Field(POOL_TYPES.DAI_SAVINGS, const=True, description="type of pool")

    _sdai_contract: Contract = PrivateAttr()
    _pot_contract: Contract = PrivateAttr()

    def __hash__(self) -> int:
        return hash(self._sdai_contract.address)

    def __eq__(self, other) -> bool:
        if not isinstance(other, VariableInterestSturdySiloStrategy):
            return NotImplemented
        # Compare the attributes for equality
        return self._sdai_contract.address == other._sdai_contract.address  # type: ignore[]

    def pool_init(self, web3_provider: Web3) -> None:
        sdai_abi_file_path = Path(__file__).parent / "abi/SavingsDai.json"
        sdai_abi_file = sdai_abi_file_path.open()
        sdai_abi = json.load(sdai_abi_file)
        sdai_abi_file.close()

        sdai_contract = web3_provider.eth.contract(abi=sdai_abi, decode_tuples=True)
        self._sdai_contract = retry_with_backoff(sdai_contract, address=self.contract_address)

        pot_abi_file_path = Path(__file__).parent / "abi/Pot.json"
        pot_abi_file = pot_abi_file_path.open()
        pot_abi = json.load(pot_abi_file)
        pot_abi_file.close()

        pot_address = retry_with_backoff(self._sdai_contract.functions.pot().call)

        pot_contract = web3_provider.eth.contract(abi=pot_abi, decode_tuples=True)
        self._pot_contract = retry_with_backoff(pot_contract, address=pot_address)

        self._initted = True

    def sync(self, web3_provider: Web3) -> None:
        if not self._initted:
            self.pool_init(web3_provider)

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self) -> int:
        RAY = 1e27
        dsr = retry_with_backoff(self._pot_contract.functions.dsr().call)
        seconds_per_year = 31536000
        x = (dsr / RAY) ** seconds_per_year
        return int(math.floor((x - 1) * 1e18))


class MorphoVault(ChainBasedPoolModel):
    """Model for Morpho Vaults"""

    pool_type: POOL_TYPES = Field(POOL_TYPES.MORPHO, const=True, description="type of pool")

    _vault_contract: Contract = PrivateAttr()
    _morpho_contract: Contract = PrivateAttr()
    _irm_abi: str = PrivateAttr()
    _decimals: int = PrivateAttr()
    _DECIMALS_OFFSET: int = PrivateAttr()
    # TODO: update unit tests to check these :^)
    _irm_contracts: dict = PrivateAttr(default={})
    _total_supplied_assets: int = PrivateAttr()
    _user_deposits: int = PrivateAttr()
    _curr_borrows: int = PrivateAttr()
    _asset_decimals: int = PrivateAttr()
    _underlying_asset_contract: Contract = PrivateAttr()
    _user_asset_balance: int = PrivateAttr()
    _share_price: int = PrivateAttr()

    _VIRTUAL_SHARES: ClassVar[int] = 1e6
    _VIRTUAL_ASSETS: ClassVar[int] = 1

    def __hash__(self) -> int:
        return hash(self._vault_contract.address)

    def __eq__(self, other) -> bool:
        if not isinstance(other, MorphoVault):
            return NotImplemented
        # Compare the attributes for equality
        return self._vault_contract.address == other._vault_contract.address  # type: ignore[]

    def pool_init(self, web3_provider: Web3) -> None:
        vault_abi_file_path = Path(__file__).parent / "abi/MetaMorpho.json"
        vault_abi_file = vault_abi_file_path.open()
        vault_abi = json.load(vault_abi_file)
        vault_abi_file.close()

        vault_contract = web3_provider.eth.contract(abi=vault_abi, decode_tuples=True)
        self._vault_contract = retry_with_backoff(vault_contract, address=self.contract_address)

        morpho_abi_file_path = Path(__file__).parent / "abi/Morpho.json"
        morpho_abi_file = morpho_abi_file_path.open()
        morpho_abi = json.load(morpho_abi_file)
        morpho_abi_file.close()

        morpho_address = retry_with_backoff(self._vault_contract.functions.MORPHO().call)

        morpho_contract = web3_provider.eth.contract(abi=morpho_abi, decode_tuples=True)
        self._morpho_contract = retry_with_backoff(morpho_contract, address=morpho_address)

        self._decimals = retry_with_backoff(self._vault_contract.functions.decimals().call)
        self._DECIMALS_OFFSET = retry_with_backoff(self._vault_contract.functions.DECIMALS_OFFSET().call)
        self._asset_decimals = self._decimals - self._DECIMALS_OFFSET

        irm_abi_file_path = Path(__file__).parent / "abi/AdaptiveCurveIrm.json"
        irm_abi_file = irm_abi_file_path.open()
        self._irm_abi = json.load(irm_abi_file)
        irm_abi_file.close()

        underlying_asset_address = retry_with_backoff(self._vault_contract.functions.asset().call)

        erc20_abi_file_path = Path(__file__).parent / "abi/IERC20.json"
        erc20_abi_file = erc20_abi_file_path.open()
        erc20_abi = json.load(erc20_abi_file)
        erc20_abi_file.close()

        underlying_asset_contract = web3_provider.eth.contract(abi=erc20_abi, decode_tuples=True)
        self._underlying_asset_contract = retry_with_backoff(
            underlying_asset_contract,
            address=underlying_asset_address,
        )

        self._initted = True

    def sync(self, web3_provider: Web3) -> None:
        if not self._initted:
            self.pool_init(web3_provider)

        supply_queue_length = retry_with_backoff(self._vault_contract.functions.supplyQueueLength().call)
        market_ids = [
            retry_with_backoff(self._vault_contract.functions.supplyQueue(idx).call) for idx in range(supply_queue_length)
        ]

        total_borrows = 0
        # get irm contracts and borrows
        for market_id in market_ids:
            # calculate current supply apy
            # TODO: can we make this more efficient by making this not be called twice?
            market = retry_with_backoff(self._morpho_contract.functions.market(market_id).call)
            market_params = retry_with_backoff(self._morpho_contract.functions.idToMarketParams(market_id).call)
            irm_address = market_params.irm
            irm_contract_raw = web3_provider.eth.contract(abi=self._irm_abi, decode_tuples=True)
            irm_contract = retry_with_backoff(irm_contract_raw, address=irm_address)
            self._irm_contracts[market_id] = irm_contract

            total_borrows += market.totalBorrowAssets

        self._total_supplied_assets = retry_with_backoff(self._vault_contract.functions.totalAssets().call)
        curr_user_shares = retry_with_backoff(self._vault_contract.functions.balanceOf(self.user_address).call)
        self._user_deposits = retry_with_backoff(self._vault_contract.functions.convertToAssets(curr_user_shares).call)
        self._user_asset_balance = retry_with_backoff(
            self._underlying_asset_contract.functions.balanceOf(Web3.to_checksum_address(self.user_address)).call
        )
        self._curr_borrows = total_borrows

        self._share_price = retry_with_backoff(self._vault_contract.functions.convertToAssets(int(1e18)).call)

    @classmethod
    def assets_to_shares_down(cls, assets: int, total_assets: int, total_shares: int) -> int:
        return (assets * (total_shares + cls._VIRTUAL_SHARES)) // (total_assets + cls._VIRTUAL_ASSETS)

    @classmethod
    def shares_to_assets_down(cls, shares: int, total_assets: int, total_shares: int) -> int:
        return (shares * (total_assets + cls._VIRTUAL_ASSETS)) // (total_shares + cls._VIRTUAL_SHARES)

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self, amount: int) -> int:
        supply_queue_length = retry_with_backoff(self._vault_contract.functions.supplyQueueLength().call)
        market_ids = [
            retry_with_backoff(self._vault_contract.functions.supplyQueue(idx).call) for idx in range(supply_queue_length)
        ]

        total_asset_delta = amount - self._user_deposits

        # apys in each market
        current_supply_apys = []
        # current assets allocated to each market
        current_assets = []

        # calculate the supply apys for each market
        for market_id in market_ids:
            # calculate current supply apy
            market = retry_with_backoff(self._morpho_contract.functions.market(market_id).call)
            market_params = retry_with_backoff(self._morpho_contract.functions.idToMarketParams(market_id).call)
            irm_contract = self._irm_contracts[market_id]
            irm_address = irm_contract.address

            if irm_address == ADDRESS_ZERO:
                current_supply_apys.append(0)
                current_assets.append(0)
                continue

            borrow_rate = retry_with_backoff(irm_contract.functions.borrowRateView(market_params, market).call)

            seconds_per_year = 31536000
            utilization = market.totalBorrowAssets / market.totalSupplyAssets

            borrow_apy_raw = math.exp(borrow_rate * seconds_per_year / 1e18) - 1
            supply_apy_raw = borrow_apy_raw * utilization * (1 - (market.fee / 1e18))

            current_supply_apys.append(int(supply_apy_raw * 1e18))

            # calculate current assets allocated to the market
            position = retry_with_backoff(self._morpho_contract.functions.position(market_id, self.contract_address).call)
            allocated_assets = self.shares_to_assets_down(
                position.supplyShares, market.totalSupplyAssets, market.totalSupplyShares
            )
            current_assets.append(allocated_assets * int(10**self._asset_decimals))

        curr_agg_apy = sum([current_assets[i] * current_supply_apys[i] for i in range(supply_queue_length)]) / sum(
            current_assets
        )

        return int(curr_agg_apy * self._total_supplied_assets / (self._total_supplied_assets + total_asset_delta))


class YearnV3Vault(ChainBasedPoolModel):
    pool_type: POOL_TYPES = Field(POOL_TYPES.YEARN_V3, const=True, description="type of pool")

    _vault_contract: Contract = PrivateAttr()
    _apr_oracle: Contract = PrivateAttr()
    _max_withdraw: int = PrivateAttr()
    _user_deposits: int = PrivateAttr()

    def pool_init(self, web3_provider: Web3) -> None:
        vault_abi_file_path = Path(__file__).parent / "abi/Yearn_V3_Vault.json"
        vault_abi_file = vault_abi_file_path.open()
        vault_abi = json.load(vault_abi_file)
        vault_abi_file.close()

        vault_contract = web3_provider.eth.contract(abi=vault_abi, decode_tuples=True)
        self._vault_contract = retry_with_backoff(vault_contract, address=self.contract_address)

        apr_oracle_abi_file_path = Path(__file__).parent / "abi/AprOracle.json"
        apr_oracle_abi_file = apr_oracle_abi_file_path.open()
        apr_oracle_abi = json.load(apr_oracle_abi_file)
        apr_oracle_abi_file.close()

        apr_oracle = web3_provider.eth.contract(abi=apr_oracle_abi, decode_tuples=True)
        self._apr_oracle = retry_with_backoff(apr_oracle, address=APR_ORACLE)

    def sync(self, web3_provider: Web3) -> None:
        if not self._initted:
            self.pool_init(web3_provider)

        self._max_withdraw = retry_with_backoff(self._vault_contract.functions.maxWithdraw(self.user_address).call)
        user_shares = retry_with_backoff(self._vault_contract.functions.balanceOf(self.user_address).call)
        self._user_deposits = retry_with_backoff(self._vault_contract.functions.convertToAssets(user_shares).call)

    def supply_rate(self, amount: int) -> int:
        delta = amount - self._user_deposits
        return retry_with_backoff(self._apr_oracle.functions.getExpectedApr(self.contract_address, delta).call)


def generate_eth_public_key(rng_gen: np.random.RandomState) -> str:
    private_key_bytes = rng_gen.bytes(32)  # type: ignore[]
    account = Account.from_key(private_key_bytes)
    return account.address


def generate_challenge_data(
    web3_provider: Web3,
    rng_gen: np.random.RandomState = np.random.RandomState(),  # noqa: B008
) -> dict[str, dict[str, ChainBasedPoolModel] | int]:  # generate pools
    selected_entry = POOL_REGISTRY[rng_gen.choice(list(POOL_REGISTRY.keys()))]
    bt.logging.debug(f"Selected pool registry entry: {selected_entry}")

    return assets_pools_for_challenge_data(selected_entry, web3_provider)


def assets_pools_for_challenge_data(
    selected_entry, web3_provider: Web3
) -> dict[str, dict[str, ChainBasedPoolModel] | int]:  # generate pools
    challenge_data = {}

    selected_assets_and_pools = selected_entry["assets_and_pools"]
    selected_pools = selected_assets_and_pools["pools"]
    global_user_address = selected_entry.get("user_address", None)

    pool_list = []

    for pool_dict in selected_pools.values():
        user_address = pool_dict.get("user_address", None)
        pool = PoolFactory.create_pool(
            pool_type=POOL_TYPES._member_map_[pool_dict["pool_type"]],
            user_address=global_user_address if user_address is None else user_address,
            contract_address=pool_dict["contract_address"],
        )
        pool_list.append(pool)

    pools = {str(pool.contract_address): pool for pool in pool_list}

    # we assume that the user address is the same across pools (valid)
    # and also that the asset contracts are the same across said pools
    total_assets = selected_entry.get("total_assets", None)

    if total_assets is None:
        total_assets = 0
        first_pool = pool_list[0]
        first_pool.sync(web3_provider)
        match first_pool.pool_type:
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.AAVE_DEFAULT, POOL_TYPES.AAVE_TARGET, POOL_TYPES.MORPHO):
                total_assets = first_pool._user_asset_balance
            case _:
                pass

        for pool in pools.values():
            pool.sync(web3_provider)
            total_asset = 0
            match pool.pool_type:
                case POOL_TYPES.STURDY_SILO:
                    total_asset += pool._user_deposits
                case T if T in (POOL_TYPES.AAVE_DEFAULT, POOL_TYPES.AAVE_TARGET):
                    total_asset += pool._user_deposits
                case POOL_TYPES.MORPHO:
                    total_asset += pool._user_deposits
                case _:
                    pass

            total_assets += total_asset

    challenge_data["assets_and_pools"] = {}
    challenge_data["assets_and_pools"]["pools"] = pools
    challenge_data["assets_and_pools"]["total_assets"] = total_assets
    if global_user_address is not None:
        challenge_data["user_address"] = global_user_address

    return challenge_data
