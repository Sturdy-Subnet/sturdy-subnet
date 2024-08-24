import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

from sturdy.utils.ethmath import wei_div, wei_mul
from sturdy.validator.simulator import Simulator
from sturdy.utils.misc import borrow_rate
from sturdy.constants import *

"""
This is a script which can be used to play around with the simulator.
It comes with a function to plot pool borrow rates, etc. over timestamps
"""


def plot_simulation_results(simulator):
    borrow_amount_history = []
    borrow_rate_history = []
    utilization_rate_history = []
    supply_rate_history = []
    median_borrow_rate_history = []

    for t in range(simulator.timesteps):
        borrow_amounts = [pool.borrow_amount for pool in simulator.pool_history[t].values()]
        reserve_sizes = [pool.reserve_size for pool in simulator.pool_history[t].values()]
        borrow_rates = [pool.borrow_rate for pool in simulator.pool_history[t].values()]
        utilization_rates = [wei_div(borrow_amounts[i], reserve_sizes[i]) for i in range(len(borrow_amounts))]
        supply_rates = [wei_mul(utilization_rates[i], borrow_rates[i]) for i in range(len(borrow_amounts))]

        borrow_amount_history.append(borrow_amounts)
        borrow_rate_history.append(borrow_rates)
        utilization_rate_history.append(utilization_rates)
        supply_rate_history.append(supply_rates)
        median_borrow_rate_history.append(np.median(borrow_rates))

    # Convert data to more manageable format
    borrow_amount_history_df = (
        pd.DataFrame(borrow_amount_history, columns=[
            f"Pool_{name[:6]}" for name in simulator.assets_and_pools["pools"]
            ]).apply(pd.to_numeric)
        / 1e18
    )
    borrow_rate_history_df = (
        pd.DataFrame(borrow_rate_history, columns=[
            f"Pool_{name[:6]}" for name in simulator.assets_and_pools["pools"]
            ]).apply(pd.to_numeric) / 1e18
    )
    utilization_rate_history_df = (
        pd.DataFrame(
            utilization_rate_history,
            columns=[
            f"Pool_{name[:6]}" for name in simulator.assets_and_pools["pools"]
            ],
        ).apply(pd.to_numeric)
        / 1e18
    )
    supply_rate_history_df = (
        pd.DataFrame(supply_rate_history, columns=[
            f"Pool_{name[:6]}" for name in simulator.assets_and_pools["pools"]
            ]).apply(pd.to_numeric)
        / 1e18
    )
    median_borrow_rate_history_df = (
        pd.Series(median_borrow_rate_history, name="Median Borrow Rate").apply(pd.to_numeric) / 1e18
    )

    plt.style.use("dark_background")
    fig, axs = plt.subplots(3, 2, figsize=(15, 15))
    axs[2, 1].remove()  # Remove the subplot in the bottom right corner
    axs[2, 0].remove()  # Remove the subplot in the bottom left corner

    def save_plot(event):
        if event.key == "s":
            plt.savefig("simulation_plot.png")
            print("Plot saved as 'simulation_plot.png'")

    fig.canvas.mpl_connect("key_press_event", save_plot)

    # Plot borrow rates with median borrow rate
    for column in borrow_rate_history_df:
        axs[0, 0].plot(
            borrow_rate_history_df.index,
            borrow_rate_history_df[column],
            label=column,
            alpha=0.5,
        )
    axs[0, 0].plot(
        median_borrow_rate_history_df.index,
        median_borrow_rate_history_df,
        label="Median Borrow Rate",
        color="white",
        linewidth=2,
        linestyle="--",
    )
    axs[0, 0].set_title("Simulated Borrow Rates Over Time")
    axs[0, 0].set_xlabel("Time Step")
    axs[0, 0].set_ylabel("Borrow Rate")
    axs[0, 0].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    # Plot borrow amounts
    borrow_amount_history_df.plot(ax=axs[0, 1])
    axs[0, 1].set_title("Simulated Borrow Amounts Over Time")
    axs[0, 1].set_xlabel("Time Step")
    axs[0, 1].set_ylabel("Borrow Amount")
    axs[0, 1].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    # Plot utilization rates
    utilization_rate_history_df.plot(ax=axs[1, 0])
    axs[1, 0].set_title("Simulated Utilization Rates Over Time")
    axs[1, 0].set_xlabel("Time Step")
    axs[1, 0].set_ylabel("Utilization Rate")
    axs[1, 0].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    # Plot supply rates
    supply_rate_history_df.plot(ax=axs[1, 1])
    axs[1, 1].set_title("Simulated Supply Rates Over Time")
    axs[1, 1].set_xlabel("Time Step")
    axs[1, 1].set_ylabel("Supply Rate")
    axs[1, 1].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    # Create a new axis that spans the entire bottom row
    ax_interest_rates = fig.add_subplot(3, 1, 3)

    # Plot interest rate curves for the pools
    utilization_range = np.linspace(0, 1, 100)
    for pool_addr, pool in simulator.assets_and_pools["pools"].items():
        interest_rates = [borrow_rate(u * 1e18, pool) / 1e18 for u in utilization_range]
        ax_interest_rates.plot(utilization_range, interest_rates, label=f"Pool_{pool_addr[:6]}")

    ax_interest_rates.set_title("Interest Rate Curves for the Pools")
    ax_interest_rates.set_xlabel("Utilization Rate")
    ax_interest_rates.set_ylabel("Borrow Rate")
    ax_interest_rates.legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    # Ensure labels don't overlap and improve layout
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()


# Usage
np.random.seed(69)
num_sims = 5
for i in range(num_sims):
    sim = Simulator(
        seed=np.random.randint(0, 1000),
    )
    sim.initialize()
    sim.init_data()
    sim.run()

    plot_simulation_results(sim)
