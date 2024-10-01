# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
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

from enum import IntEnum
from typing import Annotated

import bittensor as bt
from pydantic import BaseModel, Field, root_validator, validator
from typing_extensions import TypedDict
from web3 import Web3
from web3.constants import ADDRESS_ZERO

from sturdy.pools import BasePoolModel, ChainBasedPoolModel


class REQUEST_TYPES(IntEnum):
    ORGANIC = 0
    SYNTHETIC = 1


AllocationsDict = dict[str, int]


class AllocInfo(TypedDict):
    apy: int
    allocations: AllocationsDict | None


PoolModel = Annotated[ChainBasedPoolModel | BasePoolModel, Field(discriminator="pool_model_disc")]


class AllocateAssetsRequest(BaseModel):
    class Config:
        use_enum_values = True
        smart_union = True

    request_type: REQUEST_TYPES | int | str = Field(default=REQUEST_TYPES.ORGANIC, description="type of request")
    assets_and_pools: dict[str, dict[str, PoolModel] | int] = Field(
        ...,
        description="pools for miners to produce allocation amounts for - uid -> pool_info",
    )
    user_address: str = Field(
        default=ADDRESS_ZERO,
        description="address of the 'user' - used for various on-chain calls for organic requests",
    )

    @validator("request_type", pre=True)
    def validator_pool_type(cls, value) -> REQUEST_TYPES:
        if isinstance(value, REQUEST_TYPES):
            return value
        elif isinstance(value, int):  # noqa: RET505
            return REQUEST_TYPES(value)
        elif isinstance(value, str):
            try:
                return REQUEST_TYPES[value]
            except KeyError:
                raise ValueError(f"Invalid enum name: {value}")  # noqa: B904
        raise ValueError(f"Invalid value: {value}")

    @root_validator
    def check_params(cls, values):  # noqa: ANN201
        user_addr = values.get("user_address")
        if not Web3.is_address(user_addr):
            raise ValueError("user address is invalid!")

        return values


class AllocateAssetsResponse(BaseModel):
    class Config:
        use_enum_values = True

    request_uuid: str
    allocations: dict[str, AllocInfo] = Field(
        ...,
        description="allocations produce by miners",
    )


class AllocateAssetsBase(BaseModel):
    """
    This protocol helps in handling the distribution of validator-generated pools from
    the validator to miners, and then gathering miner-generated allocations afterwards.

    Attributes:
    - pools: A list of pools sent by the validator.
    - allocations: A list of pools and their respective allocations, when filled, represents the response from the miner.
    """

    class Config:
        use_enum_values = True
        smart_union = True

    request_type: REQUEST_TYPES | int | str = Field(default=REQUEST_TYPES.ORGANIC, description="type of request")
    assets_and_pools: dict[str, dict[str, PoolModel] | int] = Field(
        ...,
        description="pools for miners to produce allocation amounts for - uid -> pool_info",
    )
    user_address: str = Field(
        default=ADDRESS_ZERO,
        description="address of the 'user' - used for various on-chain calls",
    )

    # Optional request output, filled by recieving axon.
    allocations: AllocationsDict | None = Field(
        None,
        description="allocations produce by miners",
    )

    @validator("request_type", pre=True)
    def validator_pool_type(cls, value):  # noqa: ANN201
        if isinstance(value, REQUEST_TYPES):
            return value
        elif isinstance(value, int):  # noqa: RET505
            return REQUEST_TYPES(value)
        elif isinstance(value, str):
            try:
                return REQUEST_TYPES[value]
            except KeyError:
                raise ValueError(f"Invalid enum name: {value}")  # noqa: B904
        raise ValueError(f"Invalid value: {value}")

    @root_validator
    def check_params(cls, values):  # noqa: ANN201
        user_addr = values.get("user_address")
        if not Web3.is_address(user_addr):
            raise ValueError("user address is invalid!")

        allocs = values.get("allocations")
        if allocs is not None:
            for alloc_dict_key in allocs:
                if not Web3.is_address(alloc_dict_key):
                    raise ValueError("contract address is invalid!")

        return values


class AllocateAssets(bt.Synapse, AllocateAssetsBase):
    def __str__(self) -> str:
        return f"""AllocateAssets(request_type={self.request_type}, assets_and_pools={self.assets_and_pools},
            user_address={self.user_address}, allocations={self.allocations})"""


class GetAllocationResponse(BaseModel):
    request_uid: str
    miner_uid: str
    allocation: str
    created_at: str


class RequestInfoResponse(BaseModel):
    request_uid: str
    assets_and_pools: str
    created_at: str
