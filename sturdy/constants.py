NUM_POOLS = 10  # number of pools to generate per query per epoch - for scoring miners
MIN_BASE_RATE = 0.0
MAX_BASE_RATE = 0.0  # keep the base rate the same for every pool for now - 0
BASE_RATE_STEP = 0.01
MIN_SLOPE = 0.01
MAX_SLOPE = 0.05
MIN_KINK_SLOPE = 0.5
MAX_KINK_SLOPE = 3
SLOPE_STEP = 0.001
OPTIMAL_UTIL_RATE = 0.8
OPTIMAL_UTIL_STEP = 0.05
TOTAL_ASSETS = 1.0  # total assets to allocate ( set to 1 for simplicity :^) )
MIN_BORROW_AMOUNT = 0.001
MAX_BORROW_THRESHOLD = 0.001
MAX_BORROW_AMOUNT = (TOTAL_ASSETS / NUM_POOLS) - (TOTAL_ASSETS * MAX_BORROW_THRESHOLD)
BORROW_AMOUNT_STEP = 0.001
CHUNK_RATIO = 0.01  # chunk size as a percentage of total assets allocated during each iteration of greedy allocation algorithm
GREEDY_SIG_FIGS = 8  # significant figures to round to for greedy algorithm allocations

QUERY_TIMEOUT = 10  # timeout (seconds)
# latency reward curve scaling parameters
STEEPNESS = 1.0
DIV_FACTOR = 1.5  # a scaling factor

QUERY_RATE = 2 # how often synthetic validator queries miners (blocks)