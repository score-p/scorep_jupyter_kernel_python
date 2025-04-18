from dataclasses import dataclass
from enum import Enum

from jumper.perfdatahandler import PerformanceDataHandler


# kernel modes
class KernelMode(Enum):
    DEFAULT = (0, "default")
    MULTICELL = (1, "multicell")
    WRITEFILE = (2, "writefile")

    def __str__(self):
        return self.value[1]


@dataclass
class KernelContext:
    # will be set to True as soon as GPU data is received
    gpu_avail = False
    perfdata_handler = PerformanceDataHandler()


kernel_context = KernelContext()
