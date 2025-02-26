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

QUERY_FREQUENCY = 600  # time in seconds between validator queries
QUERY_TIMEOUT = 45  # timeout (seconds)

MINER_SYNC_FREQUENCY = 300  # time in seconds between miner syncs

ORGANIC_SCORING_PERIOD = 28800  # scoring period in seconds
MIN_SCORING_PERIOD = 7200  # min. synthetic scoring period in seconds
MAX_SCORING_PERIOD = 43200  # max. synthetic scoring period in seconds
SCORING_PERIOD_STEP = 3600  # scoring period increments in seconds

SCORING_WINDOW = 420  # scoring window

TOTAL_ALLOC_THRESHOLD = 0.98
ALLOCATION_SIMILARITY_THRESHOLD = 1e-4  # similarity threshold for plagiarism checking
APY_SIMILARITY_THRESHOLD = 1e-4

DB_DIR = "validator_database.db"  # default validator database dir

MIN_TOTAL_ASSETS_AMOUNT = int(1000e6)  # min total assets required in a request to query miners

# The following constants are for different pool models
# Aave
RESERVE_FACTOR_START_BIT_POSITION = 64
RESERVE_FACTOR_MASK = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000FFFFFFFFFFFFFFFF

# yearn finance
APR_ORACLE = (
    "0x27aD2fFc74F74Ed27e1C0A19F1858dD0963277aE"  # https://docs.yearn.fi/developers/smart-contracts/V3/periphery/AprOracle
)
