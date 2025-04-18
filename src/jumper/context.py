from dataclasses import dataclass

from jumper.perfdatahandler import PerformanceDataHandler


@dataclass
class KernelContext:
    nodelist: list = None
    perfdata_handler = PerformanceDataHandler()


kernel_context = KernelContext()
