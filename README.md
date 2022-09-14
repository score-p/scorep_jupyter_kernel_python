# The Score-P Python Jupyter Kernel
This is the Score-P Python Kernel that enables you to execute Python code in Jupyter Notebooks with [Score-P](https://score-p.org/).

The kernel is based on the [Score-P Python bindings](https://github.com/score-p/scorep_binding_python).

## Installation

**For using the kernel you need a proper Score-P installation.**

To install the kernel and all dependencies use: 

```
pip install scorep-jupyter
python -m scorep_jupyter.install
```
The kernel will then be installed in your active python environment.

## Usage

### Configuring Score-P in Jupyter
You can set up your Score-P environment by executing a cell that starts with the `%%scorep_env magic command`.

You can set the Score-P Python binding arguments by executing a cell that starts with `%%scorep_python_binding_arguments`.

### Executing Cells 
Cells that should be executed with Score-P have to be marked with `%%execute_with_scorep` in the first line. Cells without that command are executed as ordinary Python processes.

### Multi Cell Mode
You can also treat multiple cells as one single cell by using the multi cell mode.

Therefore you can mark the cells in the order you wish to execute them. Start the marking process by a cell that starts with the `%%enable_multicellmode` command.
Now mark your cells by running them. Note that the cells will not be executed at this point but will be marked for later execution.
You can stop the marking and execute all the marked cells by running a cell that starts with `%%finalize_multicellmode` command.
This will execute all the marked cells orderly with Score-P. Note that the `%%execute_with_scorep` command has no effect in the multi cell mode.

There is no "unmark" command available but you can abort the multicellmode by the `%%abort_multicellmode` command. Start your marking process again if you have marked your cells in the wrong order.

The `%%enable_multicellmode`, `%%finalize_multicellmode` and `%%abort_multicellmode` commands should be run in an exclusive cell. Additional code in the cell will be ignored.

## Presentation of Performance Data

To inspect the collected performance data, use tools as Vampir (Trace) or Cube (Profile).

## Future Work

The kernel is still under development. The following is on the agenda:
 
 - add tensorflow backend for serialization to support tf
 - performance improvements (use shared memory for persistence handling)
 
PRs are welcome.

## General Limitations 

* The kernel does not support jupyter magic, since the Score-P Python binding does not support it.

For the execution of a cell, the kernel starts a new Python process either with Score-P or standalone. The kernel handles persistency between these processes on its own. Therefore it uses dill and additional techniques. However this comes with the following drawbacks:

* when dealing with big data structures, there might be a big runtime overhead at the beginning and the end of a cell. This is due to additional data saving and loading processes for persistency in the background. However this does not affect the actual user code and the Score-P measurements.
* dill can not handle each kind of object (e.g. file handles, network connections,...). Thus, they can not be shared between cells and your notebook might not work. We are working on this by adding further serialization mechanisms.


## Citing

If you publish some work using the kernel please cite the following paper:

```
Werner, E., Manjunath, L., Frenzel, J., & Torge, S. (2021, October).
Bridging between Data Science and Performance Analysis: Tracing of Jupyter Notebooks.
In The First International Conference on AI-ML-Systems (pp. 1-7).
```

The paper is available at: https://dl.acm.org/doi/abs/10.1145/3486001.3486249

## Contact

elias.werner@tu-dresden.de

## Acknowledgment

This work was supported by the German Federal Ministry of Education and Research (BMBF, SCADS22B) and the Saxon State Ministry for Science, Culture and Tourism (SMWK) by funding the competence center for Big Data and AI "ScaDS.AI Dresden/Leipzig


