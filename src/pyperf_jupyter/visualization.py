import ipywidgets as widgets
from IPython.display import display
import os
import matplotlib.pyplot as plt


def plot_graph(ax, metric, perfdata):
    # first 0 means first node
    ax.clear()  # Clear previous plot
    # generate scale
    x_scale = [x for x in range(0, 2 * len(perfdata[0][0][-3]), int(os.environ.get("PYPERF_REPORT_FREQUENCY", 2)))]
    if metric == 'CPU Util (Min/Max/Mean)':
        ax.plot(x_scale, perfdata[0][0][-3], label='Mean', color=(0.20, 0.47, 1.00))
        ax.plot(x_scale, perfdata[0][0][-2], label='Max', color=(0.20, 0.47, 1.00, 0.3))
        ax.plot(x_scale, perfdata[0][0][-1], label='Min', color=(0.20, 0.47, 1.00, 0.3))
        ax.set_ylabel('Util (%)')
    elif metric == 'CPU Cores (Raw)':
        for cpu_index in range(0, len(perfdata[0][0]) - 3):
            ax.plot(x_scale, perfdata[0][0][cpu_index], label="CPU" + str(cpu_index))
        ax.set_ylabel('Util (%)')
    elif metric == 'Mem':
        ax.plot(x_scale, perfdata[0][1], label='Value', color=(0.12, 0.70, 0.00))
        ax.set_ylabel('Util (%)')
    elif metric == 'IO Ops':
        ax.plot(x_scale, perfdata[0][2], label='IO Read', color=(1.00, 1.00, 0.10))
        ax.plot(x_scale, perfdata[0][3], label='IO Write', color=(1.00, 0.50, 0.00))
        ax.set_ylabel('Ops')
    elif metric == 'IO Bytes':
        ax.plot(x_scale, perfdata[0][4], label='IO Read', color=(0.50, 0.50, 0.00))
        ax.plot(x_scale, perfdata[0][5], label='IO Write', color=(0.50, 0.25, 0.00))
        ax.set_ylabel('Bytes')
    elif metric == 'GPU Util':
        ax.plot(x_scale, perfdata[0][6][-3], label='Mean', color=(0.90, 0.30, 0.00))
        ax.plot(x_scale, perfdata[0][6][-2], label='Max', color=(0.90, 0.30, 0.00, 0.3))
        ax.plot(x_scale, perfdata[0][6][-1], label='Min', color=(0.90, 0.30, 0.00, 0.3))
        ax.set_ylabel('Util (%)')
    elif metric == 'GPU Mem':
        ax.plot(x_scale, perfdata[0][7][-3], label='Mean', color=(1.00, 0.40, 1.00))
        ax.plot(x_scale, perfdata[0][7][-2], label='Max', color=(1.00, 0.40, 1.00, 0.3))
        ax.plot(x_scale, perfdata[0][7][-1], label='Min', color=(1.00, 0.40, 1.00, 0.3))
        ax.set_ylabel('Util (%)')

    ax.set_title(f'{metric}')
    ax.set_xlabel('Time (s)')
    ax.legend()
    ax.grid(True)


def plot_with_dropdowns(metrics, perfdata, metric_start):
    # Create subplots in a 1x2 grid
    fig, axes = plt.subplots(1, 2, figsize=(10, 3))
    dropdowns = []

    # Plot data and create dropdowns for each subplot
    for i, ax in enumerate(axes):
        plot_graph(ax, metrics[i + metric_start], perfdata)

        # Create dropdown widget for the current subplot
        dropdown = widgets.Dropdown(options=metrics, description='Metric:', value=metrics[i + metric_start])
        dropdown.observe(lambda change, ax=ax: plot_graph(ax, change['new'], perfdata), names='value')

        # Add dropdown to list
        dropdowns.append(dropdown)
        # Display dropdowns and plots

    display(widgets.HBox(dropdowns, layout=widgets.Layout(margin='0 0', padding='0px 15%')))
    plt.tight_layout()
    plt.show()


def draw_performance_graph(slurm_nodelist:None, perfdata, gpu_avail:False):
    if slurm_nodelist:
        nodelist = slurm_nodelist
        nodelist.insert(0, 'All')
        dropdown = widgets.Dropdown(
            options=nodelist,
            value='All',
            description='Number:',
            disabled=False,
        )
        display(dropdown)

    # Dropdown widget
    metrics = ['CPU Util (Min/Max/Mean)', 'CPU Cores (Raw)', 'Mem', 'IO Ops', 'IO Bytes']
    if gpu_avail:
        metrics.extend(["GPU Util", "GPU Mem"])

    button = widgets.Button(description="Add Display")
    output = widgets.Output()

    display(button, output)

    def on_button_clicked(b):
        with output:
            plot_with_dropdowns(metrics, perfdata, 0)

    button.on_click(on_button_clicked)

    plot_with_dropdowns(metrics, perfdata, 0)
    if gpu_avail:
        plot_with_dropdowns(metrics, perfdata, 2)