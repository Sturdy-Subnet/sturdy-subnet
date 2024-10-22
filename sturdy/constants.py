NUM_POOLS = 10  # number of pools to generate per query per epoch - for scoring miners
MIN_BASE_RATE = 0
MAX_BASE_RATE = int(0.02e18)
BASE_RATE_STEP = int(0.01e18)
MIN_SLOPE = int(0.01e18)
MAX_SLOPE = int(0.05e18)
MIN_KINK_SLOPE = int(0.01e18)
MAX_KINK_SLOPE = int(0.05e18)
SLOPE_STEP = int(0.001e18)
MIN_OPTIMAL_RATE = int(0.80e18)
MAX_OPTIMAL_RATE = int(0.95e18)
OPTIMAL_UTIL_STEP = int(0.05e18)
MIN_UTIL_RATE = int(0.25e18)
MAX_UTIL_RATE = int(0.95e18)
UTIL_RATE_STEP = int(0.05e18)
MIN_TOTAL_ASSETS_OFFSET = 500e18  # 500 when converted from wei -> ether unit
MAX_TOTAL_ASSETS_OFFSET = 1000e18  # 3000
TOTAL_ASSETS_OFFSET_STEP = 100e18  # 100
SIG_FIGS = 8  # significant figures to round to for greedy algorithm allocations

REVERSION_SPEED = 0.15  # reversion speed to median borrow rate of pools
MIN_TIMESTEPS = 7
MAX_TIMESTEPS = 14
TIMESTEPS_STEP = 1
# some randomness to sprinkle into the simulation
MIN_STOCHASTICITY = 0.002  # min stochasticity
MAX_STOCHASTICITY = 0.002  # max stochasticity
STOCHASTICITY_STEP = 0.0001
POOL_RESERVE_SIZE = int(100e18)  # 100

QUERY_RATE = 2  # how often synthetic validator queries miners (blocks)
QUERY_TIMEOUT = 45  # timeout (seconds)

TOTAL_ALLOC_THRESHOLD = 0.98

# The following constants are for different pool models
# Aave
RESERVE_FACTOR_START_BIT_POSITION = 64
RESERVE_FACTOR_MASK = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000FFFFFFFFFFFFFFFF
SIMILARITY_THRESHOLD = 0.1  # similarity threshold for plagiarism checking

# yearn finance
APR_ORACLE = (
    "0x27aD2fFc74F74Ed27e1C0A19F1858dD0963277aE"  # https://docs.yearn.fi/developers/smart-contracts/V3/periphery/AprOracle
)
