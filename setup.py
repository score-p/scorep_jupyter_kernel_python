import json
import os
import sys

from setuptools import setup
from setuptools.command.install import install as _install


class install(_install):
    def run(self):
        _install.run(self)
        os.system('jupyter kernelspec install kernelspec/ --name=scorep-python --user')
        os.remove("kernelspec/kernel.json")
        os.rmdir("kernelspec")


kernel_spec = {
    "argv": [sys.executable, "-m", "scorep_jupyter.kernel", "-f", "{connection_file}"],
    "display_name": "scorep-python",
    "name": "scorep-python",
    "language": "python"
}

os.mkdir("kernelspec")
with open("kernelspec/kernel.json", "w") as f:
    json.dump(kernel_spec, f, indent=4)

setup(
    name='scorep-jupyter',
    version='0.1.0',
    packages=["scorep_jupyter"],
    cmdclass={'install': install}
)
