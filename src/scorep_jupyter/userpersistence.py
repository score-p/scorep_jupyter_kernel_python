import os
import shutil
import ast
import astunparse
from textwrap import dedent
from pathlib import Path
import uuid
import time
scorep_script_name = "scorep_script.py"
jupyter_dump_dir = "jupyter_dump_"
subprocess_dump_dir = "subprocess_dump_"
full_dump = "full_dump.pkl"
os_env_dump = "os_env_dump.pkl"
sys_path_dump = "sys_path_dump.pkl"
var_dump = "var_dump.pkl"


class PersHelper:
    def __init__(self, serializer='dill'):
        self.jupyter_definitions = ""
        self.jupyter_variables = []
        self.serializer = serializer
        self.subprocess_definitions = ""
        self.subprocess_variables = []
        self.base_path = Path(os.environ['SCOREP_KERNEL_PERSISTENCE_DIR']) / Path("./kernel_persistence/")
        self.paths = {'jupyter':
                          {'os_environ': '', 'sys_path': '', 'var': '', 'comm': ''},
                      'subprocess':
                          {'os_environ': '', 'sys_path': '', 'var': '', 'comm': ''}}

    def preprocess(self):
        uid = str(uuid.uuid4())
        if os.environ['SCOREP_KERNEL_PERSISTENCE_MODE'] == 'DISK':
            os.makedirs(self.base_path)

        for key1 in self.paths:
            dir_path = str(self.base_path / Path(key1))
            for key2 in self.paths[key1]:
                if os.environ['SCOREP_KERNEL_PERSISTENCE_MODE'] == 'DISK':
                    fd_path = dir_path + "_" + key2 + uid
                else:
                    # MEMORY
                    fd_path = "pyperf_" + key1 + "_" + key2 + uid
                self.paths[key1][key2] = fd_path
                if os.environ['SCOREP_KERNEL_PERSISTENCE_MODE'] == 'MEMORY':
                    os.mkfifo(fd_path)
                    #TODO: add a check for working FIFO, return False if not working
                if os.environ['SCOREP_KERNEL_PERSISTENCE_MODE'] == 'DISK':
                    try:
                        open(fd_path, 'a').close()
                    except OSError as e:
                        print(e)
                        print("\n Can not open file, check you file system and paths")
                        return False
        return True

    def postprocess(self):
        """
        Clean up files used for transmitting persistence and running subprocess.
        """
        # for DISK mode
        if os.path.exists(str(self.base_path)):
            shutil.rmtree(str(self.base_path))

        # for MEMORY mode
        for key1 in self.paths:
            for key2 in self.paths[key1]:
                fd_path = self.paths[key1][key2]
                if os.path.exists(fd_path):
                    os.unlink(fd_path)
        if os.path.exists(scorep_script_name):
            os.remove(scorep_script_name)

    def jupyter_dump(self):
        """
        Generate code for kernel ghost cell to dump notebook persistence for subprocess.
        """
        jupyter_dump_ = dedent(f"""\
                               import sys
                               import os
                               import {self.serializer}
                               from scorep_jupyter.userpersistence import pickle_runtime, pickle_variables
                               """)

        jupyter_dump_ += f"pickle_runtime(os.environ, sys.path, '{self.paths['jupyter']['os_environ']}', '{self.paths['jupyter']['sys_path']}', {self.serializer})\n" + \
                         f"pickle_variables({str(self.jupyter_variables)}, globals(), '{self.paths['jupyter']['var']}', {self.serializer})\n"

        if os.environ['SCOREP_KERNEL_PERSISTENCE_MODE'] == 'DISK':
            jupyter_dump_ += f"with open('{self.paths['jupyter']['comm']}', 'wb') as fd:\n" + \
                             '    fd.write(b"READFILE\\n")\n'

        return jupyter_dump_

    def subprocess_wrapper(self, code):
        """
        Extract subprocess user variables and definitions.
        """
        self.parse(code, 'subprocess')

        subprocess_update = dedent(f"""\
                                   import sys
                                   import os
                                   import {self.serializer}
                                   from scorep_jupyter.userpersistence import pickle_runtime, pickle_variables, load_runtime, load_variables, load_globals
                                   """)

        if os.environ['SCOREP_KERNEL_PERSISTENCE_MODE'] == 'DISK':
            subprocess_update += f"with open('{self.paths['jupyter']['comm']}', 'rb') as fd:\n" + \
                                 "    r = fd.readline()\n"

        subprocess_update += f"load_runtime(os.environ, sys.path, '{self.paths['jupyter']['os_environ']}', '{self.paths['jupyter']['sys_path']}', {self.serializer})\n"
        subprocess_update += (self.jupyter_definitions +  f"load_globals(globals(), '{self.paths['jupyter']['var']}', {self.serializer})")

        subprocess_update += ("\n" + code + "\n")

        if os.environ['SCOREP_KERNEL_PERSISTENCE_MODE'] == 'MEMORY':
            # ENDOFOUTPUT will never be printed. It just triggers the blocking read() in the kernel to continue.
            subprocess_update += f"comm_pipe = os.open('{self.paths['subprocess']['comm']}', flags=os.O_WRONLY)\n" + \
                                 "os.write(comm_pipe, b'READ')\n" + \
                                 "print('ENDOFOUTPUT')\n"

        subprocess_update += f"pickle_runtime(os.environ, sys.path, '{self.paths['subprocess']['os_environ']}', '{self.paths['subprocess']['sys_path']}', {self.serializer})\n" + \
                             f"pickle_variables({str(self.subprocess_variables)}, globals(), '{self.paths['subprocess']['var']}', {self.serializer}, True)\n"

        return subprocess_update

    def jupyter_update(self, code):
        """
        Update aggregated storage of definitions and user variables for entire notebook.
        """
        self.parse(code, 'jupyter')
        jupyter_update = dedent(f"""\
                                import sys
                                import os
                                from scorep_jupyter.userpersistence import load_runtime, load_globals
                                """)
        # set scorep_process=True because the data comes from the scorep process
        jupyter_update += f"load_runtime(os.environ, sys.path, '{self.paths['subprocess']['os_environ']}', '{self.paths['subprocess']['sys_path']}', {self.serializer})\n" + \
                          f"load_globals(globals(), '{self.paths['subprocess']['var']}', {self.serializer}, True)\n"
        return jupyter_update

    def parse(self, code, mode):
        """
        Extract user variables names and definitions from the code.
        """
        # Code with magics and shell commands is ignored,
        # unless magics are from "white list" which execute code
        # in "persistent" manner.
        whitelist_prefixes_cell = ['%%prun', '%%capture']
        whitelist_prefixes_line = ['%prun', '%time']

        nomagic_code = ''  # Code to be parsed for user variables
        if not code.startswith(tuple(['%', '!'])):  # No IPython magics and shell commands
            nomagic_code = code
        elif code.startswith(tuple(whitelist_prefixes_cell)):  # Cell magic & executed cell, remove first line
            nomagic_code = code.split("\n", 1)[1]
        elif code.startswith(tuple(whitelist_prefixes_line)):  # Line magic & executed cell, remove first word
            nomagic_code = code.split(" ", 1)[1]
        try:
            user_definitions = extract_definitions(nomagic_code)
            user_variables = extract_variables_names(nomagic_code)
        except SyntaxError as e:
            raise

        if mode == 'subprocess':
            # Parse definitions and user variables from subprocess code before running it.
            self.subprocess_definitions = ""
            self.subprocess_variables.clear()
            self.subprocess_definitions += user_definitions
            self.subprocess_variables.extend(user_variables)
        elif mode == "jupyter" and self.serializer == "cloudpickle":
            # Update aggregated storage of definitions and user variables for entire notebook.
            # Not relevant for dill because of dump_session.
            self.jupyter_definitions += user_definitions
            self.jupyter_variables.extend(user_variables)


def pickle_runtime(os_environ_, sys_path_, os_environ_dump_, sys_path_dump_, serializer):
    # Don't dump environment variables set by Score-P bindings.
    # Will force it to re-initialize instead of calling reset_preload()
    filtered_os_environ_ = {k: v for k, v in os_environ_.items() if not k.startswith('SCOREP_PYTHON_BINDINGS_')}

    fd=os.open(os_environ_dump_, os.O_WRONLY)
    with open(os_environ_dump_, 'wb') as file:
        serializer.dump(filtered_os_environ_, file)
    os.close(fd)

    fd = os.open(sys_path_dump_, os.O_WRONLY)
    with open(sys_path_dump_, 'wb') as file:
        serializer.dump(sys_path_, file)
    os.close(fd)

def pickle_variables(variables_names, globals_, var_dump_, serializer, scorep_process=False):
    # blocking write, to wait for the other process
    fd = os.open(var_dump_, os.O_WRONLY)
    if serializer.__name__ == 'dill' and not scorep_process:
        serializer.dump_session(var_dump_)
    elif serializer.__name__ == 'cloudpickle' or scorep_process:
        user_variables = {k: v for k, v in globals_.items() if k in variables_names}

        for el in user_variables.keys():
            # if possible, exchange class of the object here with the class that is stored for persistence. This is
            # valid since the classes should be the same and this does not affect the objects attribute dictionary
            non_persistent_class = user_variables[el].__class__.__name__
            if non_persistent_class in globals().keys():
                user_variables[el].__class__ = globals()[non_persistent_class]

        with open(var_dump_, 'wb') as file:
            serializer.dump(user_variables, file)
    os.close(fd)


def load_runtime(os_environ_, sys_path_, os_environ_dump_, sys_path_dump_, serializer):
    loaded_os_environ_ = {}
    loaded_sys_path_ = []

    # if os.path.getsize(os_environ_dump_) > 0:
    fd = os.open(os_environ_dump_, os.O_RDONLY)
    with open(os_environ_dump_, 'rb') as file:
        loaded_os_environ_ = serializer.load(file)
    # if os.path.getsize(sys_path_dump_) > 0:
    os.close(fd)

    fd = os.open(sys_path_dump_, os.O_RDONLY)
    with open(sys_path_dump_, 'rb') as file:
        loaded_sys_path_ = serializer.load(file)
    os.close(fd)
    # os_environ_.clear()
    os_environ_.update(loaded_os_environ_)

    # sys_path_.clear()
    sys_path_.extend(loaded_sys_path_)


def load_globals(globals_, var_dump_, serializer, scorep_process=False):
    fd = os.open(var_dump_, os.O_RDONLY)
    if serializer.__name__ == 'dill' and not scorep_process:
        globals_.update(serializer.load_module_asdict(var_dump_))
    elif serializer.__name__ == 'cloudpickle' or scorep_process:
        load_variables(globals_, var_dump_, serializer)
    os.close(fd)

def load_variables(globals_, var_dump_, serializer):
    with open(var_dump_, 'rb') as file:
        globals_.update(serializer.load(file))

def extract_definitions(code):
    """
    Extract imported modules and definitions of classes and functions from the code block.
    """
    # can't use in kernel as import from scorep_jupyter.userpersistence:
    # self-reference error during dill dump of notebook
    root = ast.parse(code)
    definitions = []
    for top_node in ast.iter_child_nodes(root):
        if isinstance(top_node, ast.With):
            for node in ast.iter_child_nodes(top_node):
                if (isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef) or
                        isinstance(node, ast.ClassDef) or isinstance(node, ast.Import) or isinstance(node,
                                                                                                     ast.ImportFrom)):
                    definitions.append(node)
        elif (isinstance(top_node, ast.FunctionDef) or isinstance(top_node, ast.AsyncFunctionDef) or
              isinstance(top_node, ast.ClassDef) or isinstance(top_node, ast.Import) or isinstance(top_node,
                                                                                                   ast.ImportFrom)):
            definitions.append(top_node)

    definitions_string = ""
    for node in definitions:
        definitions_string += astunparse.unparse(node)

    return definitions_string


def extract_variables_names(code):
    """
    Extract user-assigned variables from code.
    Unlike dir(), nothing coming from the imported modules is included.
    Might contain non-variables as well from assignments, which are later filtered out when dumping variables.
    """
    root = ast.parse(code)

    variables = set()
    for node in ast.walk(root):
        # assignment nodes can include attributes, therefore go over all targets and check for attribute nodes
        if isinstance(node, ast.Assign):
            for el in node.targets:
                for target_node in ast.walk(el):
                    if isinstance(target_node, ast.Name):
                        variables.add(target_node.id)
        elif isinstance(node, ast.AnnAssign):
            for target_node in ast.walk(node.target):
                if isinstance(target_node, ast.Name):
                    variables.add(target_node.id)

    return variables
