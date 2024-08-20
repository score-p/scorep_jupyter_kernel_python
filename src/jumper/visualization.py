import ipywidgets as widgets
from IPython.display import display
import os
import matplotlib.pyplot as plt
import random

perfmetrics = {
    "cpu_agg": "CPU Usage (Min/Max/Mean)",
    "cpu_raw": "CPU Usage (Raw)",
    "mem": "Mem in GB (Across nodes)",
    "io_ops": "IO Ops (Total)",
    "io_bytes": "IO MB (Total)",
    "gpu_usage_agg": "GPU Usage (Min/Max/Mean)",
    "gpu_mem_agg": "GPU Mem Usage (Min/Max/Mean)",
    "gpu_usage_raw": "GPU Usage (Raw)",
    "gpu_mem_raw": "GPU Mem (Raw)",
}


def plot_graph(ax, metric, perfdata, time_indices=None, color=None):
    # first 0 in perfdata index means first node
    ax.clear()  # Clear previous plot
    # generate scale
    nbr_cpus = len(perfdata[0][0]) - 3
    nbr_gpus = len(perfdata[0][6]) - 3
    x_scale = [
        x
        for x in range(
            0,
            int(os.environ.get("JUMPER_REPORT_FREQUENCY", 2))
            * len(perfdata[0][0][-3]),
            int(os.environ.get("JUMPER_REPORT_FREQUENCY", 2)),
        )
    ]
    print(time_indices)
    if metric == perfmetrics["cpu_agg"]:
        ax.plot(
            x_scale, perfdata[0][0][-3], label="Mean", color=(0.20, 0.47, 1.00)
        )
        ax.plot(
            x_scale,
            perfdata[0][0][-2],
            label="Max",
            color=(0.20, 0.47, 1.00, 0.3),
        )
        ax.plot(
            x_scale,
            perfdata[0][0][-1],
            label="Min",
            color=(0.20, 0.47, 1.00, 0.3),
        )
        ax.set_ylabel("Usage (%)")
    elif metric == perfmetrics["cpu_raw"]:
        for cpu_index in range(0, nbr_cpus):
            ax.plot(
                x_scale,
                perfdata[0][0][cpu_index],
                label="CPU" + str(cpu_index),
            )
        ax.set_ylabel("Usage (%)")
    elif metric == perfmetrics["mem"]:
        ax.plot(
            x_scale, perfdata[0][1], label="Value", color=(0.12, 0.70, 0.00)
        )
        ax.set_ylabel("GB")
    elif metric == perfmetrics["io_ops"]:
        ax.plot(
            x_scale, perfdata[0][2], label="IO Read", color=(1.00, 1.00, 0.10)
        )
        ax.plot(
            x_scale, perfdata[0][3], label="IO Write", color=(1.00, 0.50, 0.00)
        )
        ax.set_ylabel("Ops")
    elif metric == perfmetrics["io_bytes"]:
        ax.plot(
            x_scale, perfdata[0][4], label="IO Read", color=(0.50, 0.50, 0.00)
        )
        ax.plot(
            x_scale, perfdata[0][5], label="IO Write", color=(0.50, 0.25, 0.00)
        )
        ax.set_ylabel("Bytes")
    elif metric == perfmetrics["gpu_usage_agg"]:
        ax.plot(
            x_scale, perfdata[0][6][-3], label="Mean", color=(0.90, 0.30, 0.00)
        )
        ax.plot(
            x_scale,
            perfdata[0][6][-2],
            label="Max",
            color=(0.90, 0.30, 0.00, 0.3),
        )
        ax.plot(
            x_scale,
            perfdata[0][6][-1],
            label="Min",
            color=(0.90, 0.30, 0.00, 0.3),
        )
        ax.set_ylabel("Usage (%)")
    elif metric == perfmetrics["gpu_usage_raw"]:
        for gpu_index in range(0, nbr_gpus):
            ax.plot(
                x_scale,
                perfdata[0][6][gpu_index],
                label="GPU" + str(gpu_index),
            )
        ax.set_ylabel("Usage (%)")
    elif metric == perfmetrics["gpu_mem_agg"]:
        ax.plot(
            x_scale, perfdata[0][7][-3], label="Mean", color=(1.00, 0.40, 1.00)
        )
        ax.plot(
            x_scale,
            perfdata[0][7][-2],
            label="Max",
            color=(1.00, 0.40, 1.00, 0.3),
        )
        ax.plot(
            x_scale,
            perfdata[0][7][-1],
            label="Min",
            color=(1.00, 0.40, 1.00, 0.3),
        )
        ax.set_ylabel("Usage (%)")
    elif metric == perfmetrics["gpu_mem_raw"]:
        for gpu_index in range(0, nbr_gpus):
            ax.plot(
                x_scale,
                perfdata[0][7][gpu_index],
                label="GPU" + str(gpu_index),
            )
        ax.set_ylabel("Usage (%)")

    if metric == perfmetrics["cpu_agg"]:
        ax.set_title(
            "CPU Usage (Min/Max/Mean) | Across " + str(nbr_cpus) + " CPUs"
        )
    elif metric == perfmetrics["gpu_usage_agg"]:
        ax.set_title(
            "GPU Usage (Min/Max/Mean) | Across " + str(nbr_gpus) + " GPUs"
        )
    elif metric == perfmetrics["gpu_mem_agg"]:
        ax.set_title(
            "GPU Mem (Min/Max/Mean) | Across " + str(nbr_gpus) + " GPUs"
        )
    else:
        ax.set_title(f"{metric}")
    ax.set_xlabel("Time (s)")
    ax.legend()
    ax.grid(True)

    # in multi node case, we have to iterate over the indices (time_indices)
    # and not only 0 here
    current_index = 0
    target_index = -1
    transition_offset = (x_scale[1] - x_scale[0]) / 2
    start_offset = 0
    last_idx = time_indices[0][-1][0]

    for cell_idx, n_ms in time_indices[0]:

        target_index = target_index + n_ms
        # don't use offset for last cell
        if cell_idx == last_idx:
            transition_offset = 0
        ax.axvspan(x_scale[current_index] + start_offset,
                   x_scale[target_index] +
                   transition_offset,
                   facecolor=color[cell_idx], alpha=0.3)

        text_x_pos = x_scale[current_index] + start_offset + (
                (x_scale[target_index] + transition_offset -
                 x_scale[current_index] + start_offset) / 2)
        text_y_pos = ax.get_ylim()[0] + (ax.get_ylim()[1]*0.05)

        # add cell index to plot
        ax.text(text_x_pos, text_y_pos, "#" + str(cell_idx), style='italic',
                bbox={
                    'facecolor': 'lightgrey', 'alpha': 0.5, 'pad': 2}
                )

        current_index = target_index
        start_offset = transition_offset




def plot_with_dropdowns(metrics, perfdata, metric_start, time_indices=None):
    # Create subplots in a 1x2 grid
    fig, axes = plt.subplots(1, 2, figsize=(10, 3))
    dropdowns = []

    color = [
        "#" + ''.join([random.choice('0123456789ABCDEF') for j in range(6)])
        for i in range(len(time_indices[0]))]

    # Plot data and create dropdowns for each subplot
    for i, ax in enumerate(axes):
        plot_graph(ax, metrics[i + metric_start], perfdata,
                   time_indices, color)

        # Create dropdown widget for the current subplot
        dropdown = widgets.Dropdown(
            options=metrics,
            description="Metric:",
            value=metrics[i + metric_start],
        )
        dropdown.observe(
            lambda change, ax=ax: plot_graph(ax, change["new"], perfdata,
                                             time_indices),
            names="value",
        )

        # Add dropdown to list
        dropdowns.append(dropdown)
        # Display dropdowns and plots

    display(
        widgets.HBox(
            dropdowns, layout=widgets.Layout(margin="0 0", padding="0px 15%")
        )
    )
    plt.tight_layout()
    plt.show()


def draw_performance_graph(slurm_nodelist: None, perfdata, gpu_avail: False,
                           time_indices=None):
    if slurm_nodelist:
        nodelist = slurm_nodelist
        nodelist.insert(0, "All")
        dropdown = widgets.Dropdown(
            options=nodelist,
            value="All",
            description="Number:",
            disabled=False,
        )
        display(dropdown)

    # Dropdown widget
    metrics2display = list(perfmetrics.values())[:-4]
    if gpu_avail:
        metrics2display = list(perfmetrics.values())

    button = widgets.Button(description="Add Display")
    output = widgets.Output()

    display(button, output)

    def on_button_clicked(b):
        with output:
            plot_with_dropdowns(metrics2display, perfdata, 0, time_indices)

    button.on_click(on_button_clicked)

    plot_with_dropdowns(metrics2display, perfdata, 0, time_indices)
    if gpu_avail:
        plot_with_dropdowns(metrics2display, perfdata, 2, time_indices)
