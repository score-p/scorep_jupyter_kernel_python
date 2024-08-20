import datetime
import json
import os
import re
import subprocess
import sys
import time

from enum import Enum
from textwrap import dedent
from statistics import mean
import pandas as pd
from ipykernel.ipkernel import IPythonKernel
from itables import show
from jumper.userpersistence import PersHelper, scorep_script_name
from jumper.userpersistence import magics_cleanup

from jumper.perfdatahandler import PerformanceDataHandler
import jumper.visualization as perfvis

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
        self.scorep_env = {}

        os.environ["SCOREP_KERNEL_PERSISTENCE_DIR"] = "./"
        self.pershelper = PersHelper("dill", "memory")

        self.mode = KernelMode.DEFAULT

        self.multicell_cellcount = 0
        self.multicell_code = ""

        self.writefile_base_name = "jupyter_to_script"
        self.writefile_bash_name = ""
        self.writefile_python_name = ""
        self.writefile_scorep_env = []
        self.writefile_scorep_binding_args = []
        self.writefile_multicell = False

        # will be set to True as soon as GPU data is received
        self.gpu_avail = False
        self.perfdata_handler = PerformanceDataHandler()
        self.nodelist = self.perfdata_handler.get_nodelist()

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

    def marshaller_settings(self, code):
        """
        Switch serializer/marshalling backend used for persistence in kernel.
        """
        if self.mode == KernelMode.DEFAULT:
            # Clean files/pipes before switching
            self.pershelper.postprocess()

            marshaller_match = re.search(
                r"MARSHALLER=(\w+)", code.split("\n", 1)[1]
            )
            mode_match = re.search(r"MODE=(\w+)", code.split("\n", 1)[1])
            marshaller = (
                marshaller_match.group(1) if marshaller_match else None
            )
            mode = mode_match.group(1) if mode_match else None

            if marshaller:
                if not self.pershelper.set_marshaller(marshaller):
                    self.cell_output(
                        f"Marshaller '{marshaller}' is not recognized, "
                        f"kernel will use '{self.pershelper.marshaller}'.",
                        "stderr",
                    )
                    return self.standard_reply()
            if mode:
                if not self.pershelper.set_mode(mode):
                    self.cell_output(
                        f"Marshalling mode '{mode}' is not recognized, "
                        f"kernel will use '{self.pershelper.mode}'.",
                        "stderr",
                    )

            self.cell_output(
                f"Kernel uses '{self.pershelper.marshaller}' marshaller in"
                f"'{self.pershelper.mode}' mode."
            )
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def set_perfmonitor(self, code):
        """
        Read the perfmonitor and try to select it.
        """
        if self.mode == KernelMode.DEFAULT:
            monitor = code.split("\n")[1]
            if monitor in {"local", "localhost", "LOCAL", "LOCALHOST"}:
                self.cell_output(
                    "Selected local monitor. No parallel monitoring."
                )
            else:
                try:
                    self.perfdata_handler.set_monitor(monitor)
                    self.nodelist = self.perfdata_handler.get_nodelist()
                    if len(self.nodelist) <= 1:
                        self.nodelist = None
                        self.cell_output(
                            "Found monitor: "
                            + str(monitor)
                            + " but no nodelist, using local setup. "
                        )
                    else:
                        self.cell_output(
                            "Selected monitor: "
                            + str(monitor)
                            + " and got nodes: "
                            + str(self.nodelist)
                        )
                except Exception:
                    self.cell_output("Error setting monitor", "stderr")
        else:
            self.cell_output(
                f"KernelWarning: Currently in {self.mode}, command ignored.",
                "stderr",
            )
        return self.standard_reply()

    def set_scorep_env(self, code):
        """
        Read and record Score-P environment variables from the cell.
        """
        if self.mode == KernelMode.DEFAULT:
            for scorep_param in code.split("\n")[1:]:
                key, val = scorep_param.split("=")
                self.scorep_env[key] = val
            self.cell_output(
                "Score-P environment set successfully: " + str(self.scorep_env)
            )
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_scorep_env += code.split("\n")[1:]
            self.cell_output("Environment variables recorded.")
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
            self.scorep_binding_args += code.split("\n")[1:]
            self.cell_output(
                "Score-P Python binding arguments set successfully: "
                + str(self.scorep_binding_args)
            )
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_scorep_binding_args += code.split("\n")[1:]
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
                + f"{code}\n"
                + "print('''\n''')\n"
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
            self.multicell_code = ""
            self.multicell_cellcount = 0
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

            with os.fdopen(os.open(self.writefile_bash_name, os.O_WRONLY | os.O_CREAT), 'w') as bash_script:
                bash_script.write(
                    dedent(
                        f"""
                        # This bash script is generated automatically to run
                        # Jupyter Notebook -> Python script conversion
                        # by Jumper kernel
                        # {self.writefile_python_name}
                        # !/bin/bash
                        """
                    )
                )
            with os.fdopen(os.open(self.writefile_python_name, os.O_WRONLY | os.O_CREAT), 'w') as python_script:
                python_script.write(
                    dedent(
                        f"""
                        # This is the automatic conversion of
                        # Jupyter Notebook -> Python script by Jumper kernel.
                        # Code corresponding to the cells not marked for
                        # Score-P instrumentation is framed by
                        # "with scorep.instrumenter.disable()
                        # The script can be run with proper settings using
                        # bash script {self.writefile_bash_name}
                        import scorep
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
            if explicit_scorep or self.writefile_multicell:
                with os.fdopen(os.open(self.writefile_python_name, os.O_WRONLY | os.O_APPEND), 'a') as python_script:
                    python_script.write(code + "\n")
                self.cell_output(
                    "Python commands with instrumentation recorded."
                )
            else:
                with os.fdopen(os.open(self.writefile_python_name, os.O_WRONLY | os.O_APPEND), 'a') as python_script:
                    code = "".join(
                        ["    " + line + "\n" for line in code.split("\n")]
                    )
                    python_script.write(
                        "with scorep.instrumenter.disable():\n" + code + "\n"
                    )
                self.cell_output(
                    "Python commands without instrumentation recorded."
                )
        return self.standard_reply()

    def end_writefile(self):
        """
        Finish recording the notebook as a Python script.
        """
        # TODO: check for os path existence
        if self.mode == KernelMode.WRITEFILE:
            self.mode = KernelMode.DEFAULT
            with os.fdopen(os.open(self.writefile_bash_name, os.O_WRONLY | os.O_APPEND), 'a') as bash_script:
                bash_script.write(
                    f"{' '.join(self.writefile_scorep_env)} "
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

    def ghost_cell_error(self, reply_status, error_message):
        self.shell.execution_count += 1
        reply_status["execution_count"] = self.shell.execution_count - 1
        self.pershelper.postprocess()
        self.cell_output(error_message, "stderr")

    def report_perfdata(self, performance_data_nodes, duration):

        # print the performance data
        report_trs = int(os.environ.get("JUMPER_REPORTS_MIN", 2))

        # just count the number of memory measurements to decide whether we
        # want to print the information
        if len(performance_data_nodes[0][1]) > report_trs:

            self.cell_output("\n----Performance Data----\n", "stdout")
            self.cell_output(
                "Duration: " + "{:.2f}".format(duration) + "\n", "stdout"
            )
            # last 4 values are means across nodes, print them separately

            """
            structure in performance_data_nodes:
            [
                [NODE_1: [CPU_UTIL:[CPU_1][CPU_2][CPU_N][MEAN][MAX][MIN]]
                         [MEM_UTIL]
                         [GPU_UTIL:[GPU_1][GPU_2][GPU_N][MEAN][MAX][MIN]
                         [GPU_MEM:[GPU_1][GPU_2][GPU_N][MEAN][MAX][MIN]]
                [NODE_2: [...]]
                [NODE_N: [...]]
                [CPU_UTIL_ACROSS_NODES (The mean of the means)]
                [MEM_UTIL_ACROSS_NODES (The mean of the raw values)]
                [GPU_UTIL_ACROSS_NODES (The mean of the means)]
                [GPU_MEM_ACROSS_NODES (The mean of the means)]
            ]
            """

            for idx, performance_data in enumerate(
                performance_data_nodes[:-8]
            ):

                if self.nodelist:
                    self.cell_output(
                        "--NODE " + str(self.nodelist[idx]) + "--\n", "stdout"
                    )

                cpu_util = performance_data[0]
                mem_util = performance_data[1]
                io_ops_read = performance_data[2]
                io_ops_write = performance_data[3]
                io_bytes_read = performance_data[4]
                io_bytes_write = performance_data[5]
                gpu_util = performance_data[6]
                gpu_mem = performance_data[7]

                if cpu_util:
                    # self.cell_output("--CPU Util--\n", 'stdout')
                    self.cell_output(
                        "\nCPU Util (Across CPUs)       \tAVG: "
                        + "{:.2f}".format(mean(cpu_util[-3]))
                        + "\t MIN: "
                        + "{:.2f}".format(min(cpu_util[-1]))
                        + "\t MAX: "
                        + "{:.2f}".format(max(cpu_util[-2]))
                        + "\n",
                        "stdout",
                    )

                if len(mem_util) > 0:
                    self.cell_output(
                        "Mem Util in GB (Across nodes)\tAVG: "
                        + "{:.2f}".format(mean(mem_util))
                        + "\t MIN: "
                        + "{:.2f}".format(min(mem_util))
                        + "\t MAX: "
                        + "{:.2f}".format(max(mem_util))
                        + "\n",
                        "stdout",
                    )

                if len(io_ops_read) > 0:
                    self.cell_output(
                        "IO Ops (excl.) Read          \tTotal: "
                        + "{:.0f}".format(io_ops_read[-1])
                        + "\n",
                        "stdout",
                    )

                if len(io_ops_write) > 0:
                    self.cell_output(
                        "               Write         \tTotal: "
                        + "{:.0f}".format(io_ops_write[-1])
                        + "\n",
                        "stdout",
                    )

                if len(io_bytes_read) > 0:
                    self.cell_output(
                        "IO Bytes (excl.) Read        \tTotal: "
                        + "{:.2f}".format(io_bytes_read[-1])
                        + "\n",
                        "stdout",
                    )

                if len(io_bytes_write) > 0:
                    self.cell_output(
                        "                 Write       \tTotal: "
                        + "{:.2f}".format(io_bytes_write[-1])
                        + "\n",
                        "stdout",
                    )

                if gpu_util[0] and gpu_mem[0]:
                    self.gpu_avail = True
                    self.cell_output(
                        "--GPU Util and Mem per GPU--\n", "stdout"
                    )
                    self.cell_output(
                        "GPU Util \tAVG: "
                        + "{:.2f}".format(mean(gpu_util[-3]))
                        + "\t MIN: "
                        + "{:.2f}".format(min(gpu_util[-1]))
                        + "\t MAX: "
                        + "{:.2f}".format(max(gpu_util[-2]))
                        + "\n",
                        "stdout",
                    )
                    self.cell_output(
                        "\t    "
                        + "\tMem AVG: "
                        + "{:.2f}".format(mean(gpu_mem[-3]))
                        + "\t MIN: "
                        + "{:.2f}".format(min(gpu_mem[-1]))
                        + "\t MAX: "
                        + "{:.2f}".format(max(gpu_mem[-2]))
                        + "\n",
                        "stdout",
                    )

            """
            performance data nodes consists of:
            [raw data node0,
             raw data node1,
             raw data noden,
             CPU Mean across nodes,
             Mem Mean across nodes,
             IO OPS READ Mean across nodes,
             IO OPS WRITE Mean across nodes,
             IO Bytes READ Mean across nodes,
             IO Bytes WRITE Mean across nodes,
             GPU Util Mean across nodes (if avail),
             GPU Mem Mean across nodes (if avail)]
            """
            """
            if len(performance_data_nodes)-8 > 1:
                self.cell_output("\n---Across Nodes---\n", 'stdout')

                self.cell_output(
                    "\n--CPU Util-- \tAVG: " + "{:.2f}".format(
                        mean(performance_data_nodes[-4])) + "\t MIN: " +
                        "{:.2f}".format(
                        min(performance_data_nodes[-4])) + "\t MAX: " +
                         "{:.2f}".format(max(performance_data_nodes[-4])) +
                          "\n", 'stdout')

                if performance_data_nodes[-3]:
                    self.cell_output(
                        "--Mem Util-- \tAVG: " + "{:.2f}".format(
                            mean(performance_data_nodes[-3])) + "\t MIN: " +
                             "{:.2f}".format(
                            min(performance_data_nodes[-3])) + "\t MAX: " +
                             "{:.2f}".format(
                            max(performance_data_nodes[-3])) + "\n", 'stdout')

                if performance_data_nodes[-2] and performance_data_nodes[-1]:
                    self.cell_output("--GPU Util and Mem per GPU--\n",'stdout')
                    self.cell_output(
                        "--GPU Util-- \tAVG: " + "{:.2f}".format(
                            mean(performance_data_nodes[-2])) + "\t MIN: " +
                             "{:.2f}".format(
                            min(performance_data_nodes[-2])) + "\t MAX: " +
                             "{:.2f}".format(max(performance_data_nodes[-2])) +
                              "\n", 'stdout')
                    self.cell_output("\t    " +
                                     "\tMem AVG: " + "{:.2f}".format(
                        mean(performance_data_nodes[-1])) + "\t MIN: " +
                         "{:.2f}".format(
                        min(performance_data_nodes[-1])) + "\t MAX: " +
                         "{:.2f}".format(max(performance_data_nodes[-1])) +
                          "\n", 'stdout')
            """

    async def scorep_execute(
        self,
        code,
        silent,
        store_history=True,
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
        with os.fdopen(os.open(scorep_script_name, os.O_WRONLY | os.O_CREAT), 'w') as file:
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
        proc_env = self.scorep_env.copy()
        proc_env.update({'PATH': os.environ.get('PATH', ''),
                         'LD_LIBRARY_PATH':
                             os.environ.get('LD_LIBRARY_PATH', ''),
                         'PYTHONPATH':
                             os.environ.get('PYTHONPATH', ''),
                         'PYTHONUNBUFFERED': 'x'})
        # scorep path, subprocess observation

        # determine datetime for figuring out scorep path after execution
        dt = datetime.datetime.now()
        hour = dt.strftime("%H")
        minute = dt.strftime("%M")

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=proc_env
        )
        self.perfdata_handler.start_perfmonitor(proc.pid)
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
                    self.cell_output(line)

        performance_data_nodes, duration = (
            self.perfdata_handler.end_perfmonitor(code)
        )

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

        # os_environ_.clear()
        # sys_path_.clear()

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
        if "SCOREP_EXPERIMENT_DIRECTORY" in self.scorep_env:
            scorep_folder = self.scorep_env["SCOREP_EXPERIMENT_DIRECTORY"]
            self.cell_output(
                f"Instrumentation results can be found in {scorep_folder}"
            )
        else:
            # Find last creasted directory with scorep* name
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
        if performance_data_nodes:
            self.report_perfdata(performance_data_nodes, duration)
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
    ):
        """
        Override of do_execute() method of IPythonKernel. If no custom magic
        commands specified, execute cell with super().do_execute(),
        else save Score-P environment/binding arguments/ execute cell with
        Score-P Python binding.
        """

        """
        #displays all ran cell codes with index and timestamp
        %%display_code_all

        #displays code for index
        %%display_code_for_index i

        # displays graphs for last cell, arguments: cpu_util etc.
        %%display_graphs_for_last cpu_util, ...
        # displays one graph for all cell, arguments: cpu_util etc.
        %%display_graphs_for_all cpu_util, ...
        # -> would be cool if we can hover the graph and per timepoint,
        we see the index of the cell
        # displays graph for index cell, arguments: cpu_util etc.
        %%display_graphs_for_index i cpu_util, ...
        """
        """
        if code.startswith('%%display_graph_for_last'):
            metrics = code.split(' ')
            nmetrics = len(metrics) - 1
            self.draw_performance_graph(
                            self.get_perfdata_index(-1, metrics[1:]), nmetrics)
            return self.standard_reply()
        """
        if code.startswith("%%display_graph_for_last"):
            perfvis.draw_performance_graph(
                self.nodelist,
                self.perfdata_handler.get_perfdata_history()[-1],
                self.gpu_avail,
            )
            return self.standard_reply()
        elif code.startswith("%%display_graph_for_index"):
            if len(code.split(" ")) == 1:
                self.cell_output(
                    "No index specified. Use: %%display_graph_for_index index",
                    "stdout",
                )
            index = int(code.split(" ")[1])
            if index >= len(self.perfdata_handler.get_perfdata_history()):
                self.cell_output(
                    "Tracked only "
                    + str(len(self.perfdata_handler.get_perfdata_history()))
                    + " cells. This index is not available."
                )
            else:
                perfvis.draw_performance_graph(
                    self.nodelist,
                    self.perfdata_handler.get_perfdata_history()[index],
                    self.gpu_avail,
                )
            return self.standard_reply()
        elif code.startswith("%%display_graph_for_all"):
            data, time_indices = (
                self.perfdata_handler.get_perfdata_aggregated())
            perfvis.draw_performance_graph(
                self.nodelist,
                data,
                self.gpu_avail,
                time_indices,
            )
            return self.standard_reply()

        elif code.startswith("%%display_code_for_index"):
            if len(code.split(" ")) == 1:
                self.cell_output(
                    "No index specified. Use: %%display_code_for_index index",
                    "stdout",
                )
            index = int(code.split(" ")[1])
            if index >= len(self.perfdata_handler.get_perfdata_history()):
                self.cell_output(
                    "Tracked only "
                    + str(len(self.perfdata_handler.get_perfdata_history()))
                    + " cells. This index is not available."
                )
            else:
                self.cell_output(
                    "Cell timestamp: "
                    + str(self.perfdata_handler.get_code_history()[index][0])
                    + "\n--\n",
                    "stdout",
                )
                self.cell_output(
                    self.perfdata_handler.get_code_history()[index][1],
                    "stdout",
                )
            return self.standard_reply()
        elif code.startswith("%%display_code_history"):
            show(
                pd.DataFrame(
                    self.perfdata_handler.get_code_history(),
                    columns=["timestamp", "code"],
                ).reset_index()
            )
            return self.standard_reply()
        elif code.startswith("%%perfdata_to_variable"):
            if len(code.split(" ")) == 1:
                self.cell_output(
                    "No variable to export specified. Use: "
                    "%%perfdata_to_variable myvar",
                    "stdout",
                )
            else:
                varname = code.split(" ")[1]
                await super().do_execute(
                    f"{varname}="
                    f"{self.perfdata_handler.get_perfdata_history()}",
                    silent=True,
                )
                self.cell_output(
                    "Exported performance data to "
                    + str(varname)
                    + " variable",
                    "stdout",
                )
            return self.standard_reply()
        elif code.startswith("%%perfdata_to_json"):
            if len(code.split(" ")) == 1:
                self.cell_output(
                    "No filename to export specified. Use: "
                    "%%perfdata_to_variable myfile",
                    "stdout",
                )
            else:
                filename = code.split(" ")[1]
                with open(f"{filename}_perfdata.json", "w") as f:
                    json.dump(
                        self.perfdata_handler.get_perfdata_history(),
                        default=str,
                        fp=f,
                    )
                with open(f"{filename}_code.json", "w") as f:
                    json.dump(
                        self.perfdata_handler.get_code_history(),
                        default=str,
                        fp=f,
                    )
                self.cell_output(
                    "Exported performance data to "
                    + str(filename)
                    + "_perfdata.json and "
                    + str(filename)
                    + "_code.json",
                    "stdout",
                )
            return self.standard_reply()
        elif code.startswith("%%set_perfmonitor"):
            return self.set_perfmonitor(code)
        elif code.startswith("%%scorep_env"):
            return self.set_scorep_env(code)
        elif code.startswith("%%scorep_python_binding_arguments"):
            return self.set_scorep_pythonargs(code)
        elif code.startswith("%%serializer_settings"):
            self.cell_output(
                "Deprecated. Use: %%marshalling_settings\n[MARSHALLER=]\n[MODE=]",
                "stdout",
            )
            return self.standard_reply()
        elif code.startswith("%%marshalling_settings"):
            return self.marshaller_settings(code)
        elif code.startswith("%%enable_multicellmode"):
            return self.enable_multicellmode()
        elif code.startswith("%%abort_multicellmode"):
            return self.abort_multicellmode()
        elif code.startswith("%%finalize_multicellmode"):
            # Cannot be put into a separate function due to tight coupling
            # between do_execute and scorep_execute
            if self.mode == KernelMode.MULTICELL:
                self.mode = KernelMode.DEFAULT
                try:
                    reply_status = await self.scorep_execute(
                        self.multicell_code,
                        silent,
                        store_history,
                        user_expressions,
                        allow_stdin,
                        cell_id=cell_id,
                    )
                except Exception:
                    self.cell_output(
                        "KernelError: Multicell execution failed.", "stderr"
                    )
                    return self.standard_reply()
                self.multicell_code = ""
                self.multicell_cellcount = 0
                return reply_status
            elif self.mode == KernelMode.WRITEFILE:
                self.writefile_multicell = False
                return self.standard_reply()
            else:
                self.cell_output(
                    f"KernelWarning: Currently in {self.mode}, ignore command",
                    "stderr",
                )
                return self.standard_reply()
        elif code.startswith("%%start_writefile"):
            return self.start_writefile(code)
        elif code.startswith("%%end_writefile"):
            return self.end_writefile()
        elif code.startswith("%%execute_with_scorep"):
            if self.mode == KernelMode.DEFAULT:
                return await self.scorep_execute(
                    code.split("\n", 1)[1],
                    silent,
                    store_history,
                    user_expressions,
                    allow_stdin,
                    cell_id=cell_id,
                )
            elif self.mode == KernelMode.MULTICELL:
                return self.append_multicellmode(
                    magics_cleanup(code.split("\n", 1)[1])
                )
            elif self.mode == KernelMode.WRITEFILE:
                return self.append_writefile(
                    magics_cleanup(code.split("\n", 1)[1]),
                    explicit_scorep=True,
                )
        else:
            if self.mode == KernelMode.DEFAULT:
                self.pershelper.parse(magics_cleanup(code), "jupyter")
                self.perfdata_handler.start_perfmonitor(os.getpid())
                parent_ret = await super().do_execute(
                    code,
                    silent,
                    store_history,
                    user_expressions,
                    allow_stdin,
                    cell_id=cell_id,
                )
                performance_data_nodes, duration = (
                    self.perfdata_handler.end_perfmonitor(code)
                )
                if performance_data_nodes:
                    self.report_perfdata(performance_data_nodes, duration)
                return parent_ret
            elif self.mode == KernelMode.MULTICELL:
                return self.append_multicellmode(magics_cleanup(code))
            elif self.mode == KernelMode.WRITEFILE:
                return self.append_writefile(
                    magics_cleanup(code), explicit_scorep=False
                )

    def do_shutdown(self, restart):
        self.pershelper.postprocess()
        return super().do_shutdown(restart)


if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp

    IPKernelApp.launch_instance(kernel_class=JumperKernel)
