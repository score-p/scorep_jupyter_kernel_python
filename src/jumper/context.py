from dataclasses import dataclass


@dataclass
class KernelContext:
    nodelist: list = None


kernel_context = KernelContext()
