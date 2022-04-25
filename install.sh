#!/bin/bash

VIRTUAL_ENV_DIR=$HOME/virtualenv_jupyterkernel_scorep_python

virtualenv --system-site-packages $VIRTUAL_ENV_DIR
source $VIRTUAL_ENV_DIR/bin/activate

pip install scorep ipykernel pandas numpy torch tqdm cubex astunparse uuid

FULL_PATH_VIRTUAL_ENV_DIR_PYTHON=`which python`
FULL_PATH_VIRTUAL_ENV_DIR_SITE_PACKAGES=`python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())"`
#FULL_PATH_VIRTUAL_ENV_DIR_PYTHON="\""$(readlink -f $VIRTUAL_ENV_DIR)"/bin/python\""

cp scorep_jupyter_python_kernel.py userpersistence.py $VIRTUAL_ENV_DIR/lib/python3.8/site-packages/
sed -i "s@#*\(PYTHON_EXECUTABLE=\).*@\1 $FULL_PATH_VIRTUAL_ENV_DIR_PYTHON@" $FULL_PATH_VIRTUAL_ENV_DIR_SITE_PACKAGES/scorep_jupyter_python_kernel.py

mkdir kernelspec
JSON_FMT='{"argv":['"$FULL_PATH_VIRTUAL_ENV_DIR_PYTHON"', "-m", "scorep_jupyter_python_kernel", "-f", "{connection_file}"],"display_name":"scorep-python3","name":"scorep-python3", "language":"python3"}'
echo "$JSON_FMT" > kernelspec/kernel.json

jupyter kernelspec install kernelspec/ --name=scorep-python3 --user

rm kernelspec/ -r -f

cd test && python -m unittest userpersistence_test.py
