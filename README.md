# The Score-P Python Jupyter Kernel
This is the Score-P Python Kernel that enables you to execute Jupyter Notebooks with Score-P.

The kernel supports the usual jupyter interactivity between cells but with some limitations (see "General Limitations").

## Installation

* Check out the repository and use the install script: `sh install.sh`
* The script creates a virtual environment in the users home directory, installs the kernel 
modules in it and installs the kernel for Jupyter in the ordinary user environment 
~/.local/share/jupyter/kernels
* Note that Python should be available on your machine
* Installing more packages in the created virtual environment is on you


## Dependencies
In order to use the Score-P Python Kernel, Score-P has to be installed properly.

The kernel is based on the Score-P Python binding. For further information see https://github.com/score-p/scorep_binding_python
When using the install script, the most recent pip version of the binding is installed.

# Usage

## Configuring Score-P in Jupyter
You can set up your Score-P environment by executing a cell that starts with the %%scorep_env magic command.

You can set the Score-P Python binding arguments by executing a cell that starts with %%scorep_python_binding_arguments.

## Executing Cells 
Cells that should be executed with Score-P have to be marked with %%execute_with_scorep in the first line. Cells without that command are executed as ordinary Python processes.

### Multi Cell Mode
You can also treat multiple cells as one single cell by using the multi cell mode.

Therefore you can mark the cells in the order you wish to execute them. Start the marking process by a cell that starts with the %%enable_multicellmode command.
Now mark your cells by running them. Note that the cells will not be executed at this point but will be marked for later execution.
You can stop the marking and execute all the marked cells by running a cell that starts with %%finalize_multicellmode command.
This will execute all the marked cells orderly with Score-P. Note that the %%execute_with_scorep command has no effect in the multi cell mode.

There is no "unmark" command available but you can abort the multicellmode by the %%abort_multicellmode command. Start your marking process again if you have marked your cells in the wrong order.

The %%enable_multicellmode, %%finalize_multicellmode and %%abort_multicellmode commands should be run in an exclusive cell. Additional code in the cell will be ignored.

## Presentation of Performance Data

To inspect the collected performance data, use tools as Vampir (Trace) or Cube (Profile).

## Future Work

The kernel is still under development. The following is on the agenda:
 
 - the output of the inner python process needs to be handled as a stream, currently you receive all the feedback at the end of the process at once
 - performance improvements (use json or file based database for persistency instead of pickle/shelve might improve runtime)
 
PRs are welcome.

## General Limitations 

* The kernel does not support jupyter magic, since the Score-P Python binding does not support it.

For the execution of a cell, the kernel starts a new Python process either with Score-P or standalone. The kernel handles persistency between these processes on its own. Therefore it uses pickle/shelve and additional techniques. However this comes with the following drawbacks:

* when dealing with big data structures, there might be a big runtime overhead at the beginning and the end of a cell. This is due to additional data saving and loading processes for persistency in the background. However this does not affect the actual user code and the Score-P measurements.
* Pickle/Shelve can not handle each kind ob Python object (e.g. file handles, network connections,...). Thus, they can not be shared between cells and your notebook might not work.
* Pickle/Shelve does not store class information but gives a reference to the class when storing a class instance. Thus, overwriting classes differs from the ordinary Python way. E.g. if you define a class and an object of this class in one cell and overwrite the class in a different cell, the defined object will also be changed. So please avoid class overwriting.

## Contact

*  elias.werner@tu-dresden.de


