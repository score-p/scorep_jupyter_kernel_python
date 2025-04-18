import sys

from IPython.core.magic import (Magics, magics_class, line_magic, cell_magic)
from IPython.display import display, Markdown

from jumper.context import kernel_context
from jumper.kernel import KernelMode

from jumper.perfdatahandler import PerformanceDataHandler
import jumper.visualization as perfvis


@magics_class
class KernelMagics(Magics):
    def __init__(self, shell):
        super(KernelMagics, self).__init__(shell)
        self.mode = KernelMode.DEFAULT

        self.nodelist = kernel_context.perfdata_handler.get_nodelist()

    @cell_magic
    def abra(self, line, cell):
        print('HELLO!\n', cell)

    @line_magic
    def display_graph_for_all(self, line):
        data, time_indices = (
            kernel_context.perfdata_handler.get_perfdata_aggregated()
        )
        perfvis.draw_performance_graph(
            self.nodelist,
            data,
            kernel_context.gpu_avail,
            time_indices,
        )

    @line_magic
    def display_graph_for_index(self, line):
        """
        Display performance graph for a given index.
        Usage:
            %display_graph_for_index 2
        """

        if not line.strip():
            self.cell_output(
                "No index specified. Use: %display_graph_for_index index",
                "stderr"
            )
            return

        try:
            index = int(line.strip())
        except ValueError:
            self.cell_output(
                "Invalid index. Please provide an integer.",
                "stderr"
            )
            return

        history = kernel_context.perfdata_handler.get_perfdata_history()
        if index >= len(history):
            self.cell_output(
                f"Tracked only {len(history)} cells. This index is not available.",
                "stderr"
            )
            return

        time_indices = kernel_context.perfdata_handler.get_time_indices()[index]

        if time_indices:
            sub_idxs = [x[0] for x in time_indices[0]]
            self.cell_output(
                f"📈 Cell seemed to be tracked in multi-cell mode. "
                f"Got performance data for the following sub-cells: {sub_idxs}"
            )

        perfvis.draw_performance_graph(
            self.nodelist,
            history[index],
            kernel_context.gpu_avail,
            time_indices,
        )

    @line_magic
    def display_graph_for_last(self, line):
        if not len(kernel_context.perfdata_handler.get_perfdata_history()):
            self.cell_output("No performance data available.")
        time_indices = kernel_context.perfdata_handler.get_time_indices()[-1]
        if time_indices:
            sub_idxs = [x[0] for x in time_indices[0]]
            self.cell_output(
                f"Cell seemed to be tracked in multi cell"
                " mode. Got performance data for the"
                f" following sub cells: {sub_idxs}"
            )
        perfvis.draw_performance_graph(
            self.nodelist,
            kernel_context.perfdata_handler.get_perfdata_history()[-1],
            kernel_context.gpu_avail,
            time_indices,
        )


    @cell_magic
    def set_perfmonitor(self, line, code):
        """
        Read the perfmonitor and try to select it.
        """
        if self.mode == KernelMode.DEFAULT:
            monitor = code.split("\n")[1]
            if monitor in {"local", "localhost", "LOCAL", "LOCALHOST"}:
                self.cell_output(
                    "Selected local monitor. No parallel monitoring."
                )
            else:
                try:
                    kernel_context.perfdata_handler.set_monitor(monitor)
                    self.nodelist = kernel_context.perfdata_handler.get_nodelist()
                    if len(self.nodelist) <= 1:
                        self.nodelist = None
                        self.cell_output(
                            "Found monitor: "
                            + str(monitor)
                            + " but no nodelist, using local setup. "
                        )
                    else:
                        self.cell_output(
                            "Selected monitor: "
                            + str(monitor)
                            + " and got nodes: "
                            + str(self.nodelist)
                        )
                except Exception as e:
                    self.cell_output(
                        f"Error setting monitor\n{e}",
                        "stderr"
                    )
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )

    @staticmethod
    def cell_output(string: str, stream="stdout"):
        if stream == "stderr":
            print(string, file=sys.stderr)
        else:
            print(string)
