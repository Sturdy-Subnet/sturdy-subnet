import bittensor as bt
import gmpy2
import numpy as np

from sturdy.constants import (
    ALLOCATION_SIMILARITY_THRESHOLD,
    APY_BIN_THRESHOLD,
    NORM_EXP_POW,
    TOP_PERFORMERS_BONUS,
    TOP_PERFORMERS_COUNT,
)
from sturdy.pools import ChainBasedPoolModel
from sturdy.protocol import AllocationsDict


def create_apy_bins(apys: dict[str, int], bin_threshold: float = APY_BIN_THRESHOLD) -> dict[int, list[str]]:
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

        if relative_diff > bin_threshold:
            # Create new bin
            current_bin += 1
            current_base_apy = apy
            bins[current_bin] = [uid]
        else:
            # Add to current bin
            bins[current_bin].append(uid)

    return bins


def calculate_allocation_distance(alloc_a: np.ndarray, alloc_b: np.ndarray, total_assets: int) -> float:
    """Calculate normalized Euclidean distance between two allocations."""
    try:
        squared_diff_sum = gmpy2.mpz(0)
        for x, y in zip(alloc_a, alloc_b, strict=False):
            diff = x - y
            squared_diff_sum += diff * diff

        total_assets_mpz = gmpy2.mpz(total_assets)
        return float(gmpy2.sqrt(squared_diff_sum)) / float(total_assets_mpz * gmpy2.sqrt(2))
    except Exception as e:
        bt.logging.error(f"Error calculating distance: {e}")
        return 1.0  # Return max distance on error


def calculate_base_rewards(bins: dict[int, list[str]], miner_uids: list[str]) -> np.ndarray:
    """Calculate base rewards for each miner based on their bin."""
    base_rewards = np.zeros(len(miner_uids))

    for bin_idx, bin_miners in bins.items():
        # Higher bins get better base rewards
        base_reward = max(0.0, 1.0 - (bin_idx * 0.1))
        for uid in bin_miners:
            idx = miner_uids.index(uid)  # Get index directly from list
            base_rewards[idx] = base_reward

    return base_rewards


def format_allocations(
    allocations: AllocationsDict,
    assets_and_pools: dict,
) -> AllocationsDict:
    # TODO: better way to do this?
    if allocations is None:
        allocations = {}
    allocs = allocations.copy()
    pools = assets_and_pools["pools"]

    # pad the allocations
    for contract_addr in pools:
        if contract_addr not in allocs:
            allocs[contract_addr] = 0

    # sort the allocations by contract address
    return {contract_addr: allocs[contract_addr] for contract_addr in sorted(allocs.keys())}


def apply_similarity_penalties(
    bins: dict[int, list[str]],
    allocations: AllocationsDict,
    axon_times: dict[str, float],
    assets_and_pools: dict,
    miner_uids: list[str],
    similarity_threshold: float = ALLOCATION_SIMILARITY_THRESHOLD,
) -> np.ndarray:
    """
    Calculate similarity penalties within each bin, considering response times.
    Only penalize miners who submitted similar allocations after another miner.
    """
    penalties = np.zeros(len(miner_uids))
    uid_to_idx = {uid: idx for idx, uid in enumerate(miner_uids)}

    total_assets = assets_and_pools["total_assets"]
    allocs = format_allocations(allocations, assets_and_pools)

    for bin_miners in bins.values():
        # Sort miners by axon time within each bin
        sorted_miners = sorted(bin_miners, key=lambda uid: axon_times[uid])

        for i, uid_a in enumerate(sorted_miners):
            # Skip if allocation is None
            if not allocs[uid_a] or allocs[uid_a].get("allocations") is None:
                continue

            alloc_a = np.array([gmpy2.mpz(val) for val in allocs[uid_a]["allocations"].values()], dtype=object)
            earliest_similar = i  # Default to current position

            # Only compare with miners that responded earlier
            for j, uid_b in enumerate(sorted_miners[:i]):
                # Skip if allocation is None
                if not allocs[uid_b] or allocs[uid_b].get("allocations") is None:
                    continue

                alloc_b = np.array([gmpy2.mpz(val) for val in allocs[uid_b]["allocations"].values()], dtype=object)
                distance = calculate_allocation_distance(alloc_a, alloc_b, total_assets)

                # If allocations are too similar, track the earliest miner with similar allocation
                if distance < similarity_threshold:
                    earliest_similar = min(earliest_similar, j)
                    break

            # If we found an earlier miner with similar allocation, apply penalty proportional to position difference
            if earliest_similar < i:
                penalties[uid_to_idx[uid_a]] = (i - earliest_similar) / i

    return penalties


def apply_top_performer_bonus(rewards: np.ndarray) -> np.ndarray:
    """Apply bonus multiplier to top performing miners."""
    final_rewards = rewards.copy()

    # Get indices of top performers
    top_indices = np.argsort(rewards)[-TOP_PERFORMERS_COUNT:]

    # Apply bonus to top performers
    final_rewards[top_indices] *= TOP_PERFORMERS_BONUS

    return final_rewards


def exponentiate_rewards(rewards: np.ndarray) -> np.ndarray:
    """Apply exponential transformation to rewards."""
    return np.pow(rewards, NORM_EXP_POW)


def normalize_rewards(rewards: np.ndarray, epsilon: float = 1e-8, min_val: float = 0.0, max_val: float = 1.0) -> np.ndarray:
    """Normalize rewards to [min_val, max_val] range."""
    if not len(rewards):
        return rewards
    if np.any(np.isnan(rewards)):
        return np.zeros_like(rewards)
    min_reward = np.min(rewards)
    max_reward = np.max(rewards)
    if max_reward == min_reward:
        return np.ones_like(rewards) * max_val
    return (rewards - min_reward) / (max_reward - min_reward + epsilon) * (max_val - min_val) + min_val


def normalize_bin_rewards(
    bins: dict[int, list[str]],
    rewards_before_penalties: np.ndarray,
    rewards_after_penalties: np.ndarray,
    miner_uids: list[str],
) -> np.ndarray:
    """
    Normalizes rewards within each bin to prevent higher-apy miners from scoring less than lesser-apy miners.
    This normalization ensures that having similar apy to miners in a bin does not cause the miner to end up
    being scored less than miners in previous bins.
    """
    rewards_before = rewards_before_penalties.copy()
    rewards = rewards_after_penalties.copy()

    bin_idxs = sorted(bins.keys(), reverse=True)

    # set prev_max_score to the min score in the last bin
    prev_max_score = 0.0

    # Iterate through bins in reverse order (from lowest APY to highest)
    for bin_idx in bin_idxs:
        bin_miners = bins[bin_idx]
        # Get indices of miners in current bin
        bin_indices = [miner_uids.index(uid) for uid in bin_miners]

        # Get max score in current bin before penalties
        max_score_bin = np.max(rewards_before[bin_indices])

        # Normalize the rewards_after_penalties in the current bin
        rewards[bin_indices] = normalize_rewards(
            rewards_after_penalties[bin_indices], min_val=prev_max_score, max_val=max_score_bin
        )

        # Update min score for next bin
        prev_max_score = max_score_bin

    return rewards


def calculate_bin_rewards(
    bins: dict[int, list[str]],
    allocations: AllocationsDict,
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel] | int],
    axon_times: dict[str, float],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Calculate rewards for miners within each bin, considering APY performance,
    allocation uniqueness, and response times.
    """
    # Get list of miner UIDs in original order
    miner_uids = list(allocations.keys())

    # Calculate base rewards based on bin membership
    rewards = calculate_base_rewards(bins, miner_uids)

    # Apply penalties for similar allocations (only to later responders)
    penalties = apply_similarity_penalties(bins, allocations, axon_times, assets_and_pools, miner_uids)

    # Apply penalties to rewards
    post_penalty_rewards = rewards * (1 - penalties)

    # Normalize rewards within each bin
    rewards = normalize_bin_rewards(bins, rewards, post_penalty_rewards, miner_uids)

    # TODO: Apply exponential transformation? (disabled for now)
    # rewards = exponentiate_rewards(rewards)  # noqa: ERA001

    # Apply bonus to top performers
    rewards = apply_top_performer_bonus(rewards)

    # Normalize final rewards
    rewards = normalize_rewards(rewards)

    return rewards, penalties
