import bittensor as bt
import gmpy2
import numpy as np

from sturdy.constants import (
    ALLOCATION_SIMILARITY_THRESHOLD,
    APY_BIN_THRESHOLD_FALLBACK,
    NORM_EXP_POW,
    TOP_PERFORMERS_BONUS,
    TOP_PERFORMERS_COUNT,
)
from sturdy.pools import ChainBasedPoolModel
from sturdy.protocol import AllocationsDict


def calculate_cv_threshold(apys: list[int]) -> float:
    """
    Calculate the coefficient of variation (CV) threshold for APYs.
    Filters out lower APYs dynamically by increasing percentile cutoff
    and returns the CV of the highest performing subset.
    """
    # Convert APY values to a NumPy array and clean up bad data
    apy_array = np.nan_to_num(
        np.array(apys, dtype=np.float64),
        nan=0.0,  # Replace NaNs with 0
        posinf=0.0,  # Replace +inf with 0
        neginf=0.0,  # Replace -inf with 0
    )

    # Dynamically estimate the threshold using high-percentile APYs
    for percentile in np.arange(5, 100, 5)[::-1]:
        threshold = np.percentile(apy_array, percentile)
        high_apys = apy_array[apy_array > threshold]

        if high_apys.size == 0:
            continue

        std = np.std(high_apys)
        mean = np.mean(high_apys)

        if mean > 0 and std > 0:
            # Calculate coefficient of variation as a dynamic threshold
            return float(std / mean)
    return APY_BIN_THRESHOLD_FALLBACK


def create_apy_bins(apys: dict[str, int], threshold_func=calculate_cv_threshold) -> dict[int, list[str]]:
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
    bin_threshold = threshold_func(list(apys.values()))

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
    apys_and_allocations: dict[str, dict[str, AllocationsDict | int]],
    assets_and_pools: dict,
) -> AllocationsDict:
    """
    Format and standardize allocations dictionary by padding missing pools and normalizing allocation values.

    Args:
        apys_and_allocations: Dictionary of miner allocations and APYs
        assets_and_pools: Dictionary containing pool information

    Returns:
        Formatted allocations dictionary sorted by miner UID
    """
    if not apys_and_allocations:
        return {}

    formatted_allocs = {}
    pools = assets_and_pools["pools"]

    for miner_uid, miner_data in apys_and_allocations.items():
        formatted_allocs[miner_uid] = {"allocations": {}}

        if miner_data is None:
            current_data = {"allocations": {}}
            miner_data = current_data

        if miner_data["allocations"] is None:
            miner_data["allocations"] = {}

        for pool_key in pools:
            # Get original allocation if it exists
            original_alloc = miner_data["allocations"].get(pool_key, 0)

            # Handle complex allocation objects (e.g., with amount field) - i.e. for alpha token pools
            if isinstance(original_alloc, dict):
                formatted_allocs[miner_uid]["allocations"][pool_key] = original_alloc.get("amount", 0)
            else:
                formatted_allocs[miner_uid]["allocations"][pool_key] = original_alloc

    return dict(sorted(formatted_allocs.items()))


def apply_similarity_penalties(
    bins: dict[int, list[str]],
    apys_and_allocations: dict[str, dict[str, AllocationsDict | int]],
    axon_times: dict[str, float],
    assets_and_pools: dict,
    miner_uids: list[str],
    similarity_threshold: float = ALLOCATION_SIMILARITY_THRESHOLD,
) -> np.ndarray:
    """
    Calculate similarity penalties within each bin, considering response times.
    Penalty increases with each similar allocation found from earlier miners.
    """
    penalties = np.zeros(len(miner_uids))
    uid_to_idx = {uid: idx for idx, uid in enumerate(miner_uids)}

    total_assets = assets_and_pools["total_assets"]
    allocs = format_allocations(apys_and_allocations, assets_and_pools)

    for bin_miners in bins.values():
        # Sort miners by axon time within each bin
        sorted_miners = sorted(bin_miners, key=lambda uid: axon_times[uid])

        for i, uid_a in enumerate(sorted_miners):
            if not allocs[uid_a] or allocs[uid_a].get("allocations") is None:
                continue

            alloc_a = np.array([gmpy2.mpz(val) for val in allocs[uid_a]["allocations"].values()], dtype=object)
            similar_count = 0
            max_possible_similarities = i  # Maximum number of possible similar earlier miners

            # Compare with miners that responded earlier
            for uid_b in sorted_miners[:i]:
                if not allocs[uid_b] or allocs[uid_b].get("allocations") is None:
                    continue

                alloc_b = np.array([gmpy2.mpz(val) for val in allocs[uid_b]["allocations"].values()], dtype=object)
                distance = calculate_allocation_distance(alloc_a, alloc_b, total_assets)

                if distance < similarity_threshold:
                    similar_count += 1

            # Calculate penalty based on proportion of similar allocations found
            if max_possible_similarities > 0:
                penalties[uid_to_idx[uid_a]] = similar_count / max_possible_similarities

    return penalties


def apply_penalties_to_rewards(rewards: np.ndarray, penalties: np.ndarray) -> np.ndarray:
    """
    Apply similarity penalties to rewards.

    Args:
        rewards: Original rewards array
        penalties: Penalties array from apply_similarity_penalties

    Returns:
        Updated rewards with penalties applied
    """
    # Ensure arrays are same length
    assert len(rewards) == len(penalties), "Rewards and penalties arrays must be same length"

    # Calculate penalty multiplier (1 - penalty)
    penalty_multiplier = 1 - penalties

    # Apply penalties to rewards
    return rewards * penalty_multiplier


def apply_top_performer_bonus(rewards: np.ndarray) -> np.ndarray:
    """Apply bonus multiplier to top performing miners."""
    final_rewards = rewards.copy()

    # Get indices of top performers in ascending order
    top_indices = np.argsort(rewards)[-TOP_PERFORMERS_COUNT:]

    # Apply incrementally larger bonuses to each top performer
    for i, idx in enumerate(top_indices):
        # Multiply bonus relative to position (higher position = higher bonus)
        final_rewards[idx] *= TOP_PERFORMERS_BONUS * (i + 1)

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
    apys_and_allocations: dict[str, dict[str, AllocationsDict | int]],
    assets_and_pools: dict[str, dict[str, ChainBasedPoolModel] | int],
    axon_times: dict[str, float],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Calculate rewards for miners within each bin, considering APY performance,
    allocation uniqueness, and response times.
    """
    # Get list of miner UIDs in original order
    miner_uids = list(apys_and_allocations.keys())

    # Calculate base rewards based on bin membership
    rewards = calculate_base_rewards(bins, miner_uids)

    # Apply penalties for similar allocations (only to later responders)
    penalties = apply_similarity_penalties(bins, apys_and_allocations, axon_times, assets_and_pools, miner_uids)

    # Apply penalties to rewards
    post_penalty_rewards = apply_penalties_to_rewards(rewards, penalties)

    # Normalize rewards within each bin
    rewards = normalize_bin_rewards(bins, rewards, post_penalty_rewards, miner_uids)

    # TODO: Apply exponential transformation? (disabled for now)
    # rewards = exponentiate_rewards(rewards)  # noqa: ERA001

    # TODO: Fix apply_top_performer_bonus before enabling
    # Currently, it favors accounts that appear later in the rewards array
    # rewards = apply_top_performer_bonus(rewards)

    # Normalize final rewards
    rewards = normalize_rewards(rewards)

    return rewards, penalties
