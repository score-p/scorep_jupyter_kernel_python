import os
import shutil
import ast
import astunparse
from textwrap import dedent
from pathlib import Path

scorep_script_name = "scorep_script.py"
jupyter_dump_dir = "jupyter_dump/"
subprocess_dump_dir = "subprocess_dump/"
main_dump = "main_dump.pkl"
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
        os.environ['SCOREP_KERNEL_PERSISTENCE_DIR'] = './'
    
    def get_full_jupyter_dump_dir(self):
        """
        Get the full path for jupyer dump
        """
        return str(Path(os.environ['SCOREP_KERNEL_PERSISTENCE_DIR']) / Path(jupyter_dump_dir))

    def get_full_subprocess_dump_dir(self):
        """
        Get the full path for subprocess dump
        """
        return str(Path(os.environ['SCOREP_KERNEL_PERSISTENCE_DIR']) / Path(subprocess_dump_dir))

    # FIXME
    def pers_cleanup(self):
        """
        Clean up files used for transmitting persistence and running subprocess.
        """
        full_jupyter_dump_dir = self.get_full_jupyter_dump_dir()
        full_subprocess_dump_dir = self.get_full_subprocess_dump_dir()
        for pers_path in [scorep_script_name, 
                          *[dirname + filename for dirname in [full_jupyter_dump_dir, full_subprocess_dump_dir]
                          for filename in [main_dump, os_env_dump, sys_path_dump, var_dump]]]:
            if os.path.exists(pers_path):
                if os.path.isfile(pers_path):
                    os.remove(pers_path)
                elif os.path.isdir(pers_path):
                    shutil.rmtree(pers_path)
        
    def jupyter_dump(self):
        """
        Generate code for kernel ghost cell to dump notebook persistence for subprocess.
        """
        full_jupyter_dump_dir = self.get_full_jupyter_dump_dir()
        if not os.path.exists(full_jupyter_dump_dir):
            os.makedirs(full_jupyter_dump_dir)

        jupyter_dump_ = dedent(f"""\
                               import sys
                               import os
                               import {self.serializer}
                               from scorep_jupyter.userpersistence import pickle_runtime, pickle_variables
                               pickle_runtime(os.environ, sys.path, '{full_jupyter_dump_dir}', {self.serializer})
                               """)
        if self.serializer == 'dill':
            return jupyter_dump_ + f"dill.dump_session('{full_jupyter_dump_dir + main_dump}')"
        elif self.serializer == 'cloudpickle':
            return jupyter_dump_ + f"pickle_variables({str(self.jupyter_variables)}, globals(), '{full_jupyter_dump_dir}', {self.serializer})"
        
    def subprocess_wrapper(self, code):
        """
        Extract subprocess user variables and definitions.
        """
        self.parse(code, 'subprocess')

        full_jupyter_dump_dir = self.get_full_jupyter_dump_dir()
        full_subprocess_dump_dir = self.get_full_subprocess_dump_dir()
        if not os.path.exists(full_subprocess_dump_dir):
            os.makedirs(full_subprocess_dump_dir)
        subprocess_update = dedent(f"""\
                                   import sys
                                   import os
                                   import {self.serializer}
                                   from scorep_jupyter.userpersistence import pickle_runtime, pickle_variables, load_runtime, load_variables
                                   load_runtime(os.environ, sys.path, '{full_jupyter_dump_dir}', {self.serializer})
                                   """)
        if self.serializer == 'dill':
            subprocess_update += f"globals().update(dill.load_module_asdict('{full_jupyter_dump_dir + main_dump}'))"
        elif self.serializer == 'cloudpickle':
           subprocess_update += (self.jupyter_definitions + f"load_variables(globals(), '{full_jupyter_dump_dir}', {self.serializer})")
        return subprocess_update + "\n" + code + \
            dedent(f"""
                   pickle_runtime(os.environ, sys.path, '{full_subprocess_dump_dir}', {self.serializer})
                   pickle_variables({str(self.subprocess_variables)}, globals(), '{full_subprocess_dump_dir}', {self.serializer})
                   """)
    
    def jupyter_update(self, code):
        """
        Update aggregated storage of definitions and user variables for entire notebook.
        """
        self.parse(code, 'jupyter')

        full_subprocess_dump_dir = self.get_full_subprocess_dump_dir()
        return dedent(f"""\
                      import sys
                      import os
                      from scorep_jupyter.userpersistence import load_runtime, load_variables
                      load_runtime(os.environ, sys.path, '{full_subprocess_dump_dir}', {self.serializer})
                      {self.subprocess_definitions}
                      load_variables(globals(), '{full_subprocess_dump_dir}', {self.serializer})
                      """)

    def parse(self, code, mode):
        """
        Extract user variables names and definitions from the code.
        """
        # Code with magics and shell commands is ignored,
        # unless magics are from "white list" which execute code
        # in "persistent" manner.
        whitelist_prefixes_cell = ['%%prun', '%%capture']
        whitelist_prefixes_line = ['%prun', '%time']

        nomagic_code = '' # Code to be parsed for user variables
        if not code.startswith(tuple(['%', '!'])): # No IPython magics and shell commands
            nomagic_code = code
        elif code.startswith(tuple(whitelist_prefixes_cell)): # Cell magic & executed cell, remove first line
            nomagic_code = code.split("\n", 1)[1]
        elif code.startswith(tuple(whitelist_prefixes_line)): # Line magic & executed cell, remove first word
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

def pickle_runtime(os_environ_, sys_path_, dump_dir, serializer):
    os_env_dump_ = dump_dir + os_env_dump
    sys_path_dump_ = dump_dir + sys_path_dump

    # Don't dump environment variables set by Score-P bindings.
    # Will force it to re-initialize instead of calling reset_preload()
    filtered_os_environ_ = {k: v for k, v in os_environ_.items() if not k.startswith('SCOREP_PYTHON_BINDINGS_')}
    with open(os_env_dump_, 'wb+') as file:
        serializer.dump(filtered_os_environ_, file)
    with open(sys_path_dump_, 'wb+') as file:
        serializer.dump(sys_path_, file)
    
def pickle_variables(variables_names, globals_, dump_dir, serializer):
    var_dump_ = dump_dir + var_dump
    user_variables = {k: v for k, v in globals_.items() if k in variables_names}
    
    for el in user_variables.keys():
        # if possible, exchange class of the object here with the class that is stored for persistence. This is
        # valid since the classes should be the same and this does not affect the objects attribute dictionary
        non_persistent_class = user_variables[el].__class__.__name__
        if non_persistent_class in globals().keys():
            user_variables[el].__class__ = globals()[non_persistent_class]

    with open(var_dump_, 'wb+') as file:
        serializer.dump(user_variables, file)

def load_runtime(os_environ_, sys_path_, dump_dir, serializer):
    os_env_dump_ = dump_dir + os_env_dump
    sys_path_dump_ = dump_dir + sys_path_dump

    loaded_os_environ_ = {}
    loaded_sys_path_ = []

    if os.path.getsize(os_env_dump_) > 0:
        with open(os_env_dump_, 'rb') as file:
            loaded_os_environ_ = serializer.load(file)
    if os.path.getsize(sys_path_dump_) > 0:
        with open(sys_path_dump_, 'rb') as file:
            loaded_sys_path_ = serializer.load(file)
    
    #os_environ_.clear()
    os_environ_.update(loaded_os_environ_)

    #sys_path_.clear()
    sys_path_.extend(loaded_sys_path_)

def load_variables(globals_, dump_dir, serializer):
    var_dump_ = dump_dir + var_dump
    if os.path.getsize(var_dump_) > 0:
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
