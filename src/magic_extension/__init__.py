"""An example magic"""
__version__ = '0.0.1'

from magic_extension.magic import KernelMagics


def load_ipython_extension(ipython):
    print("magic_extension loaded!")
    ipython.register_magics(KernelMagics)