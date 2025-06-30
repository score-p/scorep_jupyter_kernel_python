import os
import shutil
import ast
import threading
import time
import sys
import types

import astunparse
from pathlib import Path
import uuid
import importlib


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
        self.is_dump_detailed_report = False

    def preprocess(self):

        uid = str(uuid.uuid4())
        if self.mode == "disk":
            os.makedirs(self.base_path)

        fd_path = ""
        for key1 in self.paths:
            dir_path = str(self.base_path / Path(key1))
            for key2 in self.paths[key1]:

                if self.mode == "memory":
                    fd_path = "scorep_jupyter_" + key1 + "_" + key2 + "_" + uid
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
        try:
            marshaller_module = importlib.import_module(marshaller)
        except ImportError:
            return False
        if not hasattr(marshaller_module, "dump") or not hasattr(
            marshaller_module, "load"
        ):
            return False
        return setattr(self, "marshaller", marshaller) or True

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
            "import threading\n"
            f"import {self.marshaller}\n"
            "from scorep_jupyter.userpersistence import dump_runtime, "
            "dump_variables, create_busy_spinner\n"
            "spinner = create_busy_spinner()\n"
            f"if {self.is_dump_detailed_report}:\n"
            "    spinner.start('Dumping runtime environment and sys.path...')"
            "\n"
            f"else:\n"
            "    spinner.start('Loading data...')\n"
            "try:\n"
            "    dump_runtime(os.environ, sys.path,"
            f"    '{self.paths['jupyter']['os_environ']}',"
            f"    '{self.paths['jupyter']['sys_path']}',{self.marshaller})\n"
            f"    if {self.is_dump_detailed_report}:\n"
            "        spinner.report('Dumping runtime environment and "
            "sys.path done.')\n"
            "        spinner.start('Dumping variables...')\n"
            f"    dump_variables({str(self.jupyter_variables)},globals(),"
            f"        '{self.paths['jupyter']['var']}',"
            f"        {self.marshaller})\n"
            f"    if {self.is_dump_detailed_report}:\n"
            "        spinner.stop('Dumping variables done.')\n"
            f"    else:\n"
            "        spinner.stop('Data is loaded.')\n"
            "except KeyboardInterrupt:\n"
            "    spinner.stop('Kernel interrupted.')\n"
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
            "from scorep_jupyter.userpersistence import dump_runtime,"
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
            "from scorep_jupyter.userpersistence import load_runtime, load_variables\n"
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

    def set_dump_report_level(self):
        self.is_dump_detailed_report = int(
            os.getenv("scorep_jupyter_MARSHALLING_DETAILED_REPORT", "0")
        )


def dump_runtime(
    os_environ_, sys_path_, os_environ_dump_, sys_path_dump_, marshaller
):
    # Don't dump environment variables set by Score-P bindings.
    # Will force it to re-initialize instead of calling reset_preload()
    filtered_os_environ_ = {
        k: v for k, v in os_environ_.items() if not k.startswith("SCOREP_")
    }

    with os.fdopen(
        os.open(os_environ_dump_, os.O_WRONLY | os.O_CREAT), "wb"
    ) as file:
        marshaller.dump(filtered_os_environ_, file)

    with os.fdopen(
        os.open(sys_path_dump_, os.O_WRONLY | os.O_CREAT), "wb"
    ) as file:
        marshaller.dump(sys_path_, file)


def dump_variables(variables_names, globals_, var_dump_, marshaller):
    user_variables = {
        k: v
        for k, v in globals_.items()
        if k in variables_names
        and not isinstance(globals_[k], types.ModuleType)
    }

    for el in user_variables.keys():
        # if possible, exchange class of the object here with the class that
        # is stored for persistence. This is valid since the classes should
        # be the same and this does not affect the objects attribute dictionary
        non_persistent_class = user_variables[el].__class__.__name__
        if non_persistent_class in globals().keys():
            user_variables[el].__class__ = globals()[non_persistent_class]

    with (os.fdopen(os.open(var_dump_, os.O_WRONLY | os.O_CREAT), "wb")
          as file):
        marshaller.dump(user_variables, file)


def load_runtime(
    os_environ_, sys_path_, os_environ_dump_, sys_path_dump_, marshaller
):
    loaded_os_environ_ = {}
    loaded_sys_path_ = []

    with os.fdopen(os.open(os_environ_dump_, os.O_RDONLY), "rb") as file:
        loaded_os_environ_ = marshaller.load(file)

    with os.fdopen(os.open(sys_path_dump_, os.O_RDONLY), "rb") as file:
        loaded_sys_path_ = marshaller.load(file)

    # os_environ_.clear()
    os_environ_.update(loaded_os_environ_)

    # sys_path_.clear()
    sys_path_.extend(loaded_sys_path_)


def load_variables(globals_, var_dump_, marshaller):
    with os.fdopen(os.open(var_dump_, os.O_RDONLY), "rb") as file:
        obj = marshaller.load(file)
    globals_.update(obj)


def extract_definitions(code):
    """
    Extract imported modules and definitions of classes and functions from
    the code block.
    """
    # can't use in kernel as import from scorep_jupyter.userpersistence:
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
    lines = code.splitlines(True)
    scorep_env = []
    
    # Cell magics that should skip entire cell content for persistence
    non_persistent_cell_magics = ["%%bash"]  # Non-Python content
    # Cell magics that should keep Python content but skip magic line
    python_cell_magics = ["%%prun", "%%capture"]
    whitelist_prefixes_line = ["%prun", "%time"]
    
    # Check if this is a cell magic
    if lines and lines[0].strip().startswith("%%"):
        first_line = lines[0].strip()
        if any(first_line.startswith(prefix) for prefix in non_persistent_cell_magics):
            # For non-Python cell magics like %%bash
            # Skip the entire cell content for persistence
            return scorep_env, ""
        elif any(first_line.startswith(prefix) for prefix in python_cell_magics):
            # For Python cell magics like %%prun, %%capture
            # Skip only the magic line, keep the Python content for persistence
            filtered_lines = lines[1:]  # Skip first line (the magic)
            return scorep_env, "".join(filtered_lines)
    
    # Process line by line for non-cell magics or non-whitelisted cell magics
    filtered_lines = []
    
    for line in lines:
        stripped_line = line.strip()
        
        # Keep empty lines and comments
        if not stripped_line or stripped_line.startswith("#"):
            filtered_lines.append(line)
            
        # Handle %env specially
        elif stripped_line.startswith("%env"):
            env_var = stripped_line.split(" ", 1)[1]
            if "=" in env_var:
                if env_var.startswith("SCOREP"):
                    scorep_env.append("export " + env_var + "\n")
                else:
                    key, val = env_var.split("=", 1)
                    filtered_lines.append(f'os.environ["{key}"]="{val}"\n')
            else:
                key = env_var
                filtered_lines.append(f"print(\"env: {key}=os.environ['{key}']\")\n")
                
        # Handle whitelisted line magics - keep the command part
        elif any(stripped_line.startswith(prefix) for prefix in whitelist_prefixes_line):
            parts = line.split(" ", 1)
            if len(parts) > 1:
                filtered_lines.append(parts[1])
                
        # Remove all other magic commands and shell commands
        elif stripped_line.startswith("%") or stripped_line.startswith("!"):
            continue
            
        # Keep regular Python code
        else:
            filtered_lines.append(line)
    
    nomagic_code = "".join(filtered_lines)
    return scorep_env, nomagic_code


class BaseSpinner:
    def __init__(self, lock=None):
        pass

    def _spinner_task(self):
        pass

    def start(self, working_message="Working..."):
        pass

    def report(self, done_message="Done."):
        pass

    def stop(self, done_message="Done."):
        pass


class BusySpinner(BaseSpinner):
    def __init__(self, lock=None):
        super().__init__(lock)
        self._lock = lock or threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._spinner_task)
        self.working_message = ""
        self.done_message = ""

    def _spinner_task(self):
        spinner_chars = "|/-\\"
        idx = 0
        while not self._stop_event.is_set():
            with self._lock:
                sys.stdout.write(
                    f"\r{self.working_message} "
                    f"{spinner_chars[idx % len(spinner_chars)]}"
                )
                sys.stdout.flush()
            time.sleep(0.1)
            idx += 1

    def start(self, working_message="Working..."):
        self.working_message = working_message
        if not self._thread.is_alive():
            self._thread.start()

    def report(self, done_message="Done."):
        with self._lock:
            sys.stdout.write(
                f"\r{done_message}{' ' * len(self.working_message)}\n"
            )
            sys.stdout.flush()

    def stop(self, done_message="Done."):
        self.report(done_message)
        self._stop_event.set()
        self._thread.join()


def create_busy_spinner(lock=None):
    is_enabled = os.getenv("scorep_jupyter_DISABLE_PROCESSING_ANIMATIONS") != "1"
    if is_enabled:
        return BusySpinner(lock)
    else:
        return BaseSpinner(lock)
