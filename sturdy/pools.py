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
from typing import Any, Literal

import bittensor as bt
import numpy as np
from eth_account import Account
from pydantic import BaseModel, Field, PrivateAttr, root_validator, validator
from web3 import Web3
from web3.constants import ADDRESS_ZERO
from web3.contract.contract import Contract
from web3.types import BlockData

from sturdy.constants import *
from sturdy.utils.ethmath import wei_div, wei_mul
from sturdy.utils.misc import (
    format_num_prec,
    getReserveFactor,
    randrange_float,
    rayMul,
    retry_with_backoff,
    ttl_cache,
)


class POOL_TYPES(IntEnum):
    SYNTHETIC = 0
    STURDY_SILO = 1
    AAVE = 2
    DAI_SAVINGS = 3
    COMPOUND_V3 = 4


def check_allocations(
    assets_and_pools: dict,
    allocations: dict[str, int],
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

    # Ensure total allocated does not exceed the total assets
    if total_allocated > to_allocate:
        return False

    pools = assets_and_pools["pools"]
    # check if allocations are above the borrow amounts
    for pool_uid, pool in pools.items():
        allocation = allocations.get(pool_uid, 0)
        borrow_amount = 0
        match pool.pool_type:
            case POOL_TYPES.STURDY_SILO:
                borrow_amount = pool._totalBorrow.amount
            case POOL_TYPES.AAVE:
                # borrow amount for aave pools is total_stable_debt + total_variable_debt
                borrow_amount = pool._nextTotalStableDebt + pool._totalVariableDebt
            case POOL_TYPES.COMPOUND_V3:
                borrow_amount = pool._total_borrow
            case POOL_TYPES.DAI_SAVINGS:
                pass  # TODO: is there a more appropriate way to go about this?
            case _:  # we assume it is a synthetic pool
                borrow_amount = pool.borrow_amount

        if allocation < borrow_amount:
            return False

    return True


class BasePoolModel(BaseModel):
    """This model will primarily be used for synthetic requests"""

    class Config:
        use_enum_values = True  # This will use the enum's value instead of the enum itself
        smart_union = True

    pool_model_disc: Literal["SYNTHETIC"] = Field(default="SYNTHETIC", description="pool type discriminator")
    contract_address: str = Field(..., description='the "contract address" of the pool - used here as a uid')
    pool_type: POOL_TYPES | int | str = Field(default=POOL_TYPES.SYNTHETIC, const=True, description="type of pool")
    base_rate: int = Field(..., description="base interest rate")
    base_slope: int = Field(..., description="base interest rate slope")
    kink_slope: int = Field(..., description="kink slope")
    optimal_util_rate: int = Field(..., description="optimal utilisation rate")
    borrow_amount: int = Field(..., description="borrow amount in wei")
    reserve_size: int = Field(..., description="pool reserve size in wei")

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
        contract_address: (str),
        base_rate: (int),
        base_slope: (int),
        kink_slope: (int),
        optimal_util_rate: (int),
        borrow_amount: (int),
        reserve_size: (int),
    """

    @property
    def util_rate(self) -> int:
        return wei_div(self.borrow_amount, self.reserve_size)

    @property
    def borrow_rate(self) -> int:
        util_rate = self.util_rate
        return (
            self.base_rate + wei_mul(wei_div(util_rate, self.optimal_util_rate), self.base_slope)
            if util_rate < self.optimal_util_rate
            else self.base_rate
            + self.base_slope
            + wei_mul(
                wei_div(
                    (util_rate - self.optimal_util_rate),
                    int(1e18 - self.optimal_util_rate),
                ),
                self.kink_slope,
            )
        )

    @property
    def supply_rate(self) -> int:
        return wei_mul(self.util_rate, self.borrow_rate)


class ChainBasedPoolModel(BaseModel):
    """This serves as the base model of pools which need to pull data from on-chain

    Args:
        contract_address: (str),
    """

    class Config:
        use_enum_values = True  # This will use the enum's value instead of the enum itself
        smart_union = True

    pool_model_disc: Literal["CHAIN"] = Field(default="CHAIN", description="pool type discriminator")
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
    def create_pool(pool_type: POOL_TYPES, **kwargs: Any) -> ChainBasedPoolModel | BasePoolModel:
        match pool_type:
            case POOL_TYPES.SYNTHETIC:
                return BasePool(**kwargs)
            case POOL_TYPES.AAVE:
                return AaveV3DefaultInterestRatePool(**kwargs)
            case POOL_TYPES.STURDY_SILO:
                return VariableInterestSturdySiloStrategy(**kwargs)
            case POOL_TYPES.DAI_SAVINGS:
                return DaiSavingsRate(**kwargs)
            case POOL_TYPES.COMPOUND_V3:
                return CompoundV3Pool(**kwargs)
            case _:
                raise ValueError(f"Unknown pool type: {pool_type}")


class AaveV3DefaultInterestRatePool(ChainBasedPoolModel):
    """This class defines the default pool type for Aave"""

    pool_type: POOL_TYPES = Field(default=POOL_TYPES.AAVE, const=True, description="type of pool")

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
    _decimals: int = PrivateAttr()

    class Config:
        arbitrary_types_allowed = True

    def __hash__(self) -> int:
        return hash((self._atoken_contract.address, self._underlying_asset_address))

    def __eq__(self, other) -> bool:
        if not isinstance(other, AaveV3DefaultInterestRatePool):
            return NotImplemented
        # Compare the attributes for equality
        return (self._atoken_contract.address, self._underlying_asset_address) == (
            other._atoken_contract.address,
            other._underlying_asset_address,
        )

    def pool_init(self, web3_provider: Web3) -> None:
        try:
            assert web3_provider.is_connected()  # noqa: S101
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

        except Exception as err:
            bt.logging.error("Failed to sync to chain!")
            bt.logging.error(err)  # type: ignore[]

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self, user_addr: str, amount: int) -> int:
        """Returns supply rate given new deposit amount"""
        try:
            already_deposited = int(
                retry_with_backoff(self._atoken_contract.functions.balanceOf(Web3.to_checksum_address(user_addr)).call)
                * 10**self._decimals
                // 1e18,
            )

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
    _curr_deposit_amount: int = PrivateAttr()
    _util_prec: int = PrivateAttr()
    _fee_prec: int = PrivateAttr()
    _totalAssets: Any = PrivateAttr()
    _totalBorrow: Any = PrivateAttr()
    _current_rate_info = PrivateAttr()
    _rate_prec: int = PrivateAttr()
    _block: BlockData = PrivateAttr()

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

    def pool_init(self, user_addr: str, web3_provider: Web3) -> None:  # noqa: ARG002
        try:
            assert web3_provider.is_connected()  # noqa: S101
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

            self._initted = True

        except Exception as e:
            bt.logging.error(e)  # type: ignore[]

    def sync(self, user_addr: str, web3_provider: Web3) -> None:
        """Syncs with chain"""
        if not self._initted:
            self.pool_init(user_addr, web3_provider)

        user_shares = retry_with_backoff(self._pair_contract.functions.balanceOf(self.contract_address).call)
        self._curr_deposit_amount = retry_with_backoff(self._pair_contract.functions.convertToAssets(user_shares).call)

        constants = retry_with_backoff(self._pair_contract.functions.getConstants().call)
        self._util_prec = constants[2]
        self._fee_prec = constants[3]
        self._totalAssets: Any = retry_with_backoff(self._pair_contract.functions.totalAssets().call)
        self._totalBorrow: Any = retry_with_backoff(self._pair_contract.functions.totalBorrow().call)

        self._block = web3_provider.eth.get_block("latest")

        self._current_rate_info = retry_with_backoff(self._pair_contract.functions.currentRateInfo().call)

        self._rate_prec = retry_with_backoff(self._rate_model_contract.functions.RATE_PREC().call)

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self, amount: int) -> int:
        delta = amount - self._curr_deposit_amount

        """Returns supply rate given new deposit amount"""
        util_rate = int((self._util_prec * self._totalBorrow.amount) // (self._totalAssets + delta))

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

    def supply_rate(self, amount: int) -> int:
        # get pool supply rate (base token)
        current_supply = retry_with_backoff(self._ctoken_contract.functions.totalSupply().call)
        already_in_pool = retry_with_backoff(self._ctoken_contract.functions.balanceOf(self.user_address).call)

        delta = amount - already_in_pool
        new_supply = current_supply + delta
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


def generate_eth_public_key(rng_gen: np.random.RandomState) -> str:
    private_key_bytes = rng_gen.bytes(32)  # type: ignore[]
    account = Account.from_key(private_key_bytes)
    return account.address


def generate_assets_and_pools(rng_gen: np.random.RandomState) -> dict[str, dict[str, BasePoolModel] | int]:  # generate pools
    assets_and_pools = {}

    pools_list = [
        BasePool(
            contract_address=generate_eth_public_key(rng_gen=rng_gen),
            pool_type=POOL_TYPES.SYNTHETIC,
            base_rate=int(randrange_float(MIN_BASE_RATE, MAX_BASE_RATE, BASE_RATE_STEP, rng_gen=rng_gen)),
            base_slope=int(randrange_float(MIN_SLOPE, MAX_SLOPE, SLOPE_STEP, rng_gen=rng_gen)),
            kink_slope=int(
                randrange_float(MIN_KINK_SLOPE, MAX_KINK_SLOPE, SLOPE_STEP, rng_gen=rng_gen),
            ),  # kink rate - kicks in after pool hits optimal util rate
            optimal_util_rate=int(
                randrange_float(
                    MIN_OPTIMAL_RATE,
                    MAX_OPTIMAL_RATE,
                    OPTIMAL_UTIL_STEP,
                    rng_gen=rng_gen,
                ),
            ),  # optimal util rate - after which the kink slope kicks in
            borrow_amount=int(
                format_num_prec(
                    wei_mul(
                        POOL_RESERVE_SIZE,
                        int(
                            randrange_float(
                                MIN_UTIL_RATE,
                                MAX_UTIL_RATE,
                                UTIL_RATE_STEP,
                                rng_gen=rng_gen,
                            ),
                        ),
                    ),
                ),
            ),  # initial borrowed amount from pool
            reserve_size=int(POOL_RESERVE_SIZE),
        )
        for _ in range(NUM_POOLS)
    ]

    pools = {str(pool.contract_address): pool for pool in pools_list}

    minimums = [pool.borrow_amount for pool in pools_list]
    min_total = sum(minimums)
    assets_and_pools["total_assets"] = int(min_total) + int(math.floor(
        randrange_float(MIN_TOTAL_ASSETS_OFFSET, MAX_TOTAL_ASSETS_OFFSET, TOTAL_ASSETS_OFFSET_STEP, rng_gen=rng_gen),
    ))
    assets_and_pools["pools"] = pools

    return assets_and_pools


# generate intial allocations for pools
def generate_initial_allocations_for_pools(assets_and_pools: dict) -> dict:
    pools: dict[str, BasePool] = assets_and_pools["pools"]
    return {str(pool.contract_address): pool.borrow_amount for pool in pools.values()}
