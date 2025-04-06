SIG_FIGS = 8  # significant figures to round to for greedy algorithm allocations

QUERY_FREQUENCY = 10  # time in seconds between validator queries
QUERY_TIMEOUT = 3  # timeout (seconds)

MINER_SYNC_FREQUENCY = 300  # time in seconds between miner syncs

ORGANIC_SCORING_PERIOD = 300  # organic scoring period in seconds
MIN_SCORING_PERIOD = 180  # min. synthetic scoring period in seconds
MAX_SCORING_PERIOD = 240  # max. synthetic scoring period in seconds
SCORING_PERIOD_STEP = 60

SCORING_WINDOW = 180  # scoring window

TOTAL_ALLOC_THRESHOLD = 0.98
ALLOCATION_SIMILARITY_THRESHOLD = 1e-4  # similarity threshold for plagiarism checking

# Constants for APY-based binning and rewards
APY_BIN_THRESHOLD_FALLBACK = 1e-5  # Fallback threshold: 0.00001 difference in APY to create new bin
TOP_PERFORMERS_BONUS = 4.0  # Multiplier for top performing miners
TOP_PERFORMERS_COUNT = 10  # Number of top performers to receive bonus

NORM_EXP_POW = 16

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

# bittensor alpha token pools
MIN_BT_POOLS = 1  # minimum number of alpha token pools to generate per query per epoch - for scoring miners
MAX_BT_POOLS = 10  # maximum number of alpha token pools to generate per query per epoch - for scoring miners

MIN_TAO_IN_POOL = 0.0  # minimum amount of TAO a pool must have to consider it to be "valid"
