import numpy as np


def wei_mul(x: int, y: int) -> int:
    return int((x * y) // 1e18)


def wei_div(x: int, y: int) -> int:
    return int((x / y) * 1e18)


def wei_mul_arrays(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    ret = (np.multiply(x, y)) // 1e18
    return ret
