# =========================== UTILITIES FOR UNISWAP ===========================

# The minimum tick that can be used on any pool.
MIN_TICK = -887272
# The maximum tick that can be used on any pool.
MAX_TICK = -MIN_TICK

# The sqrt ratio corresponding to the minimum tick that could be used on any pool.
MIN_SQRT_RATIO = 4295128739

# The sqrt ratio corresponding to the maximum tick that could be used on any pool.
MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342


def mul_shift(val: int, mul_by: str) -> int:
    """Multiply and right shift by 128 bits"""
    return (val * int(mul_by, 16)) >> 128


Q32 = 2**32
Q96 = 2**96
MAX_UINT_256 = 2**256 - 1
ZERO = 0
ONE = 1


def get_sqrt_ratio_at_tick(tick: int) -> int:
    """
    Returns the sqrt ratio as a Q64.96 for the given tick.
    The sqrt ratio is computed as sqrt(1.0001)^tick
    """
    assert isinstance(tick, int), "Tick must be an integer"
    assert tick >= MIN_TICK, f"Tick must be greater than or equal to {MIN_TICK}"
    assert tick <= MAX_TICK, f"Tick must be less than or equal to {MAX_TICK}"

    abs_tick = abs(tick)

    ratio = 0xFFFCB933BD6FAD37AA2D162D1A594001 if (abs_tick & 0x1) != 0 else 0x100000000000000000000000000000000

    if (abs_tick & 0x2) != 0:
        ratio = mul_shift(ratio, "0xfff97272373d413259a46990580e213a")
    if (abs_tick & 0x4) != 0:
        ratio = mul_shift(ratio, "0xfff2e50f5f656932ef12357cf3c7fdcc")
    if (abs_tick & 0x8) != 0:
        ratio = mul_shift(ratio, "0xffe5caca7e10e4e61c3624eaa0941cd0")
    if (abs_tick & 0x10) != 0:
        ratio = mul_shift(ratio, "0xffcb9843d60f6159c9db58835c926644")
    if (abs_tick & 0x20) != 0:
        ratio = mul_shift(ratio, "0xff973b41fa98c081472e6896dfb254c0")
    if (abs_tick & 0x40) != 0:
        ratio = mul_shift(ratio, "0xff2ea16466c96a3843ec78b326b52861")
    if (abs_tick & 0x80) != 0:
        ratio = mul_shift(ratio, "0xfe5dee046a99a2a811c461f1969c3053")
    if (abs_tick & 0x100) != 0:
        ratio = mul_shift(ratio, "0xfcbe86c7900a88aedcffc83b479aa3a4")
    if (abs_tick & 0x200) != 0:
        ratio = mul_shift(ratio, "0xf987a7253ac413176f2b074cf7815e54")
    if (abs_tick & 0x400) != 0:
        ratio = mul_shift(ratio, "0xf3392b0822b70005940c7a398e4b70f3")
    if (abs_tick & 0x800) != 0:
        ratio = mul_shift(ratio, "0xe7159475a2c29b7443b29c7fa6e889d9")
    if (abs_tick & 0x1000) != 0:
        ratio = mul_shift(ratio, "0xd097f3bdfd2022b8845ad8f792aa5825")
    if (abs_tick & 0x2000) != 0:
        ratio = mul_shift(ratio, "0xa9f746462d870fdf8a65dc1f90e061e5")
    if (abs_tick & 0x4000) != 0:
        ratio = mul_shift(ratio, "0x70d869a156d2a1b890bb3df62baf32f7")
    if (abs_tick & 0x8000) != 0:
        ratio = mul_shift(ratio, "0x31be135f97d08fd981231505542fcfa6")
    if (abs_tick & 0x10000) != 0:
        ratio = mul_shift(ratio, "0x9aa508b5b7a84e1c677de54f3e99bc9")
    if (abs_tick & 0x20000) != 0:
        ratio = mul_shift(ratio, "0x5d6af8dedb81196699c329225ee604")
    if (abs_tick & 0x40000) != 0:
        ratio = mul_shift(ratio, "0x2216e584f5fa1ea926041bedfe98")
    if (abs_tick & 0x80000) != 0:
        ratio = mul_shift(ratio, "0x48a170391f7dc42444e8fa2")

    if tick > 0:
        ratio = MAX_UINT_256 // ratio

    # back to Q96
    return (ratio // Q32) + 1 if (ratio % Q32) > 0 else ratio // Q32


TWO = 2
POWERS_OF_2 = [(128, 2**128), (64, 2**64), (32, 2**32), (16, 2**16), (8, 2**8), (4, 2**4), (2, 2**2), (1, 2**1)]


def most_significant_bit(x: int) -> int:
    """Find the most significant bit of x"""
    assert x > 0, "x must be greater than 0"
    assert x <= MAX_UINT_256, "x must be less than or equal to MAX_UINT_256"

    msb = 0
    for power, min_val in POWERS_OF_2:
        if x >= min_val:
            x >>= power
            msb += power
    return msb


def get_tick_at_sqrt_ratio(sqrt_ratio_x96: int) -> int:
    """
    Returns the tick corresponding to a given sqrt ratio, s.t. get_sqrt_ratio_at_tick(tick) <= sqrt_ratio_x96
    and get_sqrt_ratio_at_tick(tick + 1) > sqrt_ratio_x96
    """
    assert MIN_SQRT_RATIO <= sqrt_ratio_x96 < MAX_SQRT_RATIO, "Invalid sqrt ratio"

    sqrt_ratio_x128 = sqrt_ratio_x96 << 32
    msb = most_significant_bit(sqrt_ratio_x128)

    r = sqrt_ratio_x128 >> msb - 127 if msb >= 128 else sqrt_ratio_x128 << 127 - msb

    log_2 = (msb - 128) << 64

    for i in range(14):
        r = (r * r) >> 127
        f = r >> 128
        log_2 = log_2 | (f << (63 - i))
        r = r >> f

    log_sqrt10001 = log_2 * 255738958999603826347141

    tick_low = (log_sqrt10001 - 3402992956809132418596140100660247210) >> 128
    tick_high = (log_sqrt10001 + 291339464771989622907027621153398088495) >> 128

    return (
        tick_low if tick_low == tick_high else (tick_high if get_sqrt_ratio_at_tick(tick_high) <= sqrt_ratio_x96 else tick_low)
    )


def get_amount0_for_liquidity(lower_tick: int, upper_tick: int, liquidity: int) -> int:
    """Get amount0 for given liquidity and tick range"""
    sqrt_ratio_a_x96 = get_sqrt_ratio_at_tick(lower_tick)
    sqrt_ratio_b_x96 = get_sqrt_ratio_at_tick(upper_tick)
    return _get_amount0_for_liquidity(sqrt_ratio_a_x96, sqrt_ratio_b_x96, liquidity)


def _get_amount0_for_liquidity(sqrt_ratio_a_x96: int, sqrt_ratio_b_x96: int, liquidity: int) -> int:
    """Internal helper for amount0 calculation"""
    if sqrt_ratio_a_x96 > sqrt_ratio_b_x96:
        sqrt_ratio_a_x96, sqrt_ratio_b_x96 = sqrt_ratio_b_x96, sqrt_ratio_a_x96

    result = (liquidity << 96) * (sqrt_ratio_b_x96 - sqrt_ratio_a_x96)
    result = result // sqrt_ratio_b_x96
    return result // sqrt_ratio_a_x96


def get_amount1_for_liquidity(lower_tick: int, upper_tick: int, liquidity: int) -> int:
    """Get amount1 for given liquidity and tick range"""
    sqrt_ratio_a_x96 = get_sqrt_ratio_at_tick(lower_tick)
    sqrt_ratio_b_x96 = get_sqrt_ratio_at_tick(upper_tick)
    return _get_amount1_for_liquidity(sqrt_ratio_a_x96, sqrt_ratio_b_x96, liquidity)


def _get_amount1_for_liquidity(sqrt_ratio_a_x96: int, sqrt_ratio_b_x96: int, liquidity: int) -> int:
    """Internal helper for amount1 calculation"""
    if sqrt_ratio_a_x96 > sqrt_ratio_b_x96:
        sqrt_ratio_a_x96, sqrt_ratio_b_x96 = sqrt_ratio_b_x96, sqrt_ratio_a_x96

    result = liquidity * (sqrt_ratio_b_x96 - sqrt_ratio_a_x96)
    return result // Q96


def get_amounts_for_liquidity(sqrt_ratio_x96_string: str, lower_tick: int, upper_tick: int, liquidity: int) -> tuple[int, int]:
    """
    Get token amounts for given liquidity, current price, and tick range
    Returns (amount0, amount1)
    """
    sqrt_ratio_a_x96 = get_sqrt_ratio_at_tick(lower_tick)
    sqrt_ratio_b_x96 = get_sqrt_ratio_at_tick(upper_tick)
    sqrt_ratio_x96 = int(sqrt_ratio_x96_string)

    if sqrt_ratio_a_x96 > sqrt_ratio_b_x96:
        sqrt_ratio_a_x96, sqrt_ratio_b_x96 = sqrt_ratio_b_x96, sqrt_ratio_a_x96

    amount0 = 0
    amount1 = 0

    if sqrt_ratio_a_x96 > sqrt_ratio_x96:
        amount0 = _get_amount0_for_liquidity(sqrt_ratio_a_x96, sqrt_ratio_b_x96, liquidity)
    elif sqrt_ratio_b_x96 > sqrt_ratio_x96:
        amount0 = _get_amount0_for_liquidity(sqrt_ratio_x96, sqrt_ratio_b_x96, liquidity)
        amount1 = _get_amount1_for_liquidity(sqrt_ratio_a_x96, sqrt_ratio_x96, liquidity)
    else:
        amount1 = _get_amount1_for_liquidity(sqrt_ratio_a_x96, sqrt_ratio_b_x96, liquidity)

    return (amount0, amount1)


def get_liquidity_for_amount0(lower_tick: int, upper_tick: int, amount0: int) -> int:
    """Get liquidity for given amount0 and tick range"""
    sqrt_ratio_a_x96 = get_sqrt_ratio_at_tick(lower_tick)
    sqrt_ratio_b_x96 = get_sqrt_ratio_at_tick(upper_tick)

    if sqrt_ratio_a_x96 > sqrt_ratio_b_x96:
        sqrt_ratio_a_x96, sqrt_ratio_b_x96 = sqrt_ratio_b_x96, sqrt_ratio_a_x96

    intermediate = (sqrt_ratio_a_x96 * sqrt_ratio_b_x96) // Q96
    return (amount0 * intermediate) // (sqrt_ratio_b_x96 - sqrt_ratio_a_x96)


def get_liquidity_for_amount1(lower_tick: int, upper_tick: int, amount1: int) -> int:
    """Get liquidity for given amount1 and tick range"""
    sqrt_ratio_a_x96 = get_sqrt_ratio_at_tick(lower_tick)
    sqrt_ratio_b_x96 = get_sqrt_ratio_at_tick(upper_tick)

    if sqrt_ratio_a_x96 > sqrt_ratio_b_x96:
        sqrt_ratio_a_x96, sqrt_ratio_b_x96 = sqrt_ratio_b_x96, sqrt_ratio_a_x96

    return (amount1 * Q96) // (sqrt_ratio_b_x96 - sqrt_ratio_a_x96)


def get_liquidity_for_amounts(tick: int, lower_tick: int, upper_tick: int, amount0: int, amount1: int) -> int:
    """Get liquidity for given amounts and current tick"""
    sqrt_ratio_a_x96 = get_sqrt_ratio_at_tick(lower_tick)
    sqrt_ratio_b_x96 = get_sqrt_ratio_at_tick(upper_tick)
    sqrt_ratio_x96 = get_sqrt_ratio_at_tick(tick)

    if sqrt_ratio_a_x96 > sqrt_ratio_b_x96:
        sqrt_ratio_a_x96, sqrt_ratio_b_x96 = sqrt_ratio_b_x96, sqrt_ratio_a_x96

    if sqrt_ratio_a_x96 > sqrt_ratio_x96:
        return get_liquidity_for_amount0(lower_tick, upper_tick, amount0)
    if sqrt_ratio_b_x96 > sqrt_ratio_x96:
        liquidity0 = get_liquidity_for_amount0(tick, upper_tick, amount0)
        liquidity1 = get_liquidity_for_amount1(lower_tick, tick, amount1)
        return min(liquidity0, liquidity1)
    return get_liquidity_for_amount1(lower_tick, upper_tick, amount1)
