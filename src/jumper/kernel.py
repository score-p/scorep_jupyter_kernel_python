import datetime
import json
import os
import re
import selectors
import subprocess
import sys
import threading
import time
import shutil
import logging.config

from enum import Enum
from textwrap import dedent
from statistics import mean
import pandas as pd
from ipykernel.ipkernel import IPythonKernel
from itables import show
from jumper.userpersistence import PersHelper, scorep_script_name
from jumper.userpersistence import magics_cleanup, create_busy_spinner
import importlib
from jumper.perfdatahandler import PerformanceDataHandler
import jumper.visualization as perfvis
from jumper.kernel_messages import KernelErrorCode, KERNEL_ERROR_MESSAGES

# import jumper.multinode_monitor.slurm_monitor as slurm_monitor

from .logging_config import LOGGING

PYTHON_EXECUTABLE = sys.executable
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

        # will be set to True as soon as GPU data is received
        self.gpu_avail = False
        self.perfdata_handler = PerformanceDataHandler()
        self.nodelist = self.perfdata_handler.get_nodelist()

        self.scorep_available_ = shutil.which("scorep")
        self.scorep_python_available_ = True
        try:
            importlib.import_module("scorep")
        except ModuleNotFoundError:
            self.scorep_python_available_ = False

        logging.config.dictConfig(LOGGING)
        self.log = logging.getLogger('kernel')

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
            self.log_error(KernelErrorCode.SCOREP_NOT_AVAILABLE)
            return self.standard_reply()
        if not self.scorep_python_available_:
            self.log_error(KernelErrorCode.SCOREP_PYTHON_NOT_AVAILABLE)
            return self.standard_reply()
        return None

    def marshaller_settings(self, code):
        """
        Switch serializer/marshalling backend used for persistence in kernel.
        """
        if self.mode == KernelMode.DEFAULT:
            # Clean files/pipes before switching
            self.pershelper.postprocess()

            marshaller_match = re.search(
                r"MARSHALLER=([\w-]+)", code.split("\n", 1)[1]
            )
            mode_match = re.search(r"MODE=([\w-]+)", code.split("\n", 1)[1])
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
        user_expressions=None,
        allow_stdin=False,
        *,
        cell_id=None,
    ):
        """
        Execute given code with Score-P Python bindings instrumentation.
        """
        self.log.info("Executing Score-P instrumented code...")
        self.pershelper.set_dump_report_level()
        # Set up files/pipes for persistence communication
        if not self.pershelper.preprocess():
            self.pershelper.postprocess()
            self.log_error(KernelErrorCode.PERSISTENCE_SETUP_FAIL)
            return self.standard_reply()

        self.log.debug("Persistence communication set up successfully.")

        # Prepare code for the Score-P instrumented execution as subprocess
        # Transmit user persistence and updated sys.path from Jupyter
        # notebook to subprocess After running the code, transmit subprocess
        # persistence back to Jupyter notebook
        with os.fdopen(
            os.open(scorep_script_name, os.O_WRONLY | os.O_CREAT), "w"
        ) as file:
            file.write(self.pershelper.subprocess_wrapper(code))
        self.log.debug(f"Code written to temporary script: {scorep_script_name}")

        # For disk mode use implicit synchronization between kernel and
        # subprocess: await jupyter_dump, subprocess.wait(),
        # await jupyter_update Ghost cell - dump current Jupyter session for
        # subprocess Run in a "silent" way to not increase cells counter
        if self.pershelper.mode == "disk":
            self.log.debug("Executing Jupyter dump for disk mode.")
            reply_status_dump = await super().do_execute(
                self.pershelper.jupyter_dump(),
                silent,
                store_history=False,
                user_expressions=user_expressions,
                allow_stdin=allow_stdin,
                cell_id=cell_id,
            )

            if reply_status_dump["status"] != "ok":
                self.log_error(KernelErrorCode.PERSISTENCE_DUMP_FAIL, direction="Jupyter -> Score-P")
                self.pershelper.postprocess()
                return reply_status_dump

        # Launch subprocess with Jupyter notebook environment
        self.log.debug("Preparing subprocess execution.")

        cmd = (
            [PYTHON_EXECUTABLE, "-m", "scorep"]
            + self.scorep_binding_args
            + [scorep_script_name]
        )
        self.log.debug(f"Subprocess command: {' '.join(cmd)}")

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
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=proc_env
        )
        self.log.debug(f"Subprocess started with PID {proc.pid}")

        self.perfdata_handler.start_perfmonitor(proc.pid)
        # For memory mode jupyter_dump and jupyter_update must be awaited
        # concurrently to the running subprocess
        if self.pershelper.mode == "memory":
            self.log.debug("Executing Jupyter dump for memory mode.")
            reply_status_dump = await super().do_execute(
                self.pershelper.jupyter_dump(),
                silent,
                store_history=False,
                user_expressions=user_expressions,
                allow_stdin=allow_stdin,
                cell_id=cell_id,
            )
            if reply_status_dump["status"] != "ok":
                self.log_error(KernelErrorCode.PERSISTENCE_DUMP_FAIL, direction="Jupyter -> Score-P")
                self.pershelper.postprocess()
                return reply_status_dump

        # Empty cell output, required for interactive output
        # e.g. tqdm for-loop progress bar
        self.cell_output("\0")

        stdout_lock = threading.Lock()
        process_busy_spinner = create_busy_spinner(stdout_lock)
        process_busy_spinner.start('Process is running...')

        multicellmode_timestamps = []

        try:
            multicellmode_timestamps = self.read_scorep_process_pipe(proc, stdout_lock)
            process_busy_spinner.stop('Done.')
        except KeyboardInterrupt:
            process_busy_spinner.stop('Kernel interrupted.')


        # for multiple nodes, we have to add more lists here, one list per node
        # this is required to be in line with the performance data aggregation
        # for the %%display_graph_for_all magic command, which does not have
        # explicit timestamps, but aligns the colorization of the plot based
        # on the number of perf measurements we have, which is individual per
        # node

        time_indices = None
        if len(multicellmode_timestamps):
            # retrieve the index this cell will have in the global history
            sub_idx = len(self.perfdata_handler.get_code_history())
            # append to have end of last code fragment
            multicellmode_timestamps.append("MCM_TS" + str(time.time()))
            time_indices = [[]]
            nb_ms = 0.0
            for idx, ts_string in enumerate(multicellmode_timestamps[:-1]):
                secs = float(multicellmode_timestamps[idx + 1][6:]) - float(
                    ts_string[6:]
                )
                nb_ms += secs / int(
                    os.environ.get("JUMPER_REPORT_FREQUENCY", 2)
                )
                if nb_ms >= 1.0:
                    # only consider if we have measurements
                    time_indices[0].append(
                        (str(sub_idx) + "_" + str(idx), nb_ms)
                    )
                    nb_ms %= 1.0
            # add time for last to last measurement

            if nb_ms >= 0.0:
                if len(time_indices[0]):
                    sub_idx, val = time_indices[0][-1]
                    time_indices[0][-1] = (sub_idx, val + nb_ms)
                else:
                    time_indices[0].append(
                        (str(sub_idx) + "_" + str(0), nb_ms)
                    )

            nb_ms = 0.0
            for idx, val in enumerate(time_indices[0]):
                sub_idx, ms = val
                nb_ms += ms % 1.0
                ms = int(ms)
                if nb_ms >= 1.0:
                    ms += 1
                    nb_ms %= 1.0
                time_indices[0][idx] = (sub_idx, ms)

        performance_data_nodes, duration = (
            self.perfdata_handler.end_perfmonitor()
        )

        # Check if the score-p process is running.
        # This prevents jupyter_update() from getting stuck while reading non-existent temporary files
        # if something goes wrong during process execution.
        if proc.poll():
            self.log_error(KernelErrorCode.SCOREP_SUBPROCESS_FAIL)
            self.pershelper.postprocess()
            return self.standard_reply()

        # os_environ_.clear()
        # sys_path_.clear()

        # In disk mode, subprocess already terminated
        # after dumping persistence to file
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
            self.log_error(KernelErrorCode.PERSISTENCE_LOAD_FAIL, direction=f"Score-P -> Jupyter")
            self.pershelper.postprocess()
            return reply_status_update

        # In memory mode, subprocess terminates once jupyter_update is
        # executed and pipe is closed
        if self.pershelper.mode == "memory":
            if proc.poll():
                self.pershelper.postprocess()
                self.log_error(KernelErrorCode.PERSISTENCE_LOAD_FAIL, direction="Score-P -> Jupyter")
                return self.standard_reply()

        # Determine directory to which trace files were saved by Score-P
        scorep_folder = ""
        if "SCOREP_EXPERIMENT_DIRECTORY" in os.environ:
            self.log.debug(f'{os.environ["SCOREP_EXPERIMENT_DIRECTORY"]=}')
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

        if performance_data_nodes:
            self.report_perfdata(performance_data_nodes, duration)
            self.perfdata_handler.append_code(
                datetime.datetime.now(), code, time_indices
            )
        return self.standard_reply()


    def read_scorep_process_pipe(self, proc: subprocess.Popen[bytes], stdout_lock: threading.Lock) -> list:
        """
        This function reads stdout and stderr of the subprocess running with Score-P instrumentation independently.
        It logs all stderr output, collects lines containing
        the marker "MCM_TS" (used to identify multi-cell mode timestamps) into a list, and sends the remaining
        stdout lines to the Jupyter cell output.

        Simultaneous access to stdout is synchronized via a lock to prevent overlapping with another thread performing
        long-running process animation.

        Args:
            proc (subprocess.Popen[bytes]): The subprocess whose output is being read.
            stdout_lock (threading.Lock): Lock to avoid output overlapping

        Returns:
            list: A list of decoded strings containing "MCM_TS" timestamps.
        """
        multicellmode_timestamps = []
        sel = selectors.DefaultSelector()

        sel.register(proc.stdout, selectors.EVENT_READ)
        sel.register(proc.stderr, selectors.EVENT_READ)

        line_width = 50
        clear_line = "\r" + " " * line_width + "\r"

        while True:
            # Select between stdout and stderr
            for key, val in sel.select():
                line = key.fileobj.readline()
                if not line:
                    sel.unregister(key.fileobj)
                    continue

                decoded_line = line.decode(sys.getdefaultencoding(), errors='ignore')

                if key.fileobj is proc.stderr:
                    with stdout_lock:
                        self.log.warning(f'{decoded_line.strip()}')
                elif 'MCM_TS' in decoded_line:
                    multicellmode_timestamps.append(decoded_line)
                else:
                    with stdout_lock:
                        sys.stdout.write(clear_line)
                        sys.stdout.flush()
                        self.cell_output(decoded_line)

            # If both stdout and stderr empty -> out of loop
            if not sel.get_map():
                break

        return multicellmode_timestamps


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

        """
        #displays all ran cell codes with index and timestamp
        %%display_code_all

        #displays code for index
        %%display_code_for_index i

        # displays graphs for last cell, arguments: cpu_util etc.
        %%display_graphs_for_last cpu_util, ...
        # displays one graph for all cell, arguments: cpu_util etc.
        %%display_graphs_for_all cpu_util, ...
        # -> displays performance data aggregated, indicates different cells
        # by color
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
            if not len(self.perfdata_handler.get_perfdata_history()):
                self.cell_output("No performance data available.")
            time_indices = self.perfdata_handler.get_time_indices()[-1]
            if time_indices:
                sub_idxs = [x[0] for x in time_indices[0]]
                self.cell_output(
                    f"Cell seemed to be tracked in multi cell"
                    " mode. Got performance data for the"
                    f" following sub cells: {sub_idxs}"
                )
            perfvis.draw_performance_graph(
                self.nodelist,
                self.perfdata_handler.get_perfdata_history()[-1],
                self.gpu_avail,
                time_indices,
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
                time_indices = self.perfdata_handler.get_time_indices()[index]
                if time_indices:
                    sub_idxs = [x[0] for x in time_indices[0]]
                    self.cell_output(
                        f"Cell seemed to be tracked in multi cell"
                        " mode. Got performance data for the"
                        f" following sub cells: {sub_idxs}"
                    )
                perfvis.draw_performance_graph(
                    self.nodelist,
                    self.perfdata_handler.get_perfdata_history()[index],
                    self.gpu_avail,
                    time_indices,
                )
            return self.standard_reply()
        elif code.startswith("%%display_graph_for_all"):
            data, time_indices = (
                self.perfdata_handler.get_perfdata_aggregated()
            )
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
                ).reset_index(),
                layout={"topStart": "search", "topEnd": None},
                columnDefs=[{"className": "dt-left", "targets": 2}],
            )
            return self.standard_reply()
        elif code.startswith("%%perfdata_to_variable"):
            if len(code.split(" ")) == 1:
                self.cell_output(
                    "No variable for export specified. Use: "
                    "%%perfdata_to_variable myvar",
                    "stdout",
                )
            else:
                varname = code.split(" ")[1]
                # for multi cell mode, we might have time indices which we want
                # to communicate to the user, each time_index has the index of
                # the overall mult cell and the sub index within this cell.
                # In addition, it has a counter for the number of measurements
                # each sub cell corresponds to in the list of performance data
                # measurements, e.g. (2_0, 5), (2_1, 3), (2_2, 7)
                mcm_time_indices = self.perfdata_handler.get_time_indices()
                mcm_time_indices = list(
                    filter(lambda item: item is not None, mcm_time_indices)
                )

                code = (
                    f"{varname}="
                    f"{self.perfdata_handler.get_perfdata_history()}"
                )

                if mcm_time_indices:
                    code += f"\n{varname}.append({mcm_time_indices})"

                await super().do_execute(code, silent=True)
                self.cell_output(
                    "Exported performance data to "
                    + str(varname)
                    + " variable. ",
                    "stdout",
                )
                if mcm_time_indices:
                    self.cell_output(
                        "Detected that cells were executed in multi cell mode."
                        + f"Last entry in {varname} is a list that contains "
                        f"the sub indices per cell that were executed in "
                        f"in multi cell mode and a counter for the number of"
                        f" performance measurements within this sub cell, "
                        f"e.g. f{mcm_time_indices[-1]}",
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
        elif code.startswith("%%scorep_python_binding_arguments"):
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
                    self.perfdata_handler.end_perfmonitor()
                )
                if performance_data_nodes:
                    self.report_perfdata(performance_data_nodes, duration)
                    self.perfdata_handler.append_code(
                        datetime.datetime.now(), code
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

    def log_error(self, code: KernelErrorCode, **kwargs):
        """
        Logs a kernel error with predefined error code and adds an extensible message format.

        Parameters:
            code (KernelErrorCode): error code to select message template from `KERNEL_ERROR_MESSAGES`.
            **kwargs: contextual fields for the error message template (e.g., active_kernel="jupyter").

            In addition to the dynamic arguments, the formatter always injects:
                - mode (str): PersHelper() mode (e.g. "memory")
                - marshaller (str): matshaller (e.g. "dill")
        """
        mode = self.pershelper.mode
        marshaller = self.pershelper.marshaller

        template = KERNEL_ERROR_MESSAGES.get(code, "Unknown error. Mode: {mode}, Marshaller: {marshaller}")
        message = template.format(
            mode=mode,
            marshaller=marshaller,
            **kwargs
        )

        self.log.error(message)
        self.cell_output("KernelError: " + message, "stderr")


if __name__ == "__main__":
    from ipykernel.kernelapp import IPKernelApp

    IPKernelApp.launch_instance(kernel_class=JumperKernel)
