import numpy as np
import gmpy2
from typing import Dict, List

from sturdy.constants import APY_BIN_THRESHOLD, TOP_PERFORMERS_BONUS, TOP_PERFORMERS_COUNT


def create_apy_bins(apys: dict[str, int], bin_threshold: int = APY_BIN_THRESHOLD) -> dict[int, list[str]]:
    """
    Creates bins of miners based on their APY values using relative differences.

    Args:
        apys: Dictionary mapping miner UIDs to their APY values
        bin_threshold: Threshold for creating new bins (default: APY_BIN_THRESHOLD)

    Returns:
        Dictionary mapping bin indices to lists of miner UIDs
    """
    # Sort APYs in descending order
    sorted_items = sorted(apys.items(), key=lambda x: x[1], reverse=True)

    bins: dict[int, list[str]] = {}
    current_bin = 0

    if not sorted_items:
        return bins

    # Initialize first bin with highest APY miner
    bins[current_bin] = [sorted_items[0][0]]
    current_base_apy = sorted_items[0][1]

    # Assign miners to bins based on APY differences
    for uid, apy in sorted_items[1:]:
        # Calculate relative difference from current bin's base APY
        # Using relative difference: (a - b) / max(|a|, |b|)
        relative_diff = abs(apy - current_base_apy) / max(abs(current_base_apy), abs(apy), 1)

        if relative_diff > (bin_threshold):  # Convert threshold to decimal
            # Create new bin
            current_bin += 1
            current_base_apy = apy
            bins[current_bin] = [uid]
        else:
            # Add to current bin
            bins[current_bin].append(uid)

    return bins


def calculate_bin_rewards(bins: Dict[int, List[str]], allocations: Dict[str, dict], total_assets: int) -> Dict[str, float]:
    """
    Calculates rewards for miners within each bin based on allocation similarity.
    """
    rewards = {}

    for bin_idx, miner_uids in bins.items():
        bin_size = len(miner_uids)
        if bin_size == 0:
            continue

        # Base reward for this bin (higher bins get higher base rewards)
        base_reward = 1.0 - (bin_idx * 0.1)  # Decrease reward by 10% for each lower bin

        # Calculate allocation similarities within bin
        for uid_a in miner_uids:
            alloc_a = np.array([gmpy2.mpz(val) for val in allocations[uid_a]["allocations"].values()], dtype=object)

            # Start with base reward
            similarity_penalty = 0

            # Compare with other miners in same bin
            for uid_b in miner_uids:
                if uid_a != uid_b:
                    alloc_b = np.array([gmpy2.mpz(val) for val in allocations[uid_b]["allocations"].values()], dtype=object)

                    # Calculate Euclidean distance with gmpy2
                    squared_diff_sum = gmpy2.mpz(0)
                    for x, y in zip(alloc_a, alloc_b, strict=False):
                        diff = x - y
                        squared_diff_sum += diff * diff

                    # Calculate normalized distance
                    total_assets_mpz = gmpy2.mpz(total_assets)
                    diff = float(gmpy2.sqrt(squared_diff_sum)) / float(total_assets_mpz * gmpy2.sqrt(2))
                    similarity_penalty += (1 - diff) / (bin_size - 1)

            # Final reward calculation
            rewards[uid_a] = base_reward * (1 - similarity_penalty)

    # Apply bonus to top performers
    sorted_rewards = sorted(rewards.items(), key=lambda x: x[1], reverse=True)
    for i in range(min(TOP_PERFORMERS_COUNT, len(sorted_rewards))):
        uid = sorted_rewards[i][0]
        rewards[uid] *= TOP_PERFORMERS_BONUS

    # Normalize rewards
    max_reward = max(rewards.values())
    if max_reward > 0:
        rewards = {uid: r / max_reward for uid, r in rewards.items()}

    return rewards
