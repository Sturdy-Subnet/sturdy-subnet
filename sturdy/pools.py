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
from typing import Dict, Literal, Union
from enum import Enum

import json
from pydantic import BaseModel, Field, PrivateAttr, root_validator
from web3 import Web3
import web3
import web3.constants
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


class POOL_TYPES(str, Enum):
    STURDY_SILO = "STURDY_SILO"
    AAVE = "AAVE"
    SYNTHETIC = "SYNTHETIC"
    DAI_SAVINGS = "DAI_SAVINGS"
    COMPOUND_V3 = "COMPOUND_V3"


class BasePoolModel(BaseModel):
    """This model will primarily be used for synthetic requests"""

    pool_model_disc: Literal["SYNTHETIC"] = Field(
        default="SYNTHETIC", description="pool type discriminator"
    )
    pool_id: str = Field(..., description="uid of pool")
    pool_type: POOL_TYPES = Field(
        default=POOL_TYPES.SYNTHETIC, const=True, description="type of pool"
    )
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

    pool_model_disc: Literal["CHAIN"] = Field(
        default="CHAIN", description="pool type discriminator"
    )
    pool_id: str = Field(..., description="uid of pool")
    pool_type: POOL_TYPES = Field(..., description="type of pool")
    user_address: str = Field(
        default=web3.constants.ADDRESS_ZERO,
        description="address of the 'user' - used for various on-chain calls",
    )
    contract_address: str = Field(
        default=web3.constants.ADDRESS_ZERO, description="address of contract to call"
    )

    _initted: bool = PrivateAttr(False)

    @root_validator
    def check_params(cls, values):
        if len(values.get("pool_id")) <= 0:
            raise ValueError("pool id is empty")
        if not Web3.is_address(values.get("contract_address")):
            raise ValueError("pool address is invalid!")
        if not Web3.is_address(values.get("user_address")):
            raise ValueError("user address is invalid!")

        return values

    def pool_init(self, **args):
        raise NotImplementedError("pool_init() has not been implemented!")

    def sync(self, **args):
        raise NotImplementedError("sync() has not been implemented!")

    def supply_rate(self, **args):
        raise NotImplementedError("supply_rate() has not been implemented!")


class PoolFactory:
    @staticmethod
    def create_pool(
        pool_type: POOL_TYPES, **kwargs
    ) -> Union[ChainBasedPoolModel, BasePoolModel]:
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

    pool_type: POOL_TYPES = Field(
        default=POOL_TYPES.AAVE, const=True, description="type of pool"
    )

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
            atoken_abi_file_path = Path(__file__).parent / "abi/AToken.json"
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

            pool_abi_file_path = Path(__file__).parent / "abi/Pool.json"
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

            erc20_abi_file_path = Path(__file__).parent / "abi/IERC20.json"
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
            pool_abi_file_path = Path(__file__).parent / "abi/Pool.json"
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
                Path(__file__).parent / "abi/IReserveInterestRateStrategy.json"
            )
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
                Path(__file__).parent / "abi/IVariableDebtToken.json"
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
    def supply_rate(self, user_addr: str, amount: int) -> int:
        """Returns supply rate given new deposit amount"""
        try:
            already_deposited = int(
                retry_with_backoff(
                    self._atoken_contract.functions.balanceOf(
                        Web3.to_checksum_address(user_addr)
                    ).call
                )
                * 10**self._decimals
                // 1e18
            )

            delta = amount - already_deposited
            to_deposit = delta if delta > 0 else 0
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
                    )
                ).call
            )

            # return liquidity_rate / 1e27
            return Web3.to_wei(nextLiquidityRate / 1e27, "ether")

        except Exception as e:
            bt.logging.error("Failed to retrieve supply apy!")
            bt.logging.error(e)

        return 0


class VariableInterestSturdySiloStrategy(ChainBasedPoolModel):

    pool_type: POOL_TYPES = Field(
        POOL_TYPES.STURDY_SILO, const=True, description="type of pool"
    )

    _silo_strategy_contract: Contract = PrivateAttr()
    _pair_contract: Contract = PrivateAttr()
    _rate_model_contract: Contract = PrivateAttr()
    _curr_deposit_amount: int = PrivateAttr()
    _util_prec: int = PrivateAttr()
    _fee_prec: int = PrivateAttr()
    _totalAsset: int = PrivateAttr()
    _totalBorrow: int = PrivateAttr()
    _current_rate_info = PrivateAttr()
    _rate_prec: int = PrivateAttr()
    _block: web3.types.BlockData = PrivateAttr()

    def __hash__(self):
        return hash((self._silo_strategy_contract.address, self._pair_contract))

    def __eq__(self, other):
        if not isinstance(other, VariableInterestSturdySiloStrategy):
            return NotImplemented
        # Compare the attributes for equality
        return (self._silo_strategy_contract.address, self._pair_contract) == (
            other._silo_strategy_contract.address,
            other._pair_contract.address,
        )

    def pool_init(self, user_addr: str, web3_provider: Web3):
        try:
            assert web3_provider.is_connected()
        except Exception as err:
            bt.logging.error("Failed to connect to Web3 instance!")
            bt.logging.error(err)

        try:
            silo_strategy_abi_file_path = (
                Path(__file__).parent / "abi/SturdySiloStrategy.json"
            )
            silo_strategy_abi_file = silo_strategy_abi_file_path.open()
            silo_strategy_abi = json.load(silo_strategy_abi_file)
            silo_strategy_abi_file.close()

            silo_strategy_contract = web3_provider.eth.contract(
                abi=silo_strategy_abi, decode_tuples=True
            )
            self._silo_strategy_contract = retry_with_backoff(
                silo_strategy_contract, address=self.contract_address
            )

            pair_abi_file_path = Path(__file__).parent / "abi/SturdyPair.json"
            pair_abi_file = pair_abi_file_path.open()
            pair_abi = json.load(pair_abi_file)
            pair_abi_file.close()

            pair_contract_address = retry_with_backoff(
                self._silo_strategy_contract.functions.pair().call
            )
            pair_contract = web3_provider.eth.contract(abi=pair_abi, decode_tuples=True)
            self._pair_contract = retry_with_backoff(
                pair_contract, address=pair_contract_address
            )

            rate_model_abi_file_path = Path(__file__).parent / "abi/VariableInterestRate.json"
            rate_model_abi_file = rate_model_abi_file_path.open()
            rate_model_abi = json.load(rate_model_abi_file)
            rate_model_abi_file.close()

            rate_model_contract_address = retry_with_backoff(
                self._pair_contract.functions.rateContract().call
            )
            rate_model_contract = web3_provider.eth.contract(
                abi=rate_model_abi, decode_tuples=True
            )
            self._rate_model_contract = retry_with_backoff(
                rate_model_contract, address=rate_model_contract_address
            )

            self._initted = True

        except Exception as e:
            bt.logging.error(e)

    def sync(self, user_addr: str, web3_provider: Web3):
        """Syncs with chain"""
        if not self._initted:
            self.pool_init(user_addr, web3_provider)

        user_shares = retry_with_backoff(
            self._pair_contract.functions.balanceOf(user_addr).call
        )
        self._curr_deposit_amount = retry_with_backoff(
            self._pair_contract.functions.convertToAssets(user_shares).call
        )

        constants = retry_with_backoff(
            self._pair_contract.functions.getConstants().call
        )
        self._util_prec = constants[2]
        self._fee_prec = constants[3]
        self._totalAsset = retry_with_backoff(
            self._pair_contract.functions.totalAsset().call
        )
        self._totalBorrow = retry_with_backoff(
            self._pair_contract.functions.totalBorrow().call
        )

        self._block = web3_provider.eth.get_block("latest")

        self._current_rate_info = retry_with_backoff(
            self._pair_contract.functions.currentRateInfo().call
        )

        self._rate_prec = retry_with_backoff(
            self._rate_model_contract.functions.RATE_PREC().call
        )

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self, amount: int) -> int:
        delta = amount - self._curr_deposit_amount
        """Returns supply rate given new deposit amount"""
        util_rate = (self._util_prec * self._totalBorrow.amount) // (
            self._totalAsset.amount + delta
        )

        last_update_timestamp = self._current_rate_info.lastTimestamp
        current_timestamp = self._block["timestamp"]
        delta_time = current_timestamp - last_update_timestamp

        protocol_fee = self._current_rate_info.feeToProtocolRate
        (new_rate_per_sec, _) = retry_with_backoff(
            self._rate_model_contract.functions.getNewRate(
                delta_time, util_rate, self._current_rate_info.fullUtilizationRate
            ).call
        )

        supply_apy = int(
            new_rate_per_sec
            * 31536000
            * 1e18
            * util_rate
            // self._rate_prec
            // self._util_prec
            * (1 - (protocol_fee / self._fee_prec))
        )  # (rate_per_sec_pct * seconds_in_year * util_rate_pct) * 1e18

        return supply_apy


class CompoundV3Pool(ChainBasedPoolModel):
    """Model for Compound V3 Pools"""

    pool_type: POOL_TYPES = Field(
        POOL_TYPES.COMPOUND_V3, const=True, description="type of pool"
    )

    _ctoken_contract: Contract = PrivateAttr()
    _base_oracle_contract: Contract = PrivateAttr()
    _reward_oracle_contract: Contract = PrivateAttr()
    _base_token_contract: Contract = PrivateAttr()
    _reward_token_contract: Contract = PrivateAttr()
    _base_token_price: float = PrivateAttr()
    _reward_token_price: float = PrivateAttr()

    _CompoundTokenMap: Dict = {
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # WETH -> ETH
    }

    def pool_init(self, web3_provider: Web3):
        comet_abi_file_path = Path(__file__).parent / "../abi/Comet.json"
        comet_abi_file = comet_abi_file_path.open()
        comet_abi = json.load(comet_abi_file)
        comet_abi_file.close()

        # ctoken contract
        ctoken_contract = web3_provider.eth.contract(abi=comet_abi, decode_tuples=True)
        self._ctoken_contract = retry_with_backoff(
            ctoken_contract, address=self.contract_address
        )

        oracle_abi_file_path = Path(__file__).parent / "../abi/EACAggregatorProxy.json"
        oracle_abi_file = oracle_abi_file_path.open()
        oracle_abi = json.load(oracle_abi_file)
        oracle_abi_file.close()

        feed_registry_abi_file_path = Path(__file__).parent / "../abi/FeedRegistry.json"
        feed_registry_abi_file = feed_registry_abi_file_path.open()
        feed_registry_abi = json.load(feed_registry_abi_file)
        feed_registry_abi_file.close()

        chainlink_registry_address = "0x47Fb2585D2C56Fe188D0E6ec628a38b74fCeeeDf"  # chainlink registry address on eth mainnet
        usd_address = "0x0000000000000000000000000000000000000348"  # follows: https://en.wikipedia.org/wiki/ISO_4217
        chainlink_registry = web3_provider.eth.contract(
            abi=feed_registry_abi, decode_tuples=True
        )

        chainlink_registry_contract = retry_with_backoff(
            chainlink_registry, address=chainlink_registry_address
        )

        base_token_address = retry_with_backoff(
            self._ctoken_contract.functions.baseToken().call
        )
        asset_address = self._CompoundTokenMap.get(
            base_token_address, base_token_address
        )

        base_oracle_address = retry_with_backoff(
            chainlink_registry_contract.functions.getFeed(
                asset_address, usd_address
            ).call
        )
        base_oracle_contract = web3_provider.eth.contract(
            abi=oracle_abi, decode_tuples=True
        )
        self._base_oracle_contract = retry_with_backoff(
            base_oracle_contract, address=base_oracle_address
        )

        reward_oracle_address = "0xdbd020CAeF83eFd542f4De03e3cF0C28A4428bd5"  # TODO: COMP price feed address
        reward_oracle_contract = web3_provider.eth.contract(
            abi=oracle_abi, decode_tuples=True
        )
        self._reward_oracle_contract = retry_with_backoff(
            reward_oracle_contract, address=reward_oracle_address
        )

        self._initted = True

    def sync(self, web3_provider: Web3):
        if not self._initted:
            self.pool_init(web3_provider)

        # get token prices - in wei
        base_decimals = retry_with_backoff(
            self._base_oracle_contract.functions.decimals().call
        )
        reward_decimals = retry_with_backoff(
            self._reward_oracle_contract.functions.decimals().call
        )

        self._base_token_price = (
            retry_with_backoff(self._base_oracle_contract.functions.latestAnswer().call)
            / 10**base_decimals
        )
        self._reward_token_price = (
            retry_with_backoff(
                self._reward_oracle_contract.functions.latestAnswer().call
            )
            / 10**reward_decimals
        )

    def supply_rate(self, amount: int) -> int:
        # get pool supply rate (base token)
        current_supply = retry_with_backoff(
            self._ctoken_contract.functions.totalSupply().call
        )
        already_in_pool = retry_with_backoff(
            self._ctoken_contract.functions.balanceOf(self.user_address).call
        )

        delta = amount - already_in_pool
        new_supply = current_supply + delta
        current_borrows = retry_with_backoff(
            self._ctoken_contract.functions.totalBorrow().call
        )

        utilization = wei_div(current_borrows, new_supply)
        seconds_per_year = 31536000
        seconds_per_day = 86400

        pool_rate = (
            retry_with_backoff(
                self._ctoken_contract.functions.getSupplyRate(utilization).call
            )
            * seconds_per_year
        )

        base_scale = retry_with_backoff(
            self._ctoken_contract.functions.baseScale().call
        )
        conv_total_supply = new_supply / base_scale

        base_index_scale = retry_with_backoff(
            self._ctoken_contract.functions.baseIndexScale().call
        )
        base_tracking_supply_speed = retry_with_backoff(
            self._ctoken_contract.functions.baseTrackingSupplySpeed().call
        )
        reward_per_day = base_tracking_supply_speed / base_index_scale * seconds_per_day
        comp_rate = 0

        if conv_total_supply * self._base_token_price > 0:
            comp_rate = Web3.to_wei(
                self._reward_token_price
                * reward_per_day
                / (conv_total_supply * self._base_token_price)
                * 365,
                "ether",
            )

        total_rate = int(pool_rate + comp_rate)
        return total_rate


class DaiSavingsRate(ChainBasedPoolModel):
    """Model for DAI Savings Rate"""

    pool_type: POOL_TYPES = Field(
        POOL_TYPES.DAI_SAVINGS, const=True, description="type of pool"
    )

    _sdai_contract: Contract = PrivateAttr()
    _pot_contract: Contract = PrivateAttr()

    def __hash__(self):
        return hash(self._sdai_contract.address)

    def __eq__(self, other):
        if not isinstance(other, VariableInterestSturdySiloStrategy):
            return NotImplemented
        # Compare the attributes for equality
        return self._sdai_contract.address == other._sdai_contract.address

    def pool_init(self, web3_provider: Web3):
        sdai_abi_file_path = Path(__file__).parent / "../abi/SavingsDai.json"
        sdai_abi_file = sdai_abi_file_path.open()
        sdai_abi = json.load(sdai_abi_file)
        sdai_abi_file.close()

        sdai_contract = web3_provider.eth.contract(abi=sdai_abi, decode_tuples=True)
        self._sdai_contract = retry_with_backoff(
            sdai_contract, address=self.contract_address
        )

        pot_abi_file_path = Path(__file__).parent / "../abi/Pot.json"
        pot_abi_file = pot_abi_file_path.open()
        pot_abi = json.load(pot_abi_file)
        pot_abi_file.close()

        pot_address = retry_with_backoff(self._sdai_contract.functions.pot().call)

        pot_contract = web3_provider.eth.contract(abi=pot_abi, decode_tuples=True)
        self._pot_contract = retry_with_backoff(pot_contract, address=pot_address)

        self._initted = True

    def sync(self, web3_provider: Web3):
        if not self._initted:
            self.pool_init(web3_provider)

    # last 256 unique calls to this will be cached for the next 60 seconds
    @ttl_cache(maxsize=256, ttl=60)
    def supply_rate(self):
        RAY = 1e27
        dsr = retry_with_backoff(self._pot_contract.functions.dsr().call)
        seconds_per_year = 31536000
        x = (dsr / RAY) ** seconds_per_year
        apy = int(math.floor((x - 1) * 1e18))

        return apy


def generate_assets_and_pools(rng_gen=np.random) -> Dict:  # generate pools
    assets_and_pools = {}

    pools = [
        BasePool(
            pool_id=str(x),
            pool_type=POOL_TYPES.SYNTHETIC,
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
