from jupyter_client.kernelspec import KernelSpecManager
from IPython.utils.tempdir import TemporaryDirectory
import os
import sys
import json

kernel_spec = {
    "argv": [sys.executable, "-m", "pyperf_jupyter.kernel", "-f", "{connection_file}"],
    "name": "pyperfCPython",
    "display_name": "PyPerfCPython",
    "language": "python"
}


def install_kernel_spec():
    with TemporaryDirectory() as d:
        with open(os.path.join(d, 'kernel.json'), 'w') as f:
            json.dump(kernel_spec, f, sort_keys=True)
        print("installed the pyperf_jupyter kernel")
        KernelSpecManager().install_kernel_spec(d, 'PyPerfCPython', user=True)


if __name__ == '__main__':
    install_kernel_spec()
