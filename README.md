[![Unit Tests](https://github.com/score-p/scorep_jupyter_kernel_python/actions/workflows/unit_test.yml/badge.svg)](https://github.com/score-p/scorep_jupyter_kernel_python/actions/workflows/unit_test.yml)
[![Formatting](https://github.com/score-p/scorep_jupyter_kernel_python/actions/workflows/formatter.yml/badge.svg)](https://github.com/score-p/scorep_jupyter_kernel_python/actions/workflows/formatter.yml)
[![Static Analysis](https://github.com/score-p/scorep_jupyter_kernel_python/actions/workflows/linter.yml/badge.svg)](https://github.com/score-p/scorep_jupyter_kernel_python/actions/workflows/linter.yml)

<p align="center">
<img width="450" src="doc/JUmPER01.png"/>
</p>

# JUmPER: Jupyter meets Performance

JUmPER brings performance engineering to Jupyter. It consists of the two repositories:

- JUmPER Ipython extension (https://github.com/ScaDS/jumper_ipython_extension)

The extension allows you to take coarse-grained performance measurements and create visualizations in your Python kernels.

- Score-P Jupyter kernel Python (this repository)

The Score-P kernel allows you to instrument, and trace or profile your Python code in Jupyter using [Score-P](https://score-p.org/). 

For binding to Score-P, the kernel uses the [Score-P Python bindings](https://github.com/score-p/scorep_binding_python). 


# Table of Content

- [A Jupyter Kernel for Performance Engineering](#a-jupyter-kernel-for-performance-engineering)
- [Table of Content](#table-of-content)
- [Installation](#installation)
- [Usage](#usage)
  - [Score-P Instrumentation](#score-p-instrumentation)
    - [Configuring Score-P in Jupyter](#configuring-score-p-in-jupyter)
  - [Multi-Cell Mode](#multi-cell-mode)
  - [Write Mode](#write-mode)
- [Presentation of Performance Data](#presentation-of-performance-data)
- [Limitations](#limitations)
  - [Serialization Type Support](#serialization-type-support)
  - [Overhead](#overhead)
  - [Logging Configuration](#logging-configuration)
- [Future Work](#future-work)
- [Citing](#citing)
- [Contact](#contact)
- [Acknowledgments](#acknowledgments)

# Installation

To install the kernel and required dependencies:

```
pip install scorep-jupyter
python -m scorep_jupyter.install
```

You can also build the kernel from source via:

```
pip install .
```

The kernel will then be installed in your active python environment.
You can select the kernel in Jupyter as `Score-P_Python`.

**For using the Score-P features of the kernel you need a proper Score-P installation.**

From the Score-P Python bindings:

> You need at least Score-P 5.0, build with `--enable-shared` and the gcc compiler plugin.
> Please make sure that `scorep-config` is in your `PATH` variable.
> For Ubuntu LTS systems there is a non-official ppa of Score-P available: https://launchpad.net/~andreasgocht/+archive/ubuntu/scorep .

To use the coarse-grained performance measurements, simply install the jumper ipython extension via:

```
pip install jumper_extension
```

Then load it in a Jupyter cell with:

```
%load_ext jumper_extension
```

You can find usage information in the repository of the extension.

# Usage

## Score-P Instrumentation

### Configuring Score-P in Jupyter

Set up your Score-P environment with `%env` line magic, e.g.:
```
%env SCOREP_ENABLE_TRACING=1
%env SCOREP_TOTAL_MEMORY=3g
```
For a documentation of Score-P environment variables, see: [Score-P Measurement Configuration](https://perftools.pages.jsc.fz-juelich.de/cicd/scorep/tags/latest/html/scorepmeasurementconfig.html).


`%%scorep_python_binding_arguments`

Set the Score-P Python bindings arguments. For a documentation of arguments, see [Score-P Python bindings](https://github.com/score-p/scorep_binding_python).

![](doc/pythonBindings_setup.png)

`%%marshalling_settings`

Set marshaller/serializer used for persistence and mode of communicating persistence between notebook and subprocess. Currently tested marshallers: `dill`, `cloudpickle`, `parallel_marshall`; modes of communication: `disk`, `memory`. If no arguments were provided, will print current configuration. Use:
```
%%marshalling_settings
MARSHALLER=[dill,cloudpickle]
MODE=[disk,memory]
```

When using persistence in `disk` mode, user can also define directory to which serializer output will be saved with `SCOREP_JUPYTER_PERSISTENCE_DIR` environment variable.
```
%env SCOREP_JUPYTER_PERSISTENCE_DIR=path/to/dir
```
To see the detailed report for marshalling steps - `SCOREP_JUPYTER_MARSHALLING_DETAILED_REPORT` environment variable can be set.
```
%env SCOREP_JUPYTER_MARSHALLING_DETAILED_REPORT=1
```
You can disable visual animations shown during long-running tasks by setting the `SCOREP_JUPYTER_DISABLE_PROCESSING_ANIMATIONS` environment variable.
```
%env SCOREP_JUPYTER_DISABLE_PROCESSING_ANIMATIONS=1
```

`%%execute_with_scorep`

Executes a cell with Score-P, i.e. it calls `python -m scorep <cell code>`

![](doc/instrumentation.gif)



## Multi-Cell Mode
You can also treat multiple cells as one single cell by using the multi cell mode. Therefore you can mark the cells in the order you wish to execute them.


`%%enable_multicellmode`


Enables the multi-cell mode and starts the marking process. Subsequently, "running" cells will not execute them but mark them for execution after `%%finalize_multicellmode`.

`%%finalize_multicellmode`

Stop the marking process and executes all the marked cells.
All the marked cells will be executed with Score-P.

`%%abort_multicellmode`

Stops the marking process, without executing the cells.

**Hints**:
- The `%%execute_with_scorep` command has no effect in the multi cell mode.

- There is no "unmark" command available but you can abort the multicellmode by the `%%abort_multicellmode` command. Start your marking process again if you have marked your cells in the wrong order.

- The `%%enable_multicellmode`, `%%finalize_multicellmode` and `%%abort_multicellmode` commands should be run in an exclusive cell. Additional code in the cell will be ignored.

![](doc/mcm.gif)



## Write Mode

Analogous to [%%writefile](https://ipython.readthedocs.io/en/stable/interactive/magics.html#cellmagic-writefile) command in IPykernel, you can convert a set of cells to the Python script which is to be executed with Score-P Python bindings (with settings and environment described in auxillary bash script).

`%%start_writefile [scriptname]`

Enables the write mode and starts the marking process. Subsequently, "running" cells will not execute them but mark them for writing into a python file after `%%end_writefile`.
`scriptname` is `jupyter_to_script.py` by default.

`%%end_writefile`

Stops the marking process and writes the marked cells in a Python script. Additionally, a bash script will be created for setting the Score-P environment variables, Pyhton bindings arguments and executing the Python script.

**Hints**:
- Recording a cell containing `%%scorep_python_binding_arguments` will add the Score-P Python bindings to the bash script.

- Code of a cell which is not to be executed with Score-P (not inside the multicell mode and without `%%execute_with_scorep`) will be framed with `with scorep.instrumenter.disable()` in the Python script to prevent instrumentation.

- Other cells will be recorded without any changes, except for dropping all magic commands.

- `%%abort_multicellmode` will be ignored in the write mode and will not unmark previous cells from instrumentation.

![](doc/writemode.gif)


# Presentation of Performance Data

To inspect the Score-P collected performance data, use tools as Vampir (Trace) or Cube (Profile).

# Limitations 

## Serialization Type Support
For the execution of a cell, the kernel uses the default IPython kernel. For a cell with Score-P it starts a new Python process. Before starting this process, the state of the previous executed cells is persisted using `dill` (https://github.com/uqfoundation/dill) or `cloudpickle` (https://github.com/cloudpipe/cloudpickle/releases). However:

> `dill` cannot yet pickle these standard types:
> frame, generator, traceback

Similar yields for cloudpickle. Use the `%%marshalling_settings` magic command to switch between both depending on your needs.

## Overhead

When dealing with big data structures, there might be a big runtime overhead at the beginning and the end of a Score-P cell. This is due to additional data saving and loading processes for persistency in the background. However this does not affect the actual user code and the Score-P measurements.

## Logging Configuration
To adjust logging and obtain more detailed output about the behavior of the scorep_jupyter kernel, refer to the `src/logging_config.py` file.

This file contains configuration options for controlling the verbosity, format, and destination of log messages. You can customize it to suit your debugging needs.

# Future Work

The kernel is still under development.
 
PRs are welcome.

# Citing

If you publish some work using the kernel, we would appreciate if you cite one of the following papers:

```
Werner, E., Rygin, A., Gocht-Zech, A., Döbel, S., & Lieber, M. (2024, November).
scorep_jupyter: Performance Data Monitoring, Instrumentation and Visualization for Jupyter Notebooks.
In SC24-W: Workshops of the International Conference for High Performance Computing, Networking, Storage and Analysis (pp. 2003-2011). IEEE.
https://www.doi.org/10.1109/SCW63240.2024.00250
```

or

```
Werner, E., Manjunath, L., Frenzel, J., & Torge, S. (2021, October).
Bridging between Data Science and Performance Analysis: Tracing of Jupyter Notebooks.
In The First International Conference on AI-ML-Systems (pp. 1-7).
https://dl.acm.org/doi/abs/10.1145/3486001.3486249
```

Additionally, please refer to the Score-P Python bindings, published here:

```
Gocht A., Schöne R., Frenzel J. (2021)
Advanced Python Performance Monitoring with Score-P.
In: Mix H., Niethammer C., Zhou H., Nagel W.E., Resch M.M. (eds) Tools for High Performance Computing 2018 / 2019. Springer, Cham.
https://doi.org/10.1007/978-3-030-66057-4_14 
```

or

```
Gocht-Zech A., Grund A. and Schöne R. (2021)
Controlling the Runtime Overhead of Python Monitoring with Selective Instrumentation
In: 2021 IEEE/ACM International Workshop on Programming and Performance Visualization Tools (ProTools)
https://doi.org/10.1109/ProTools54808.2021.00008
``` 

# Contact

elias.werner@tu-dresden.de

# Acknowledgments

This work was supported by the German Federal Ministry of Education and Research (BMBF, SCADS22B) and the Saxon State Ministry for Science, Culture and Tourism (SMWK) by funding the competence center for Big Data and AI "ScaDS.AI Dresden/Leipzig


