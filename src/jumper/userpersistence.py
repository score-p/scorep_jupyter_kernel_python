import os
import shutil
import ast
import astunparse
from pathlib import Path
import uuid

import dill

scorep_script_name = "scorep_script.py"


class PersHelper:
    def __init__(self, marshaller="dill", mode="memory"):
        self.jupyter_definitions = ""
        self.jupyter_variables = []
        self.marshaller = marshaller
        self.mode = mode
        self.subprocess_definitions = ""
        self.subprocess_variables = []
        self.base_path = Path(
            os.environ["SCOREP_KERNEL_PERSISTENCE_DIR"]
        ) / Path("./kernel_persistence/")
        self.paths = {
            "jupyter": {"os_environ": "", "sys_path": "", "var": ""},
            "subprocess": {"os_environ": "", "sys_path": "", "var": ""},
        }

    def preprocess(self):

        uid = str(uuid.uuid4())
        if self.mode == "disk":
            os.makedirs(self.base_path)

        fd_path = ""
        for key1 in self.paths:
            dir_path = str(self.base_path / Path(key1))
            for key2 in self.paths[key1]:

                if self.mode == "memory":
                    fd_path = "jumper_" + key1 + "_" + key2 + "_" + uid
                elif self.mode == "disk":
                    fd_path = dir_path + "_" + key2 + "_" + uid

                self.paths[key1][key2] = fd_path

                try:
                    if self.mode == "memory":
                        os.mkfifo(fd_path)
                    elif self.mode == "disk":
                        open(fd_path, "a").close()
                except PermissionError:
                    print(
                        f"Permission denied: Cannot create pipe/file at"
                        f" {fd_path}"
                    )
                    return False
                except FileExistsError:
                    print(f"Pipe/file already exists at {fd_path}")
                    return False
                except OSError as e:
                    print(
                        f"Failed to create pipe/file due to an OS error: {e}"
                    )
                    return False
        return True

    def postprocess(self):
        """
        Clean up files used for transmitting persistence and running subprocess
        """
        if self.mode == "memory":
            for key1 in self.paths:
                for key2 in self.paths[key1]:
                    fd_path = self.paths[key1][key2]
                    if os.path.exists(fd_path):
                        os.unlink(fd_path)
        elif self.mode == "disk":
            if os.path.exists(str(self.base_path)):
                shutil.rmtree(str(self.base_path))

        if os.path.exists(scorep_script_name):
            os.remove(scorep_script_name)

    def set_marshaller(self, marshaller):
        # TODO: valid marshallers should not be configured in code but via an
        # environment variable
        valid_marshallers = {"dill", "cloudpickle", "parallel_marshall"}
        return marshaller in valid_marshallers and (
            setattr(self, "marshaller", marshaller) or True
        )

    def set_mode(self, mode):
        valid_modes = {"disk", "memory"}
        return mode in valid_modes and (setattr(self, "mode", mode) or True)

    def jupyter_dump(self):
        """
        Generate code for kernel ghost cell to dump notebook persistence for
        subprocess.
        """
        jupyter_dump_ = (
            "import sys\n"
            "import os\n"
            f"import {self.marshaller}\n"
            "from jumper.userpersistence import dump_runtime,dump_variables\n"
            "dump_runtime(os.environ, sys.path,"
            f"'{self.paths['jupyter']['os_environ']}',"
            f"'{self.paths['jupyter']['sys_path']}',{self.marshaller})\n"
            f"dump_variables({str(self.jupyter_variables)},globals(),"
            f"'{self.paths['jupyter']['var']}',"
            f"{self.marshaller})"
        )

        return jupyter_dump_

    def subprocess_wrapper(self, code):
        """
        Extract subprocess user variables and definitions.
        """
        self.parse(code, "subprocess")
        subprocess_code = (
            "import sys\n"
            "import os\n"
            f"import {self.marshaller}\n"
            "from jumper.userpersistence import dump_runtime,"
            "dump_variables, load_runtime, load_variables\n"
            "load_runtime(os.environ, sys.path,"
            f"'{self.paths['jupyter']['os_environ']}',"
            f"'{self.paths['jupyter']['sys_path']}',{self.marshaller})\n"
            f"{self.jupyter_definitions}"
            f"load_variables(globals(),'{self.paths['jupyter']['var']}',"
            f"{self.marshaller})\n"
            f"{code}\n"
        )

        # In memory mode, signal subprocess output observer in kernel to
        # terminate by closing the streams
        # TODO: Missing possible stderr from dump_runtime and dump_variables
        if self.mode == "memory":
            subprocess_code += (
                "sys.stdout.flush()\n"
                "sys.stderr.flush()\n"
                "os.close(sys.stdout.fileno())\n"
                "os.close(sys.stderr.fileno())\n"
            )

        subprocess_code += (
            "dump_runtime(os.environ, sys.path,"
            f"'{self.paths['subprocess']['os_environ']}',"
            f"'{self.paths['subprocess']['sys_path']}',"
            f"{self.marshaller})\n"
            f"dump_variables({str(self.subprocess_variables)},"
            f"globals(),'{self.paths['subprocess']['var']}',"
            f"{self.marshaller})\n"
        )

        return subprocess_code

    def jupyter_update(self, code):
        """
        Update aggregated storage of definitions and user variables for
        entire notebook.
        """
        self.parse(code, "jupyter")
        jupyter_update = (
            "import sys\n"
            "import os\n"
            "from jumper.userpersistence import load_runtime, load_variables\n"
            f"load_runtime(os.environ, sys.path,"
            f"'{self.paths['subprocess']['os_environ']}',"
            f"'{self.paths['subprocess']['sys_path']}',{self.marshaller})\n"
            f"{self.jupyter_definitions}"
            f"load_variables(globals(),'{self.paths['subprocess']['var']}', "
            f"{self.marshaller})\n"
        )

        return jupyter_update

    def parse(self, code, mode):
        """
        Extract user variables names and definitions from the code.
        """
        try:
            user_definitions = extract_definitions(code)
            user_variables = extract_variables_names(code)
        except SyntaxError as e:
            raise e

        if mode == "subprocess":
            # Parse definitions and user variables from subprocess code
            # before running it.
            self.subprocess_definitions = ""
            self.subprocess_variables.clear()
            self.subprocess_definitions += user_definitions
            self.subprocess_variables.extend(user_variables)
        elif mode == "jupyter":
            # Update aggregated storage of definitions and user variables
            # for entire notebook.
            self.jupyter_definitions += user_definitions
            self.jupyter_variables.extend(user_variables)


def dump_runtime(
    os_environ_, sys_path_, os_environ_dump_, sys_path_dump_, marshaller
):
    # Don't dump environment variables set by Score-P bindings.
    # Will force it to re-initialize instead of calling reset_preload()
    filtered_os_environ_ = {
        k: v
        for k, v in os_environ_.items()
        if not k.startswith("SCOREP_PYTHON_BINDINGS_")
    }

    with os.fdopen(os.open(os_environ_dump_, os.O_WRONLY | os.O_CREAT), 'wb') as file:
        dill.dump(filtered_os_environ_, file)

    with os.fdopen(os.open(sys_path_dump_, os.O_WRONLY | os.O_CREAT), 'wb') as file:
        dill.dump(sys_path_, file)


def dump_variables(variables_names, globals_, var_dump_, marshaller):
    user_variables = {
        k: v for k, v in globals_.items() if k in variables_names
    }

    for el in user_variables.keys():
        # if possible, exchange class of the object here with the class that
        # is stored for persistence. This is valid since the classes should
        # be the same and this does not affect the objects attribute dictionary
        non_persistent_class = user_variables[el].__class__.__name__
        if non_persistent_class in globals().keys():
            user_variables[el].__class__ = globals()[non_persistent_class]

    with os.fdopen(os.open(var_dump_, os.O_WRONLY | os.O_CREAT), 'wb') as file:
        marshaller.dump(user_variables, file)


def load_runtime(
    os_environ_, sys_path_, os_environ_dump_, sys_path_dump_, marshaller
):
    loaded_os_environ_ = {}
    loaded_sys_path_ = []

    with os.fdopen(os.open(os_environ_dump_, os.O_RDONLY), 'rb') as file:
        loaded_os_environ_ = dill.load(file)

    with os.fdopen(os.open(sys_path_dump_, os.O_RDONLY), 'rb') as file:
        loaded_sys_path_ = dill.load(file)

    # os_environ_.clear()
    os_environ_.update(loaded_os_environ_)

    # sys_path_.clear()
    sys_path_.extend(loaded_sys_path_)


def load_variables(globals_, var_dump_, marshaller):
    with os.fdopen(os.open(var_dump_, os.O_RDONLY), 'rb') as file:
        obj = marshaller.load(file)
    globals_.update(obj)


def extract_definitions(code):
    """
    Extract imported modules and definitions of classes and functions from
    the code block.
    """
    # can't use in kernel as import from jumper.userpersistence:
    # self-reference error during dill dump of notebook
    root = ast.parse(code)
    definitions = []
    for top_node in ast.iter_child_nodes(root):
        if isinstance(top_node, ast.With):
            for node in ast.iter_child_nodes(top_node):
                if (
                    isinstance(node, ast.FunctionDef)
                    or isinstance(node, ast.AsyncFunctionDef)
                    or isinstance(node, ast.ClassDef)
                    or isinstance(node, ast.Import)
                    or isinstance(node, ast.ImportFrom)
                ):
                    definitions.append(node)
        elif (
            isinstance(top_node, ast.FunctionDef)
            or isinstance(top_node, ast.AsyncFunctionDef)
            or isinstance(top_node, ast.ClassDef)
            or isinstance(top_node, ast.Import)
            or isinstance(top_node, ast.ImportFrom)
        ):
            definitions.append(top_node)

    definitions_string = ""
    for node in definitions:
        definitions_string += astunparse.unparse(node)

    return definitions_string


def extract_variables_names(code):
    """
    Extract user-assigned variables from code. Unlike dir(), nothing coming
    from the imported modules is included. Might contain non-variables as
    well from assignments, which are later filtered out when dumping variables.
    """
    root = ast.parse(code)

    variables = set()
    for node in ast.walk(root):
        # assignment nodes can include attributes, therefore go over all
        # targets and check for attribute nodes
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


def magics_cleanup(code):
    """
    Remove IPython magics from the code. Return only "persistent" code,
    which is executed with whitelisted magics.
    """
    whitelist_prefixes_cell = ["%%prun", "%%capture"]
    whitelist_prefixes_line = ["%prun", "%time"]

    nomagic_code = ""  # Code to be parsed for user variables
    if not code.startswith(
        tuple(["%", "!"])
    ):  # No IPython magics and shell commands
        nomagic_code = code
    elif code.startswith(
        tuple(whitelist_prefixes_cell)
    ):  # Cell magic & executed cell, remove first line
        nomagic_code = code.split("\n", 1)[1]
    elif code.startswith(
        tuple(whitelist_prefixes_line)
    ):  # Line magic & executed cell, remove first word
        nomagic_code = code.split(" ", 1)[1]
    return nomagic_code
