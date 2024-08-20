from jupyter_client.kernelspec import KernelSpecManager
from IPython.utils.tempdir import TemporaryDirectory
import os
import sys
import json
from jumper.logo import logo_image

kernel_spec = {
    "argv": [sys.executable, "-m", "jumper.kernel", "-f", "{connection_file}"],
    "name": "jumper",
    "display_name": "JUmPER",
    "language": "python",
}


def install_kernel_spec():
    with TemporaryDirectory() as d:
        with open(os.path.join(d, "kernel.json"), "w") as f:
            json.dump(kernel_spec, f, sort_keys=True)

        with open(os.path.join(d, "logo-64x64.png"), "wb") as f:
            f.write(logo_image)

        print("installed the jumper kernel")
        KernelSpecManager().install_kernel_spec(d, "jumper", user=True)


if __name__ == "__main__":
    install_kernel_spec()
