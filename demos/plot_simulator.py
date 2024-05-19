import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

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
        borrow_amounts = [
            pool["borrow_amount"] for pool in simulator.pool_history[t].values()
        ]
        reserve_sizes = [
            pool["reserve_size"] for pool in simulator.pool_history[t].values()
        ]
        borrow_rates = [
            pool["borrow_rate"] for pool in simulator.pool_history[t].values()
        ]
        utilization_rates = [
            borrow_amounts[i] / reserve_sizes[i] for i in range(len(borrow_amounts))
        ]
        supply_rates = [
            utilization_rates[i] * borrow_rates[i] for i in range(len(borrow_amounts))
        ]

        borrow_amount_history.append(borrow_amounts)
        borrow_rate_history.append(borrow_rates)
        utilization_rate_history.append(utilization_rates)
        supply_rate_history.append(supply_rates)
        median_borrow_rate_history.append(np.median(borrow_rates))

    borrow_amount_history_df = pd.DataFrame(
        borrow_amount_history, columns=[f"Pool_{i}" for i in range(len(borrow_amounts))]
    )
    borrow_rate_history_df = pd.DataFrame(
        borrow_rate_history, columns=[f"Pool_{i}" for i in range(len(borrow_rates))]
    )
    utilization_rate_history_df = pd.DataFrame(
        utilization_rate_history,
        columns=[f"Pool_{i}" for i in range(len(borrow_rates))],
    )
    supply_rate_history_df = pd.DataFrame(
        supply_rate_history, columns=[f"Pool_{i}" for i in range(len(borrow_amounts))]
    )
    median_borrow_rate_history_df = pd.Series(
        median_borrow_rate_history, name="Median Borrow Rate"
    )

    fig, axs = plt.subplots(5, 1, figsize=(12, 35))

    def save_plot(event):
        if event.key == "s":
            plt.savefig("simulation_plot.png")
            print("Plot saved as 'simulation_plot.png'")

    fig.canvas.mpl_connect("key_press_event", save_plot)

    for column in borrow_rate_history_df:
        axs[0].plot(
            borrow_rate_history_df.index,
            borrow_rate_history_df[column],
            label=column,
            alpha=0.5,
        )
    axs[0].plot(
        median_borrow_rate_history_df.index,
        median_borrow_rate_history_df,
        label="Median Borrow Rate",
        color="black",
        linewidth=2,
        linestyle="--",
    )
    axs[0].set_title("Simulated Borrow Rates Over Time")
    axs[0].set_xlabel("Time Step")
    axs[0].set_ylabel("Borrow Rate")
    axs[0].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    borrow_amount_history_df.plot(ax=axs[1])
    axs[1].set_title("Simulated Borrow Amounts Over Time")
    axs[1].set_xlabel("Time Step")
    axs[1].set_ylabel("Borrow Amount")
    axs[1].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    utilization_rate_history_df.plot(ax=axs[2])
    axs[2].set_title("Simulated Utilization Rates Over Time")
    axs[2].set_xlabel("Time Step")
    axs[2].set_ylabel("Utilization Rate")
    axs[2].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    supply_rate_history_df.plot(ax=axs[3])
    axs[3].set_title("Simulated Supply Rates Over Time")
    axs[3].set_xlabel("Time Step")
    axs[3].set_ylabel("Supply Rate")
    axs[3].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    utilization_range = np.linspace(0, 1, 100)
    for i in range(NUM_POOLS):
        interest_rates = [
            borrow_rate(u, simulator.assets_and_pools["pools"][str(i)])
            for u in utilization_range
        ]
        axs[4].plot(utilization_range, interest_rates, label=f"Pool_{i}")
    axs[4].set_title("Interest Rate Curves for the Pools")
    axs[4].set_xlabel("Utilization Rate")
    axs[4].set_ylabel("Borrow Rate")
    axs[4].legend(title="Pools", bbox_to_anchor=(1.05, 1), loc="upper left")

    plt.tight_layout()
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
