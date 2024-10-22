import numpy as np


def wei_mul(x: int, y: int) -> int:
    return int((x * y) // 1e18)


def wei_div(x: int, y: int) -> int:
    return int((x / y) * 1e18)


def wei_mul_arrays(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (np.multiply(x, y)) // 1e18

def wei_div_arrays(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (np.divide(x, y)) * 1e18
