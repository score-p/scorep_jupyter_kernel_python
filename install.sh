#!/bin/bash

VIRTUAL_ENV_DIR=$HOME/virtualenv_jupyterkernel_scorep_python

virtualenv --system-site-packages $VIRTUAL_ENV_DIR
source $VIRTUAL_ENV_DIR/bin/activate

FULL_PATH_VIRTUAL_ENV_DIR_PYTHON="\""$(readlink -f $VIRTUAL_ENV_DIR)"/bin/python\""

sed -i "s@#*\(PYTHON_EXECUTABLE=\).*@\1 $FULL_PATH_VIRTUAL_ENV_DIR_PYTHON@" scorep_jupyter_python_kernel.py

pip install scorep ipykernel pandas numpy torch tqdm 
cp scorep_jupyter_python_kernel.py userpersistency.py $VIRTUAL_ENV_DIR/lib/python3.8/site-packages/

mkdir kernelspec
JSON_FMT='{"argv":['"$FULL_PATH_VIRTUAL_ENV_DIR_PYTHON"', "-m", "scorep_jupyter_python_kernel", "-f", "{connection_file}"],"display_name":"scorep-python3","name":"scorep-python3", "language":"python3"}'
echo "$JSON_FMT" > kernelspec/kernel.json

jupyter kernelspec install kernelspec/ --name=scorep-python3 --user

rm kernelspec/ -r -f

cd test && python -m unittest userpersistency_test.py
