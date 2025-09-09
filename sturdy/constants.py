MINER_SYNC_FREQUENCY = 300  # time in seconds between miner syncs
NEW_TASK_INITIAL_DELAY = 30  # time in seconds to delay the new task loop on initial startup

MAIN_LOOP_FREQUENCY = 300  # time in seconds between main loop iterations
UNISWAP_V3_LP_QUERY_FREQUENCY = 3600  # time in seconds between Uniswap V3 LP queries

# thresholds for the percentage of miners in each gruop before applying penalties to lowest performing miners in each group
MINER_GROUP_THRESHOLDS = {
    "UNISWAP_V3_LP": 200,  # 200 of the miners will be UniswapV3 liquidity providing miners for TaoFi
}

# Default moving average alpha parameters for each miner group
LP_MINER_ALPHA = 0.5

# Validators don't have to verify signatures from miners in the whitelist.
WHITELISTED_LP_MINER = "5H3QttLgF7nzWGLSpXkH6gMC6XnSovfGa1xRosqyjVqB7XoS"

# Emissions split
MINER_GROUP_EMISSIONS = {
    "UNISWAP_V3_LP": 1,  # uniswap lp miners will receive 100% of the emissions
}

# Uniswap V3 LP subgraph URL for Taofi
TAOFI_GQL_URL = "https://subgraph.taofi.com/subgraphs/name/uniswap/v3-older"
