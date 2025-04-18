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

        # will be set to True as soon as GPU data is received
        self.gpu_avail = False

    @cell_magic
    def abra(self, line, cell):
        print('HELLO!\n', cell)

    @line_magic
    def display_graph_for_all(self, line):
        data, time_indices = (
            kernel_context.perfdata_handler.get_perfdata_aggregated()
        )
        perfvis.draw_performance_graph(
            kernel_context.nodelist,
            data,
            self.gpu_avail,
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
                    kernel_context.nodelist = kernel_context.perfdata_handler.get_nodelist()
                    if len(kernel_context.nodelist) <= 1:
                        kernel_context.nodelist = None
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
                            + str(kernel_context.nodelist)
                        )
                except Exception as e:
                    self.cell_output(f"Error setting monitor\n{e}", "stderr")
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )

    @staticmethod
    def cell_output(string, stream="stdout"):
        if stream == "stderr":
            print(string, file=sys.stderr)
        else:
            print(string)
