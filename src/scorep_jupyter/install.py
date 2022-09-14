from jupyter_client.kernelspec import KernelSpecManager
from IPython.utils.tempdir import TemporaryDirectory
import os
import sys
import json

kernel_spec = {
    "argv": [sys.executable, "-m", "scorep_jupyter.kernel", "-f", "{connection_file}"],
    "display_name": "scorep-python",
    "name": "scorep-python",
    "language": "python"
}


def install_kernel_spec():
    with TemporaryDirectory() as d:
        with open(os.path.join(d, 'kernel.json'), 'w') as f:
            json.dump(kernel_spec, f, sort_keys=True)
        print("installing the scorep jupyter kernel")
        KernelSpecManager().install_kernel_spec(d, 'scorep-python', user=True)


if __name__ == '__main__':
    install_kernel_spec()
