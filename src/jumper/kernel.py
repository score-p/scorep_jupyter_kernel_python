import datetime
import json
import os
import re
import subprocess
import sys
import time
import shutil

from enum import Enum
from textwrap import dedent
from ipykernel.ipkernel import IPythonKernel
from jumper.userpersistence import PersHelper, scorep_script_name
from jumper.userpersistence import magics_cleanup
import importlib

# import jumper.multinode_monitor.slurm_monitor as slurm_monitor

PYTHON_EXECUTABLE = sys.executable
READ_CHUNK_SIZE = 8
userpersistence_token = "jumper.userpersistence"
jupyter_dump = "jupyter_dump.pkl"
subprocess_dump = "subprocess_dump.pkl"


# kernel modes
class KernelMode(Enum):
    DEFAULT = (0, "default")
    MULTICELL = (1, "multicell")
    WRITEFILE = (2, "writefile")

    def __str__(self):
        return self.value[1]


class JumperKernel(IPythonKernel):
    implementation = "Python and Score-P"
    implementation_version = "1.0"
    language = "python"
    language_version = "3.8"
    language_info = {
        "name": "python",
        "mimetype": "text/plain",
        "file_extension": ".py",
    }
    banner = "Jupyter kernel for performance engineering."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # setting the matplotlib backend
        super().shell.run_cell(
            "%matplotlib inline", silent=True, store_history=False
        )
        super().shell.run_cell(
            "%matplotlib widget", silent=True, store_history=False
        )

        # TODO: timeit, python, ...? do not save variables to globals()
        self.whitelist_prefixes_cell = [
            "%%prun",
            "%%timeit",
            "%%capture",
            "%%python",
            "%%pypy",
        ]
        self.whitelist_prefixes_line = ["%prun", "%time"]

        self.blacklist_prefixes = ["%lsmagic"]

        self.scorep_binding_args = []

        os.environ["SCOREP_KERNEL_PERSISTENCE_DIR"] = "./"
        self.pershelper = PersHelper("dill", "memory")

        self.mode = KernelMode.DEFAULT

        self.multicell_cellcount = -1
        self.multicell_code = "import time\n"
        self.multicell_code_history = ""

        self.writefile_base_name = "jupyter_to_script"
        self.writefile_bash_name = ""
        self.writefile_python_name = ""
        self.writefile_scorep_env = []
        self.writefile_scorep_binding_args = []
        self.writefile_multicell = False

        self.scorep_available_ = shutil.which("scorep")
        self.scorep_python_available_ = True
        try:
            importlib.import_module("scorep")
        except ModuleNotFoundError:
            self.scorep_python_available_ = False

    def cell_output(self, string, stream="stdout"):
        """
        Display string as cell output.
        """
        stream_content = {"name": stream, "text": string}
        self.send_response(self.iopub_socket, "stream", stream_content)

    def standard_reply(self):
        self.shell.execution_count += 1
        return {
            "status": "ok",
            "execution_count": self.shell.execution_count - 1,
            "payload": [],
            "user_expressions": {},
        }

    def scorep_not_available(self):
        if not self.scorep_available_:
            self.cell_output("Score-P not available, cell ignored.", "stderr")
            return self.standard_reply()
        if not self.scorep_python_available_:
            self.cell_output(
                "Score-P Python not available, cell ignored. "
                "Consider installing it via `pip install scorep`",
                "stderr",
            )
            return self.standard_reply()
        else:
            return None

    def marshaller_settings(self, code):
        """
        Switch serializer/marshalling backend used for persistence in kernel.
        """
        if self.mode == KernelMode.DEFAULT:
            # Clean files/pipes before switching
            self.pershelper.postprocess()

            # Safely extract content after the magic command
            code_parts = code.split("\n", 1)
            content = code_parts[1] if len(code_parts) > 1 else ""

            marshaller_match = re.search(
                r"MARSHALLER=([\w-]+)", content
            )
            mode_match = re.search(r"MODE=([\w-]+)", content)
            marshaller = (
                marshaller_match.group(1) if marshaller_match else None
            )
            mode = mode_match.group(1) if mode_match else None

            if marshaller:
                if not self.pershelper.set_marshaller(marshaller):
                    self.cell_output(
                        f"Marshaller '{marshaller}' is not available"
                        f" or compatible, "
                        f"kernel will use '{self.pershelper.marshaller}'.",
                        "stderr",
                    )
            if mode:
                if not self.pershelper.set_mode(mode):
                    self.cell_output(
                        f"Marshalling mode '{mode}' is not recognized, "
                        f"kernel will use '{self.pershelper.mode}'.",
                        "stderr",
                    )

            self.cell_output(
                f"Kernel uses '{self.pershelper.marshaller}' marshaller in "
                f"'{self.pershelper.mode}' mode."
            )
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def set_scorep_pythonargs(self, code):
        """
        Read and record Score-P Python binding arguments from the cell.
        """
        if self.mode == KernelMode.DEFAULT:
            self.scorep_binding_args = (
                code.split("\n")[1].replace(" ", "\n").split("\n")
            )
            self.cell_output(
                "Score-P Python binding arguments set successfully: "
                + str(self.scorep_binding_args)
            )
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_scorep_binding_args = (
                code.split("\n")[1].replace(" ", "\n").split("\n")
            )
            self.cell_output("Score-P bindings arguments recorded.")
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def enable_multicellmode(self):
        """
        Start multicell mode.
        """
        if self.mode == KernelMode.DEFAULT:
            self.mode = KernelMode.MULTICELL
            self.cell_output(
                "Multicell mode enabled. The following cells will be marked "
                "for instrumented execution."
            )
        elif self.mode == KernelMode.MULTICELL:
            self.cell_output(
                f"KernelWarning: {KernelMode.MULTICELL} mode has already"
                f" been enabled",
                "stderr",
            )
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_multicell = True
        return self.standard_reply()

    def append_multicellmode(self, code):
        """
        Append cell to multicell mode sequence.
        """
        if self.mode == KernelMode.MULTICELL:
            self.multicell_cellcount += 1
            max_line_len = max(len(line) for line in code.split("\n"))
            self.multicell_code += (
                f"print('Executing cell {self.multicell_cellcount}')\n"
                + f"print('''{code}''')\n"
                + f"print('-' * {max_line_len})\n"
                + "print('MCM_TS'+str(time.time()))\n"
                + f"{code}\n"
                + "print('''\n''')\n"
            )
            self.multicell_code_history += (
                f"###User code for sub cell {self.multicell_cellcount}\n"
                + f"print('''{code}''')\n"
            )
            self.cell_output(
                f"Cell marked for multicell mode. It will be executed at "
                f"position {self.multicell_cellcount}"
            )
        return self.standard_reply()

    def abort_multicellmode(self):
        """
        Cancel multicell mode.
        """
        if self.mode == KernelMode.MULTICELL:
            self.mode = KernelMode.DEFAULT
            self.multicell_code = "import time\n"
            self.multicell_code_history = ""
            self.multicell_cellcount = -1
            self.cell_output("Multicell mode aborted.")
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def start_writefile(self, code):
        """
        Start recording the notebook as a Python script. Custom file name
        can be defined as an argument of the magic command.
        """
        # TODO: Check for os path existence
        # TODO: Edge cases processing, similar to multicellmode
        if self.mode == KernelMode.DEFAULT:
            self.mode = KernelMode.WRITEFILE
            # init writefile_scorep_env and python binding args
            self.writefile_scorep_env = []
            self.writefile_scorep_binding_args = []
            writefile_cmd = code.split("\n")[0].split(" ")
            if len(writefile_cmd) > 1:
                if writefile_cmd[1].endswith(".py"):
                    self.writefile_base_name = writefile_cmd[1][:-3]
                else:
                    self.writefile_base_name = writefile_cmd[1]
            self.writefile_bash_name = (
                os.path.realpath("")
                + "/"
                + self.writefile_base_name
                + "_run.sh"
            )
            self.writefile_python_name = (
                os.path.realpath("") + "/" + self.writefile_base_name + ".py"
            )

            with os.fdopen(
                os.open(
                    self.writefile_bash_name,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                ),
                "w",
            ) as bash_script:
                bash_script.write(
                    dedent(
                        f"""
                        # This bash script is generated automatically to run
                        # Jupyter Notebook -> Python script conversion
                        # by JUmPER kernel
                        # {self.writefile_python_name}
                        # !/bin/bash
                        """
                    )
                )
            with os.fdopen(
                os.open(
                    self.writefile_python_name,
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                ),
                "w",
            ) as python_script:
                python_script.write(
                    dedent(
                        f"""
                        # This is the automatic conversion of
                        # Jupyter Notebook -> Python script by JUmPER kernel.
                        # Code corresponding to the cells not marked for
                        # Score-P instrumentation is framed by
                        # "with scorep.instrumenter.disable()
                        # The script can be run with proper settings using
                        # bash script {self.writefile_bash_name}
                        import scorep
                        import os
                        """
                    )
                )
            self.cell_output(
                "Started converting to Python script. See files:\n"
                + self.writefile_bash_name
                + "\n"
                + self.writefile_python_name
                + "\n"
            )
        elif self.mode == KernelMode.WRITEFILE:
            self.cell_output(
                f"KernelWarning: {KernelMode.WRITEFILE} mode has already"
                f" been enabled",
                "stderr",
            )
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def append_writefile(self, code, explicit_scorep):
        """
        Append cell to writefile.
        """
        if self.mode == KernelMode.WRITEFILE:
            if not code:
                pass
            elif explicit_scorep or self.writefile_multicell:
                with os.fdopen(
                    os.open(
                        self.writefile_python_name, os.O_WRONLY | os.O_APPEND
                    ),
                    "a",
                ) as python_script:
                    python_script.write(code + "\n")
                self.cell_output(
                    "Python commands with instrumentation recorded."
                )
            else:
                with os.fdopen(
                    os.open(
                        self.writefile_python_name, os.O_WRONLY | os.O_APPEND
                    ),
                    "a",
                ) as python_script:
                    code = "".join(
                        ["    " + line + "\n" for line in code.split("\n")]
                    )
                    python_script.write(
                        "with scorep.instrumenter.disable():\n" + code + "\n"
                    )
                self.cell_output(
                    "Python commands without instrumentation recorded."
                )
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def end_writefile(self):
        """
        Finish recording the notebook as a Python script.
        """
        # TODO: check for os path existence
        if self.mode == KernelMode.WRITEFILE:
            self.mode = KernelMode.DEFAULT
            with os.fdopen(
                os.open(self.writefile_bash_name, os.O_WRONLY | os.O_APPEND),
                "a",
            ) as bash_script:
                bash_script.write(
                    f"{''.join(self.writefile_scorep_env)}\n"
                    f"{PYTHON_EXECUTABLE} -m scorep "
                    f"{' '.join(self.writefile_scorep_binding_args)} "
                    f"{self.writefile_python_name}"
                )
            self.cell_output("Finished converting to Python script.")
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def abort_writefile(self):
        """
        Cancel writefile mode.
        """
        if self.mode == KernelMode.WRITEFILE:
            self.mode = KernelMode.DEFAULT

            if os.path.exists(self.writefile_bash_name):
                os.remove(self.writefile_bash_name)
            if os.path.exists(self.writefile_python_name):
                os.remove(self.writefile_python_name)

            self.writefile_base_name = "jupyter_to_script"
            self.writefile_bash_name = ""
            self.writefile_python_name = ""
            self.writefile_scorep_binding_args = []
            self.writefile_multicell = False
            self.cell_output("Writefile mode aborted.")
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def ghost_cell_error(self, reply_status, error_message):
        self.shell.execution_count += 1
        reply_status["execution_count"] = self.shell.execution_count - 1
        self.pershelper.postprocess()
        self.cell_output(error_message, "stderr")

    async def scorep_execute(
        self,
        code,
        silent,
        user_expressions=None,
        allow_stdin=False,
        *,
        cell_id=None,
    ):
        """
        Execute given code with Score-P Python bindings instrumentation.
        """
        # Set up files/pipes for persistence communication
        if not self.pershelper.preprocess():
            self.pershelper.postprocess()
            self.cell_output(
                "KernelError: Failed to set up the persistence communication "
                "files/pipes.",
                "stderr",
            )
            return self.standard_reply()

        # Prepare code for the Score-P instrumented execution as subprocess
        # Transmit user persistence and updated sys.path from Jupyter
        # notebook to subprocess After running the code, transmit subprocess
        # persistence back to Jupyter notebook
        with os.fdopen(
            os.open(scorep_script_name, os.O_WRONLY | os.O_CREAT), "w"
        ) as file:
            file.write(self.pershelper.subprocess_wrapper(code))
        # For disk mode use implicit synchronization between kernel and
        # subprocess: await jupyter_dump, subprocess.wait(),
        # await jupyter_update Ghost cell - dump current Jupyter session for
        # subprocess Run in a "silent" way to not increase cells counter
        if self.pershelper.mode == "disk":
            reply_status_dump = await super().do_execute(
                self.pershelper.jupyter_dump(),
                silent,
                store_history=False,
                user_expressions=user_expressions,
                allow_stdin=allow_stdin,
                cell_id=cell_id,
            )

            if reply_status_dump["status"] != "ok":
                self.ghost_cell_error(
                    reply_status_dump,
                    "KernelError: Failed to pickle notebook's persistence.",
                )
                return reply_status_dump

        # Launch subprocess with Jupyter notebook environment
        cmd = (
            [PYTHON_EXECUTABLE, "-m", "scorep"]
            + self.scorep_binding_args
            + [scorep_script_name]
        )
        scorep_env = {
            key: os.environ[key]
            for key in os.environ
            if key.startswith("SCOREP_")
        }
        proc_env = {
            "PATH": os.environ.get("PATH", ""),
            "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "EBPYTHONPREFIXES": os.environ.get("EBPYTHONPREFIXES", ""),
            "PYTHONUNBUFFERED": "x",
        }
        proc_env.update(scorep_env)
        # scorep path, subprocess observation

        # determine datetime for figuring out scorep path after execution
        dt = datetime.datetime.now()
        hour = dt.strftime("%H")
        minute = dt.strftime("%M")

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=proc_env
        )

        # For memory mode jupyter_dump and jupyter_update must be awaited
        # concurrently to the running subprocess
        if self.pershelper.mode == "memory":
            reply_status_dump = await super().do_execute(
                self.pershelper.jupyter_dump(),
                silent,
                store_history=False,
                user_expressions=user_expressions,
                allow_stdin=allow_stdin,
                cell_id=cell_id,
            )
            if reply_status_dump["status"] != "ok":
                self.ghost_cell_error(
                    reply_status_dump,
                    "KernelError: Failed to pickle notebook's persistence.",
                )
                return reply_status_dump

        # Redirect process stderr to stdout and observe the latter
        # Observing two stream with two threads causes interference in
        # cell_output in Jupyter notebook
        # stdout is read in chunks, which are split into lines using
        # \r or \n as delimiter
        # Last element in the list might be "incomplete line",
        # not ending with \n or \r, it is saved
        # and merged with the first line in the next chunk
        incomplete_line = ""
        endline_pattern = re.compile(r"(.*?[\r\n]|.+$)")
        # Empty cell output, required for interactive output
        # e.g. tqdm for-loop progress bar
        self.cell_output("\0")

        multicellmode_timestamps = []
        while True:
            chunk = b"" + proc.stdout.read(READ_CHUNK_SIZE)
            if chunk == b"":
                break
            chunk = chunk.decode(sys.getdefaultencoding(), errors="ignore")
            lines = endline_pattern.findall(chunk)
            if len(lines) > 0:
                lines[0] = incomplete_line + lines[0]
                if lines[-1][-1] not in ["\n", "\r"]:
                    incomplete_line = lines.pop(-1)
                else:
                    incomplete_line = ""
                for line in lines:
                    if "MCM_TS" in line:
                        multicellmode_timestamps.append(line)
                        continue
                    self.cell_output(line)

        # In disk mode, subprocess already terminated
        # after dumping persistence to file
        if self.pershelper.mode == "disk":
            if proc.returncode:
                self.pershelper.postprocess()
                self.cell_output(
                    "KernelError: Cell execution failed, cell persistence "
                    "was not recorded.",
                    "stderr",
                )
                return self.standard_reply()

        # Ghost cell - load subprocess persistence back to Jupyter notebook
        # Run in a "silent" way to not increase cells counter
        reply_status_update = await super().do_execute(
            self.pershelper.jupyter_update(code),
            silent,
            store_history=False,
            user_expressions=user_expressions,
            allow_stdin=allow_stdin,
            cell_id=cell_id,
        )
        if reply_status_update["status"] != "ok":
            self.ghost_cell_error(
                reply_status_update,
                "KernelError: Failed to load cell's persistence to the "
                "notebook.",
            )
            return reply_status_update

        # In memory mode, subprocess terminates once jupyter_update is
        # executed and pipe is closed
        if self.pershelper.mode == "memory":
            if proc.returncode:
                self.pershelper.postprocess()
                self.cell_output(
                    "KernelError: Cell execution failed, cell persistence "
                    "was not recorded.",
                    "stderr",
                )
                return self.standard_reply()

        # Determine directory to which trace files were saved by Score-P
        scorep_folder = ""
        if "SCOREP_EXPERIMENT_DIRECTORY" in os.environ:
            scorep_folder = os.environ["SCOREP_EXPERIMENT_DIRECTORY"]
            self.cell_output(
                f"Instrumentation results can be found in {scorep_folder}"
            )
        else:
            # Find last created directory with scorep* name
            # TODO: Directory isn't created local when running scorep-collector
            max_iterations = 5
            while max_iterations > 0:
                # regular scorep folders always: scorep-YYYYMMDD_HHMM_XXXXXXX
                scorep_dirs = [
                    d
                    for d in os.listdir(".")
                    if os.path.isdir(d) and "scorep" in d and "_" in d
                ]
                if scorep_dirs:
                    scorep_folder = max(scorep_dirs, key=os.path.getmtime)
                    folder_time = int(scorep_folder.split("_")[1])
                    start_time = int(hour + minute)
                    if folder_time >= start_time:
                        break
                    time.sleep(1)
                    max_iterations -= 1

            if max_iterations == 0:
                self.cell_output(
                    "KernelWarning: Path of Instrumentation results could "
                    "not be determined or were not saved locally.",
                    "stderr",
                )
            else:
                self.cell_output(
                    f"Instrumentation results can be found in "
                    f"{os.getcwd()}/{scorep_folder}"
                )

        self.pershelper.postprocess()
        return self.standard_reply()

    async def do_execute(
        self,
        code,
        silent,
        store_history=False,
        user_expressions=None,
        allow_stdin=False,
        *,
        cell_id=None,
        **kwargs,
    ):
        """
        Override of do_execute() method of IPythonKernel. If no custom magic
        commands specified, execute cell with super().do_execute(),
        else save Score-P environment/binding arguments/ execute cell with
        Score-P Python binding.
        """
        if code.startswith("%%scorep_python_binding_arguments"):
            return self.scorep_not_available() or self.set_scorep_pythonargs(
                code
            )
        elif code.startswith("%%serializer_settings"):
            self.cell_output(
                "Deprecated. Use: %%marshalling_settings"
                "\n[MARSHALLER=]\n[MODE=]",
                "stdout",
            )
            return self.standard_reply()
        elif code.startswith("%%marshalling_settings"):
            return self.scorep_not_available() or self.marshaller_settings(
                code
            )
        elif code.startswith("%%enable_multicellmode"):
            return self.scorep_not_available() or self.enable_multicellmode()
        elif code.startswith("%%abort_multicellmode"):
            return self.scorep_not_available() or self.abort_multicellmode()
        elif code.startswith("%%finalize_multicellmode"):
            # Cannot be put into a separate function due to tight coupling
            # between do_execute and scorep_execute
            if self.mode == KernelMode.MULTICELL:
                self.mode = KernelMode.DEFAULT
                try:
                    reply_status = await self.scorep_execute(
                        self.multicell_code,
                        silent,
                        user_expressions,
                        allow_stdin,
                        cell_id=cell_id,
                    )
                except Exception:
                    self.cell_output(
                        "KernelError: Multicell execution failed.",
                        "stderr",
                    )
                    return self.standard_reply()
                self.multicell_code = ""
                self.multicell_cellcount = -1
                return reply_status
            elif self.mode == KernelMode.WRITEFILE:
                self.writefile_multicell = False
                return self.standard_reply()
            else:
                self.cell_output(
                    f"KernelWarning: Currently in {self.mode},"
                    f" ignore command",
                    "stderr",
                )
                return self.standard_reply()
        elif code.startswith("%%start_writefile"):
            return self.scorep_not_available() or self.start_writefile(code)
        elif code.startswith("%%abort_writefile"):
            return self.scorep_not_available() or self.abort_writefile()
        elif code.startswith("%%end_writefile"):
            return self.scorep_not_available() or self.end_writefile()
        elif code.startswith("%%execute_with_scorep"):
            scorep_missing = self.scorep_not_available()
            if scorep_missing is None:
                if self.mode == KernelMode.DEFAULT:
                    return await self.scorep_execute(
                        code.split("\n", 1)[1],
                        silent,
                        user_expressions,
                        allow_stdin,
                        cell_id=cell_id,
                    )
                elif self.mode == KernelMode.MULTICELL:
                    return self.append_multicellmode(
                        magics_cleanup(code.split("\n", 1)[1])[1]
                    )
                elif self.mode == KernelMode.WRITEFILE:
                    scorep_env, nomagic_code = magics_cleanup(
                        code.split("\n", 1)[1]
                    )
                    self.writefile_scorep_env.extend(scorep_env)
                    return self.append_writefile(
                        nomagic_code,
                        explicit_scorep=True,
                    )
            else:
                return scorep_missing
        else:
            if self.mode == KernelMode.DEFAULT:
                self.pershelper.parse(magics_cleanup(code)[1], "jupyter")
                parent_ret = await super().do_execute(
                    code,
                    silent,
                    store_history,
                    user_expressions,
                    allow_stdin,
                    cell_id=cell_id,
                )
                return parent_ret
            elif self.mode == KernelMode.MULTICELL:
                return self.append_multicellmode(magics_cleanup(code)[1])
            elif self.mode == KernelMode.WRITEFILE:
                scorep_env, nomagic_code = magics_cleanup(code)
                self.writefile_scorep_env.extend(scorep_env)
                return self.append_writefile(
                    nomagic_code,
                    explicit_scorep=False,
                )

    def do_shutdown(self, restart):
        self.pershelper.postprocess()
        return super().do_shutdown(restart)


if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp

    IPKernelApp.launch_instance(kernel_class=JumperKernel)
