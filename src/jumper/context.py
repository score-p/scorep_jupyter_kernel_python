from dataclasses import dataclass

from jumper.perfdatahandler import PerformanceDataHandler


@dataclass
class KernelContext:
    # will be set to True as soon as GPU data is received
    gpu_avail = False
    perfdata_handler = PerformanceDataHandler()


kernel_context = KernelContext()
