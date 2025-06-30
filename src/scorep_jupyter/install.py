from jupyter_client.kernelspec import KernelSpecManager
from IPython.utils.tempdir import TemporaryDirectory
import os
import sys
import json
from scorep_jupyter.logo import logo_image

kernel_spec = {
    "argv": [sys.executable, "-m", "scorep_jupyter.kernel", "-f", "{connection_file}"],
    "name": "scorep_jupyter",
    "display_name": "Score-P_Python",
    "language": "python",
}


def install_kernel_spec():
    with TemporaryDirectory() as d:
        with open(os.path.join(d, "kernel.json"), "w") as f:
            json.dump(kernel_spec, f, sort_keys=True)

        with open(os.path.join(d, "logo-64x64.png"), "wb") as f:
            f.write(logo_image)

        print("installed the scorep jupyter python kernel")
        KernelSpecManager().install_kernel_spec(d, "scorep_jupyter", user=True)


if __name__ == "__main__":
    install_kernel_spec()
