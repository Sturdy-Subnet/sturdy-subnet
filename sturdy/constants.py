NUM_POOLS = 10  # number of pools to generate per query per epoch - for scoring miners
MIN_BASE_RATE = 0.02
MAX_BASE_RATE = 0.1
BASE_RATE_STEP = 0.01
MIN_SLOPE = 0.01
MAX_SLOPE = 0.1
MIN_KINK_SLOPE = 0.5
MAX_KINK_SLOPE = 3
SLOPE_STEP = 0.001
MIN_OPTIMAL_UTIL_RATE = 0.85
MAX_OPTIMAL_UTIL_RATE = 0.95
OPTIMAL_UTIL_STEP = 0.01
TOTAL_ASSETS = 1.0  # total assets to allocate ( set to 1 for simplicity :^) )
MIN_BORROW_AMOUNT = 0.05 * (TOTAL_ASSETS/NUM_POOLS)
AVG_BORROW_AMOUNT = 0.1  * (TOTAL_ASSETS/NUM_POOLS)
STD_BORROW_AMOUNT = 0.05 * (TOTAL_ASSETS/NUM_POOLS)
MAX_BORROW_AMOUNT = 0.2  * (TOTAL_ASSETS/NUM_POOLS)
BORROW_AMOUNT_STEP = 0.001
CHUNK_RATIO = 0.01  # chunk size as a percentage of total assets allocated during each iteration of greedy allocation algorithm
GREEDY_SIG_FIGS = 8  # significant figures to round to for greedy algorithm allocations

QUERY_TIMEOUT = 10  # timeout (seconds)
# latency reward curve scaling parameters
STEEPNESS = 1.0
DIV_FACTOR = 1.5  # a scaling factor

QUERY_RATE = 2 # how often synthetic validator queries miners (blocks)