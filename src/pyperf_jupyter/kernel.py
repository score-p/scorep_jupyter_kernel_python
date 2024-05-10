import codecs
import pickle

from ipykernel.ipkernel import IPythonKernel
import sys
import os
import subprocess
import re
import time
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

from itables import show
from datetime import datetime

# Create interactive widgets
from ipywidgets import interact, interactive, fixed, interact_manual
import ipywidgets as widgets
from IPython.display import display
from pyperf_jupyter.userpersistence import PersHelper, scorep_script_name
from enum import Enum
from textwrap import dedent

import pandas as pd
from functools import partial

from statistics import mean
import json
PYTHON_EXECUTABLE = sys.executable
READ_CHUNK_SIZE = 8
import json
import time
import pickle
import codecs
import matplotlib.pyplot as plt
from itables import show
import pandas as pd
from datetime import datetime
from pyperf_jupyter.userpersistence import extract_definitions, extract_variables_names

PYTHON_EXECUTABLE = sys.executable
READ_CHUNK_SIZE = 8
userpersistence_token = "pyperf_jupyter.userpersistence"
scorep_script_name = "scorep_script.py"
jupyter_dump = "jupyter_dump.pkl"
subprocess_dump = "subprocess_dump.pkl"

# kernel modes
class KernelMode(Enum):
    DEFAULT   = (0, 'default')
    MULTICELL = (1, 'multicell')
    WRITEFILE = (2, 'writefile')

    def __str__(self):
        return self.value[1]

class PyPerfKernel(IPythonKernel):
    implementation = 'Python and Score-P'
    implementation_version = '1.0'
    language = 'python'
    language_version = '3.8'
    language_info = {
        'name': 'python',
        'mimetype': 'text/plain',
        'file_extension': '.py',
    }
    banner = "Jupyter kernel for performance engineering."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        '''
        magics = super().shell.magics_manager.lsmagic()

        self.whitelist_prefixes_line = list(magics['line'].keys())
        self.whitelist_prefixes_cell = list(magics['cell'].keys())
        '''

        # setting the matplotlib backend
        super().shell.run_cell("%matplotlib inline", silent=True, store_history=False)
        super().shell.run_cell("%matplotlib widget", silent=True, store_history=False)

        # TODO: timeit, python, ...? do not save variables to globals()
        self.whitelist_prefixes_cell = ['%%prun', '%%timeit', '%%capture', '%%python', '%%pypy']
        self.whitelist_prefixes_line = ['%prun', '%time']

        self.blacklist_prefixes = ['%lsmagic']

        self.code_history = []
        self.performance_data_history = []

        self.scorep_binding_args = []
        self.scorep_env = {}

        os.environ['SCOREP_KERNEL_PERSISTENCE_DIR'] = './'
        self.pershelper = PersHelper('dill', 'memory')

        self.mode = KernelMode.DEFAULT

        self.multicell_cellcount = 0
        self.multicell_code = ""

        self.writefile_base_name = "jupyter_to_script"
        self.writefile_bash_name = ""
        self.writefile_python_name = ""
        self.writefile_scorep_env = []
        self.writefile_scorep_binding_args = []
        self.writefile_multicell = False

        self.slurm_nodelist = self.parse_slurm_nodelist(os.environ.get("SLURM_NODELIST", ''))
        if len(self.slurm_nodelist) <= 1:
            self.slurm_nodelist = None
        # will be set to True as soon as GPU data is received
        self.gpu_avail = False

    def cell_output(self, string, stream='stdout'):
        """
        Display string as cell output.
        """
        stream_content = {'name': stream, 'text': string}
        self.send_response(self.iopub_socket, 'stream', stream_content)

    def standard_reply(self):
        self.shell.execution_count += 1
        return {'status': 'ok',
                'execution_count': self.shell.execution_count - 1,
                'payload': [],
                'user_expressions': {},
                }


    def serializer_settings(self, code):
        """
        Switch serializer backend used for persistence in kernel.
        """
        if self.mode == KernelMode.DEFAULT:
            # Clean files/pipes before switching
            self.pershelper.postprocess()

            serializer_match = re.search(r'SERIALIZER=(\w+)', code.split('\n', 1)[1])
            mode_match = re.search(r'MODE=(\w+)', code.split('\n', 1)[1])
            serializer = serializer_match.group(1) if serializer_match else None
            mode = mode_match.group(1) if mode_match else None

            if serializer:
                if not self.pershelper.set_serializer(serializer):
                    self.cell_output(f"Serializer '{serializer}' is not recognized, kernel will use '{self.pershelper.serializer}'.", 'stderr')
                    return self.standard_reply()
            if mode:
                if not self.pershelper.set_mode(mode):
                    self.cell_output(f"Serialization mode '{mode}' is not recognized, kernel will use '{self.pershelper.mode}'.", 'stderr')

            self.cell_output(f"Kernel uses '{self.pershelper.serializer}' serializer in '{self.pershelper.mode}' mode.")
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()


    def set_scorep_env(self, code):
        """
        Read and record Score-P environment variables from the cell.
        """
        if self.mode == KernelMode.DEFAULT:
            for scorep_param in code.split('\n')[1:]:
                key, val = scorep_param.split('=')
                self.scorep_env[key] = val
            self.cell_output(
                'Score-P environment set successfully: ' + str(self.scorep_env))
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_scorep_env += code.split('\n')[1:]
            self.cell_output('Environment variables recorded.')
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def set_scorep_pythonargs(self, code):
        """
        Read and record Score-P Python binding arguments from the cell.
        """
        if self.mode == KernelMode.DEFAULT:
            self.scorep_binding_args += code.split('\n')[1:]
            self.cell_output(
                'Score-P Python binding arguments set successfully: ' + str(self.scorep_binding_args))
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_scorep_binding_args += code.split('\n')[1:]
            self.cell_output('Score-P bindings arguments recorded.')
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def enable_multicellmode(self):
        """
        Start multicell mode.
        """
        if self.mode == KernelMode.DEFAULT:
            self.mode = KernelMode.MULTICELL
            self.cell_output('Multicell mode enabled. The following cells will be marked for instrumented execution.')
        elif self.mode == KernelMode.MULTICELL:
            self.cell_output(f'KernelWarning: {KernelMode.MULTICELL} mode has already been enabled', 'stderr')
        elif self.mode == KernelMode.WRITEFILE:
            self.writefile_multicell = True
        return self.standard_reply()

    def append_multicellmode(self, code):
        """
        Append cell to multicell mode sequence.
        """
        if self.mode == KernelMode.MULTICELL:
            self.multicell_cellcount += 1
            max_line_len = max(len(line) for line in code.split('\n'))
            self.multicell_code += f"print('Executing cell {self.multicell_cellcount}')\n" + \
                                f"print('''{code}''')\n" + \
                                f"print('-' * {max_line_len})\n" + \
                                f"{code}\n" + \
                                f"print('''\n''')\n"
            self.cell_output(
                f'Cell marked for multicell mode. It will be executed at position {self.multicell_cellcount}')
        return self.standard_reply()

    def abort_multicellmode(self):
        """
        Cancel multicell mode.
        """
        if self.mode == KernelMode.MULTICELL:
            self.mode = KernelMode.DEFAULT
            self.multicell_code = ""
            self.multicell_cellcount = 0
            self.cell_output('Multicell mode aborted.')
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
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
            writefile_cmd = code.split('\n')[0].split(' ')
            if len(writefile_cmd) > 1:
                if writefile_cmd[1].endswith('.py'):
                    self.writefile_base_name = writefile_cmd[1][:-3]
                else:
                    self.writefile_base_name = writefile_cmd[1]
            self.writefile_bash_name = os.path.realpath('') + '/' + self.writefile_base_name + '_run.sh'
            self.writefile_python_name = os.path.realpath('') + '/' + self.writefile_base_name + '.py'

            with open(self.writefile_bash_name, 'w+') as bash_script:
                bash_script.write(dedent(f"""\
                                          # This bash script is generated automatically to run
                                          # Jupyter Notebook -> Python script conversion by Score-P kernel
                                          # {self.writefile_python_name}
                                          # !/bin/bash
                                          """))
            with open(self.writefile_python_name, 'w+') as python_script:
                python_script.write(dedent(f"""
                                            # This is the automatic Jupyter Notebook -> Python script conversion by Score-P kernel.
                                            # Code corresponding to the cells not marked for Score-P instrumentation
                                            # is framed "with scorep.instrumenter.disable()
                                            # The script can be run with proper settings using bash script
                                            # {self.writefile_bash_name}
                                            import scorep
                                            """))
            self.cell_output('Started converting to Python script. See files:\n' +
                            self.writefile_bash_name + '\n' + self.writefile_python_name + '\n')
        elif self.mode == KernelMode.WRITEFILE:
            self.cell_output(f'KernelWarning: {KernelMode.WRITEFILE} mode has already been enabled', 'stderr')
        else:
            self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def append_writefile(self, code, explicit_scorep):
        """
        Append cell to writefile.
        """
        if self.mode == KernelMode.WRITEFILE:
            if explicit_scorep or self.writefile_multicell:
                with open(self.writefile_python_name, 'a') as python_script:
                    python_script.write(code + '\n')
                self.cell_output('Python commands with instrumentation recorded.')
            else:
                with open(self.writefile_python_name, 'a') as python_script:
                    code = ''.join(['    ' + line + '\n' for line in code.split('\n')])
                    python_script.write('with scorep.instrumenter.disable():\n' + code + '\n')
                self.cell_output('Python commands without instrumentation recorded.')
        return self.standard_reply()

    def end_writefile(self):
        """
        Finish recording the notebook as a Python script.
        """
        # TODO: check for os path existence
        if self.mode == KernelMode.WRITEFILE:
            self.mode = KernelMode.DEFAULT
            with open(self.writefile_bash_name, 'a') as bash_script:
                bash_script.write(
                    f"{' '.join(self.writefile_scorep_env)} {PYTHON_EXECUTABLE} -m scorep {' '.join(self.writefile_scorep_binding_args)} {self.writefile_python_name}")
            self.cell_output('Finished converting to Python script.')
        else:
            self.cell_output(
                f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
        return self.standard_reply()

    def ghost_cell_error(self, reply_status, error_message):
        self.shell.execution_count += 1
        reply_status['execution_count'] = self.shell.execution_count - 1
        self.pershelper.postprocess()
        self.cell_output(error_message, 'stderr')


    def parse_slurm_nodelist(self, nodelist_string):
        nodes = []
        # Regular expression to match patterns like 'node[1-3],node5,node7'
        pattern = r'(\w+\[\d+-\d+\]|\w+|\d+)'
        matches = re.findall(pattern, nodelist_string)

        for match in matches:
            # Check if the match contains a range
            if '-' in match:
                node_range = match.split('[')
                prefix = node_range[0]
                start, end = map(int, re.findall(r'\d+', node_range[1]))
                nodes.extend([f"{prefix}{i}" for i in range(start, end + 1)])
            else:
                nodes.append(match)

        return nodes

    def get_perfdata_aggregated(self):
        perfdata_aggregated = []
        # for each node, initialize the list
        # index 0 in next row indicates, we are just checking the very first cell that was executed
        '''
        each line in performance_data_history represents a cell (code) that was executed
        each cell then looks like that:
        [raw data node0,
             raw data node1,
             raw data noden,
             CPU Mean across nodes,
             Mem Mean across nodes,
             IO OPS READ Mean across nodes,
             IO OPS WRITE Mean across nodes,
             IO Bytes READ Mean across nodes,
             IO Bytes WRITE Mean across nodes,
             GPU Util Mean across nodes,
             GPU Mem Mean across nodes]
        '''
        for node in range(0, len(self.performance_data_history[0])-8):
            perfdata_init = self.performance_data_history[0][node]
            # for each cpu and gpu, we need an empty list to be filled
            cpu_util = [[] for _ in perfdata_init[0]] if perfdata_init[0] else [[]]
            gpu_util = [[] for _ in perfdata_init[2]] if perfdata_init[2] else [[]]
            gpu_mem = [[] for _ in perfdata_init[2]] if perfdata_init[3] else [[]]
            mem_util = []
            io_ops_read = []
            io_ops_write = []
            io_bytes_read = []
            io_bytes_write = []
            perfdata_aggregated.append([cpu_util, mem_util, io_ops_read, io_ops_write, io_bytes_read, io_bytes_write,
                                        gpu_util, gpu_mem])

        # for each cell/code (called perfdata)...
        for perfdata in self.performance_data_history:
            # for each node in this cell/code
            for node in range(0,len(perfdata)-8):
                for cpu_index in range(0, len(perfdata[node][0])):
                    perfdata_aggregated[node][0][cpu_index].extend(perfdata[node][0][cpu_index])
                perfdata_aggregated[node][1].extend(perfdata[node][1])
                perfdata_aggregated[node][2].extend(perfdata[node][2])
                perfdata_aggregated[node][3].extend(perfdata[node][3])
                perfdata_aggregated[node][4].extend(perfdata[node][4])
                perfdata_aggregated[node][5].extend(perfdata[node][5])
                for gpu_index in range(0, len(perfdata[node][6])):
                    perfdata_aggregated[node][6][gpu_index].extend(perfdata[node][6][gpu_index])
                for gpu_index in range(0, len(perfdata[node][7])):
                    perfdata_aggregated[node][7][gpu_index].extend(perfdata[node][7][gpu_index])

        return perfdata_aggregated


    def plot_graph(self, ax, metric, perfdata):
        # first 0 means first node
        ax.clear()  # Clear previous plot
        #generate scale
        x_scale = [x for x in range(0, 2 * len(perfdata[0][0][-3]), int(os.environ.get("PYPERF_REPORT_FREQUENCY", 2)))]
        if metric == 'CPU Util (Min/Max/Mean)':
            ax.plot(x_scale, perfdata[0][0][-3], label='Mean', color=(0.20,0.47,1.00))
            ax.plot(x_scale, perfdata[0][0][-2], label='Max', color=(0.20,0.47,1.00, 0.3))
            ax.plot(x_scale, perfdata[0][0][-1], label='Min', color=(0.20,0.47,1.00, 0.3))
            ax.set_ylabel('Util (%)')
        elif metric == 'CPU Cores (Raw)':
            for cpu_index in range(0, len(perfdata[0][0])-3):
                ax.plot(x_scale, perfdata[0][0][cpu_index], label="CPU" + str(cpu_index))
            ax.set_ylabel('Util (%)')
        elif metric == 'Mem':
            ax.plot(x_scale, perfdata[0][1], label='Value', color=(0.12,0.70,0.00))
            ax.set_ylabel('Util (%)')
        elif metric == 'IO Ops':
            ax.plot(x_scale, perfdata[0][2], label='IO Read', color=(1.00,1.00,0.10))
            ax.plot(x_scale, perfdata[0][3], label='IO Write', color=(1.00,0.50,0.00))
            ax.set_ylabel('Ops')
        elif metric == 'IO Bytes':
            ax.plot(x_scale, perfdata[0][4], label='IO Read', color=(0.50,0.50,0.00))
            ax.plot(x_scale, perfdata[0][5], label='IO Write', color=(0.50,0.25,0.00))
            ax.set_ylabel('Bytes')
        elif metric == 'GPU Util':
            ax.plot(x_scale, perfdata[0][6][-3], label='Mean', color=(0.90,0.30,0.00))
            ax.plot(x_scale, perfdata[0][6][-2], label='Max', color=(0.90,0.30,0.00, 0.3))
            ax.plot(x_scale, perfdata[0][6][-1], label='Min', color=(0.90,0.30,0.00, 0.3))
            ax.set_ylabel('Util (%)')
        elif metric == 'GPU Mem':
            ax.plot(x_scale, perfdata[0][7][-3], label='Mean', color=(1.00,0.40,1.00))
            ax.plot(x_scale, perfdata[0][7][-2], label='Max', color=(1.00,0.40,1.00, 0.3))
            ax.plot(x_scale, perfdata[0][7][-1], label='Min', color=(1.00,0.40,1.00, 0.3))
            ax.set_ylabel('Util (%)')

        ax.set_title(f'{metric}')
        ax.set_xlabel('Time (s)')
        ax.legend()
        ax.grid(True)

    def plot_with_dropdowns(self, metrics, perfdata, metric_start):
        # Create subplots in a 1x2 grid
        fig, axes = plt.subplots(1, 2, figsize=(10, 3))
        dropdowns = []

        # Plot data and create dropdowns for each subplot
        for i, ax in enumerate(axes):
            self.plot_graph(ax, metrics[i+metric_start], perfdata)

            # Create dropdown widget for the current subplot
            dropdown = widgets.Dropdown(options=metrics, description='Metric:', value=metrics[i+metric_start])
            dropdown.observe(lambda change, ax=ax: self.plot_graph(ax, change['new'], perfdata), names='value')

            # Add dropdown to list
            dropdowns.append(dropdown)

        plt.tight_layout()
        plt.show()


    def draw_performance_graph(self, perfdata):

        if self.slurm_nodelist:
            nodelist = self.slurm_nodelist
            nodelist.insert(0, 'All')
            dropdown = widgets.Dropdown(
                options=nodelist,
                value='All',
                description='Number:',
                disabled=False,
            )
            display(dropdown)

        # Dropdown widget
        metrics = ['CPU Util (Min/Max/Mean)', 'CPU Cores (Raw)', 'Mem', 'IO Ops', 'IO Bytes']
        if self.gpu_avail:
            metrics.extend(["GPU Util", "GPU Mem"])

        button = widgets.Button(description="Add Display")
        output = widgets.Output()

        display(button, output)

        def on_button_clicked(b):
            with output:
                self.plot_with_dropdowns(metrics, perfdata, 0)

        button.on_click(on_button_clicked)

        self.plot_with_dropdowns(metrics, perfdata, 0)
        if self.gpu_avail:
            self.plot_with_dropdowns(metrics, perfdata, 2)




    def compute_mean_across_nodes(self, key1, key2, metrics_across_nodes):
        # use the first list
        mean_across_nodes = []
        for i in range(0,len(metrics_across_nodes[key1][key2][0])):
            mean = metrics_across_nodes[key1][key2][0][i]
            # check the values on the other lists, compute the mean and add
            for j in range(1,len(metrics_across_nodes[key1][key2])):
                mean+=metrics_across_nodes[key1][key2][j][i]
            mean_across_nodes.append(mean/len(metrics_across_nodes[key1][key2]))
        return mean_across_nodes

    def report_perfdata(self, stdout_data_node, duration, nodelist):

        # might be that parent process pushes to stdout and that output gets reversed
        # couldn't find a better way than waiting for 1s and hoping that outputs are in correct order in the queue now
        time.sleep(1)

        # parse the performance data
        performance_data_nodes = []
        metrics_across_nodes = {'CPU': {'MEANS': [],
                                'MAXS': [],
                                'MINS': []},
                        'MEM': {'MEANS': [],
                                'MAXS': [],
                                'MINS': []},
                        'GPU_UTIL': {'MEANS': [],
                                'MAXS': [],
                                'MINS': []},
                        'GPU_MEM': {'MEANS': [],
                                     'MAXS': [],
                                     'MINS': []},
                        'IO_OPS_READ': {'MEANS': [],
                                    'MAXS': [],
                                    'MINS': []},
                        'IO_OPS_WRITE': {'MEANS': [],
                                        'MAXS': [],
                                        'MINS': []},
                        'IO_BYTES_READ': {'MEANS': [],
                                         'MAXS': [],
                                         'MINS': []},
                        'IO_BYTES_WRITE': {'MEANS': [],
                                          'MAXS': [],
                                          'MINS': []},
                         }
        for stdout_data in stdout_data_node:
            stdout_data = stdout_data.split(b"\n\n")
            # init CPU and GPU lists
            mem_util = []
            io_ops_read = []
            io_ops_write = []
            io_bytes_read = []
            io_bytes_write = []
            if stdout_data[0]:
                init_data = pickle.loads(codecs.decode(stdout_data[0], "base64"))
                cpu_util = [[] for _ in init_data[0]]
                gpu_util = [[] for _ in init_data[2]]
                gpu_mem = [[] for _ in init_data[3]]

                # add empty lists for mean, max, min
                for i in range(0,3):
                    cpu_util.append([])
                    gpu_util.append([])
                    gpu_mem.append([])
            else:
                return False

            for line in stdout_data:
                if line == b'':
                    continue
                perf_data = pickle.loads(codecs.decode(line, "base64"))

                for cpu in range(0, len(perf_data[0])):
                    cpu_util[cpu].append(perf_data[0][cpu])

                last_measurements = [cpu_list[-1] for cpu_list in cpu_util[:-3]]
                cpu_util[-3].append(mean(last_measurements))
                cpu_util[-2].append(max(last_measurements))
                cpu_util[-1].append(min(last_measurements))


                mem_util.append(perf_data[1])
                #0 read counts, 1 write counts, 2 read bytes, 3 write bytes
                io_ops_read.append(perf_data[4][0])
                io_ops_write.append(perf_data[4][1])
                io_bytes_read.append(perf_data[4][2])
                io_bytes_write.append(perf_data[4][3])
                for gpu in range(0, len(perf_data[2])):
                    gpu_util[gpu].append(perf_data[2][gpu])
                    gpu_mem[gpu].append(perf_data[3][gpu])

                last_measurements = [gpu_list[-1] for gpu_list in gpu_util[:-3]]
                if last_measurements:
                    gpu_util[-3].append(mean(last_measurements))
                    gpu_util[-2].append(max(last_measurements))
                    gpu_util[-1].append(min(last_measurements))

                last_measurements = [gpu_list[-1] for gpu_list in gpu_mem[:-3]]
                if last_measurements:
                    gpu_mem[-3].append(mean(last_measurements))
                    gpu_mem[-2].append(max(last_measurements))
                    gpu_mem[-1].append(min(last_measurements))

            # TODO: discuss whether Means of Maxs are relevant or should we consider Mean of Means only?
            metrics_across_nodes["CPU"]["MEANS"].append(cpu_util[-3])
            metrics_across_nodes["MEM"]["MEANS"].append(mem_util)
            metrics_across_nodes["IO_OPS_READ"]["MEANS"].append(io_ops_read)
            metrics_across_nodes["IO_OPS_WRITE"]["MEANS"].append(io_ops_write)
            metrics_across_nodes["IO_BYTES_READ"]["MEANS"].append(io_bytes_read)
            metrics_across_nodes["IO_BYTES_WRITE"]["MEANS"].append(io_bytes_write)
            metrics_across_nodes["GPU_UTIL"]["MEANS"].append(gpu_util[-3])
            metrics_across_nodes["GPU_MEM"]["MEANS"].append(gpu_mem[-3])
            performance_data_nodes.append([cpu_util, mem_util, io_ops_read, io_ops_write, io_bytes_read, io_bytes_write, gpu_util, gpu_mem])

        # compute the mean, max, min across the nodes using pure mem_util lists, the mean, max and min lists of the other sensors
        performance_data_nodes.append(self.compute_mean_across_nodes("CPU", "MEANS", metrics_across_nodes))
        performance_data_nodes.append(self.compute_mean_across_nodes("MEM", "MEANS", metrics_across_nodes))
        performance_data_nodes.append(self.compute_mean_across_nodes("IO_OPS_READ", "MEANS", metrics_across_nodes))
        performance_data_nodes.append(self.compute_mean_across_nodes("IO_OPS_WRITE", "MEANS", metrics_across_nodes))
        performance_data_nodes.append(self.compute_mean_across_nodes("IO_BYTES_READ", "MEANS", metrics_across_nodes))
        performance_data_nodes.append(self.compute_mean_across_nodes("IO_BYTES_WRITE", "MEANS", metrics_across_nodes))
        performance_data_nodes.append(self.compute_mean_across_nodes("GPU_UTIL", "MEANS", metrics_across_nodes))
        performance_data_nodes.append(self.compute_mean_across_nodes("GPU_MEM", "MEANS", metrics_across_nodes))

        self.performance_data_history.append(performance_data_nodes)

        # print the performance data
        report_trs = int(os.environ.get("PYPERF_REPORTS_MIN", 2))

        #just count the number of memory measurements to decide whether we want to print the information
        if len(performance_data_nodes[0][1]) > report_trs:

            self.cell_output("\n----Performance Data----\n", 'stdout')
            self.cell_output("Duration: " + "{:.2f}".format(duration) + "\n", 'stdout')
            # last 4 values are means across nodes, print them separately

            '''
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
            '''

            for idx, performance_data in enumerate(performance_data_nodes[:-8]):

                if nodelist:
                    self.cell_output("--NODE " + str(nodelist[idx]) + "--\n", 'stdout')

                cpu_util = performance_data[0]
                mem_util = performance_data[1]
                io_ops_read = performance_data[2]
                io_ops_write = performance_data[3]
                io_bytes_read = performance_data[4]
                io_bytes_write = performance_data[5]
                gpu_util = performance_data[6]
                gpu_mem = performance_data[7]


                if cpu_util:
                    #self.cell_output("--CPU Util--\n", 'stdout')
                    self.cell_output(
                        "\nCPU Util    \tAVG: " + "{:.2f}".format(
                            mean(cpu_util[-3])) + "\t MIN: " + "{:.2f}".format(
                            min(cpu_util[-1])) + "\t MAX: " + "{:.2f}".format(max(cpu_util[-2])) + "\n", 'stdout')

                if len(mem_util) > 0:
                    self.cell_output(
                        "Mem Util    \tAVG: " + "{:.2f}".format(
                            mean(mem_util)) + "\t MIN: " + "{:.2f}".format(
                            min(mem_util)) + "\t MAX: " + "{:.2f}".format(max(mem_util)) + "\n", 'stdout')

                if len(io_ops_read) > 0:
                    self.cell_output(
                        "IO Ops(R)   \tAVG: " + "{:.2f}".format(
                            mean(io_ops_read)) + "\t MIN: " + "{:.2f}".format(
                            min(io_ops_read)) + "\t MAX: " + "{:.2f}".format(max(io_ops_read)) + "\n", 'stdout')

                if len(io_ops_write) > 0:
                    self.cell_output(
                        "      (W)   \tAVG: " + "{:.2f}".format(
                            mean(io_ops_write)) + "\t MIN: " + "{:.2f}".format(
                            min(io_ops_write)) + "\t MAX: " + "{:.2f}".format(max(io_ops_write)) + "\n", 'stdout')

                if len(io_bytes_read) > 0:
                    self.cell_output(
                        "IO Bytes(R) \tAVG: " + "{:.2f}".format(
                            mean(io_bytes_read)) + "\t MIN: " + "{:.2f}".format(
                            min(io_bytes_read)) + "\t MAX: " + "{:.2f}".format(max(io_bytes_read)) + "\n", 'stdout')

                if len(io_bytes_write) > 0:
                    self.cell_output(
                        "        (W) \tAVG: " + "{:.2f}".format(
                            mean(io_bytes_write)) + "\t MIN: " + "{:.2f}".format(
                            min(io_bytes_write)) + "\t MAX: " + "{:.2f}".format(max(io_bytes_write)) + "\n", 'stdout')

                if gpu_util[0] and gpu_mem[0]:
                    self.gpu_avail = True
                    self.cell_output("--GPU Util and Mem per GPU--\n", 'stdout')
                    self.cell_output(
                        "GPU Util \tAVG: " + "{:.2f}".format(
                            mean(gpu_util[-3])) + "\t MIN: " + "{:.2f}".format(
                            min(gpu_util[-1])) + "\t MAX: " + "{:.2f}".format(max(gpu_util[-2])) + "\n", 'stdout')
                    self.cell_output("\t    " +
                                     "\tMem AVG: " + "{:.2f}".format(
                        mean(gpu_mem[-3])) + "\t MIN: " + "{:.2f}".format(
                        min(gpu_mem[-1])) + "\t MAX: " + "{:.2f}".format(max(gpu_mem[-2])) + "\n",
                                     'stdout')

            '''
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
            '''
            '''
            if len(performance_data_nodes)-8 > 1:
                self.cell_output("\n---Across Nodes---\n", 'stdout')

                self.cell_output(
                    "\n--CPU Util-- \tAVG: " + "{:.2f}".format(
                        mean(performance_data_nodes[-4])) + "\t MIN: " + "{:.2f}".format(
                        min(performance_data_nodes[-4])) + "\t MAX: " + "{:.2f}".format(max(performance_data_nodes[-4])) + "\n", 'stdout')

                if performance_data_nodes[-3]:
                    self.cell_output(
                        "--Mem Util-- \tAVG: " + "{:.2f}".format(
                            mean(performance_data_nodes[-3])) + "\t MIN: " + "{:.2f}".format(
                            min(performance_data_nodes[-3])) + "\t MAX: " + "{:.2f}".format(
                            max(performance_data_nodes[-3])) + "\n", 'stdout')

                if performance_data_nodes[-2] and performance_data_nodes[-1]:
                    self.cell_output("--GPU Util and Mem per GPU--\n", 'stdout')
                    self.cell_output(
                        "--GPU Util-- \tAVG: " + "{:.2f}".format(
                            mean(performance_data_nodes[-2])) + "\t MIN: " + "{:.2f}".format(
                            min(performance_data_nodes[-2])) + "\t MAX: " + "{:.2f}".format(max(performance_data_nodes[-2])) + "\n", 'stdout')
                    self.cell_output("\t    " +
                                     "\tMem AVG: " + "{:.2f}".format(
                        mean(performance_data_nodes[-1])) + "\t MIN: " + "{:.2f}".format(
                        min(performance_data_nodes[-1])) + "\t MAX: " + "{:.2f}".format(max(performance_data_nodes[-1])) + "\n",
                                     'stdout')
            '''

            return True
        else:
            return False

    async def scorep_execute(self, code, silent, store_history=True, user_expressions=None,
                             allow_stdin=False, *, cell_id=None):
        """
        Execute given code with Score-P Python bindings instrumentation.
        """
        # Set up files/pipes for persistence communication
        if not self.pershelper.preprocess():
            self.pershelper.postprocess()
            self.cell_output("KernelError: Failed to set up the persistence communication files/pipes.", "stderr")
            return self.standard_reply()

        # Prepare code for the Score-P instrumented execution as subprocess
        # Transmit user persistence and updated sys.path from Jupyter notebook to subprocess
        # After running the code, transmit subprocess persistence back to Jupyter notebook
        with open(scorep_script_name, 'w') as file:
            file.write(self.pershelper.subprocess_wrapper(code))

        # For disk mode use implicit synchronization between kernel and subprocess:
        # await jupyter_dump, subprocess.wait(), await jupyter_update
        # Ghost cell - dump current Jupyter session for subprocess
        # Run in a "silent" way to not increase cells counter
        if self.pershelper.mode == 'disk':
            reply_status_dump = await super().do_execute(self.pershelper.jupyter_dump(), silent, store_history=False,
                                                    user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)
            if reply_status_dump['status'] != 'ok':
                self.ghost_cell_error(reply_status_dump, "KernelError: Failed to pickle notebook's persistence.")
                return reply_status_dump
            
        # Launch subprocess with Jupyter notebook environment
        cmd = [PYTHON_EXECUTABLE, "-m", "scorep"] + \
            self.scorep_binding_args + [scorep_script_name]
        proc_env = self.scorep_env.copy()
        proc_env.update({'PATH': os.environ['PATH'], 'PYTHONUNBUFFERED': 'x'}) # scorep path, subprocess observation
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=proc_env)
        
        # For memory mode jupyter_dump and jupyter_update must be awaited
        # concurrently to the running subprocess
        if self.pershelper.mode == 'memory':
            reply_status_dump = await super().do_execute(self.pershelper.jupyter_dump(), silent, store_history=False,
                                                        user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)
            if reply_status_dump['status'] != 'ok':
                self.ghost_cell_error(reply_status_dump, "KernelError: Failed to pickle notebook's persistence.")
                return reply_status_dump

        # Redirect process stderr to stdout and observe the latter
        # Observing two stream with two threads causes interference in cell_output in Jupyter notebook
        # stdout is read in chunks, which are split into lines using \r or \n as delimiter
        # Last element in the list might be "incomplete line", not ending with \n or \r, it is saved
        # and merged with the first line in the next chunk
        incomplete_line = ''
        endline_pattern = re.compile(r'(.*?[\r\n]|.+$)')
        # Empty cell output, required for interactive output e.g. tqdm for-loop progress bar
        self.cell_output('\0')
        while True:
            chunk = b'' + proc.stdout.read(READ_CHUNK_SIZE)
            if chunk == b'':
                break
            chunk = chunk.decode(sys.getdefaultencoding(), errors='ignore')
            lines = endline_pattern.findall(chunk)
            if len(lines) > 0:
                lines[0] = incomplete_line + lines[0]
                if lines[-1][-1] not in ['\n', '\r']:
                    incomplete_line = lines.pop(-1)
                else:
                    incomplete_line = ""
                for line in lines:
                    self.cell_output(line)

        # In disk mode, subprocess already terminated after dumping persistence to file
        if self.pershelper.mode == 'disk':
            if proc.returncode:
                self.pershelper.postprocess()
                self.cell_output('KernelError: Cell execution failed, cell persistence was not recorded.', 'stderr')
                return self.standard_reply()
            
        # os_environ_.clear()
        # sys_path_.clear()

        # Ghost cell - load subprocess persistence back to Jupyter notebook
        # Run in a "silent" way to not increase cells counter
        reply_status_update = await super().do_execute(self.pershelper.jupyter_update(code), silent, store_history=False,
                                                    user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)
        if reply_status_update['status'] != 'ok':
            self.ghost_cell_error(reply_status_update, "KernelError: Failed to load cell's persistence to the notebook.")
            return reply_status_update
        
        # In memory mode, subprocess terminates once jupyter_update is executed and pipe is closed
        if self.pershelper.mode == 'memory':
            if proc.returncode:
                self.pershelper.postprocess()
                self.cell_output('KernelError: Cell execution failed, cell persistence was not recorded.', 'stderr')
                return self.standard_reply()

        # Determine directory to which trace files were saved by Score-P
        if 'SCOREP_EXPERIMENT_DIRECTORY' in self.scorep_env:
            scorep_folder = self.scorep_env['SCOREP_EXPERIMENT_DIRECTORY']
            self.cell_output(
                f"Instrumentation results can be found in {scorep_folder}")
        else:
            # Find last creasted directory with scorep* name
            # TODO: Directory isn't created locally when running scorep-collector
            scorep_dirs = [d for d in os.listdir('.') if os.path.isdir(d) and 'scorep' in d]
            if scorep_dirs:
                scorep_folder = max(scorep_dirs, key=os.path.getmtime)
                self.cell_output(
                    f"Instrumentation results can be found in {os.getcwd()}/{scorep_folder}")
            else:
                self.cell_output("KernelWarning: Instrumentation results were not saved locally.", 'stderr')

        self.pershelper.postprocess()
        return self.standard_reply()

    async def do_execute(self, code, silent, store_history=False, user_expressions=None,
                         allow_stdin=False, *, cell_id=None):
        """
        Override of do_execute() method of IPythonKernel. If no custom magic commands specified,
        execute cell with super().do_execute(), else save Score-P environment/binding arguments/
        execute cell with Score-P Python binding.
        """

        '''
        #displays all ran cell codes with index and timestamp
        %%display_code_all

        #displays code for index
        %%display_code_for_index i

        # displays graphs for last cell, arguments: cpu_util etc.
        %%display_graphs_for_last cpu_util, ...
        # displays one graph for all cell, arguments: cpu_util etc.
        %%display_graphs_for_all cpu_util, ...
        # -> would be cool if we can hover the graph and per timepoint, we see the index of the cell
        # displays graph for index cell, arguments: cpu_util etc.
        %%display_graphs_for_index i cpu_util, ...
        '''
        '''
        if code.startswith('%%display_graph_for_last'):
            metrics = code.split(' ')
            nmetrics = len(metrics) - 1
            self.draw_performance_graph(self.get_perfdata_index(-1, metrics[1:]), nmetrics)
            return self.standard_reply()
        '''
        if code.startswith('%%display_graph_for_last'):
            self.draw_performance_graph(self.performance_data_history[-1])
            return self.standard_reply()
        elif code.startswith('%%display_graph_for_index'):
            if len(code.split(' '))==1:
                self.cell_output("No index specified. Use: %%display_graph_for_index index", 'stdout')
            index = int(code.split(' ')[1])
            if index>=len(self.performance_data_history):
                self.cell_output("Tracked only "+ str(len(self.performance_data_history)) +" cells. This index is not available.")
            else:
                self.draw_performance_graph(self.performance_data_history[index])
            return self.standard_reply()
        elif code.startswith('%%display_graph_for_all'):
            self.draw_performance_graph(self.get_perfdata_aggregated())
            return self.standard_reply()

        elif code.startswith('%%display_code_for_index'):
            if len(code.split(' '))==1:
                self.cell_output("No index specified. Use: %%display_code_for_index index", 'stdout')
            index = int(code.split(' ')[1])
            if index >= len(self.performance_data_history):
                self.cell_output("Tracked only "+ str(len(self.performance_data_history)) +" cells. This index is not available.")
            else:
                self.cell_output("Cell timestamp: " + str(self.code_history[index][0]) + "\n--\n", 'stdout')
                self.cell_output(self.code_history[index][1], 'stdout')
            return self.standard_reply()
        elif code.startswith('%%display_code_history'):
            show(pd.DataFrame(self.code_history, columns=["timestamp", "code"]).reset_index())
            return self.standard_reply()
        elif code.startswith('%%perfdata_to_variable'):
            if len(code.split(' '))==1:
                self.cell_output("No variable to export specified. Use: %%perfdata_to_variable myvar", 'stdout')
            else:
                varname = code.split(' ')[1]
                await super().do_execute(f"{varname}={self.performance_data_history}", silent=True)
                self.cell_output("Exported performance data to " + str(varname) + " variable", 'stdout')
            return self.standard_reply()
        elif code.startswith('%%perfdata_to_json'):
            if len(code.split(' '))==1:
                self.cell_output("No filename to export specified. Use: %%perfdata_to_variable myfile", 'stdout')
            else:
                filename = code.split(' ')[1]
                with open(f'{filename}_perfdata.json', 'w') as f:
                    json.dump(self.performance_data_history, default=str, fp=f)
                with open(f'{filename}_code.json', 'w') as f:
                    json.dump(self.code_history, default=str, fp=f)
                self.cell_output("Exported performance data to " +
                                 str(filename) + "_perfdata.json and " + str(filename) + "_code.json", 'stdout')
            return self.standard_reply()
        elif code.startswith('%%scorep_env'):
            return self.set_scorep_env(code)
        elif code.startswith('%%scorep_python_binding_arguments'):
            return self.set_scorep_pythonargs(code)
        elif code.startswith('%%serializer_settings'):
            return self.serializer_settings(code)
        elif code.startswith('%%enable_multicellmode'):
            return self.enable_multicellmode()
        elif code.startswith('%%abort_multicellmode'):
            return self.abort_multicellmode()

        elif code.startswith('%%finalize_multicellmode'):
            # Cannot be put into a separate function due to tight coupling between do_execute and scorep_execute
            if self.mode == KernelMode.MULTICELL:
                self.mode = KernelMode.DEFAULT
                try:
                    reply_status = await self.scorep_execute(self.multicell_code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
                except:
                    self.cell_output("KernelError: Multicell execution failed.", 'stderr')
                    return self.standard_reply()
                self.multicell_code = ""
                self.multicell_cellcount = 0
                return reply_status
            elif self.mode == KernelMode.WRITEFILE:
                self.writefile_multicell = False
                return self.standard_reply()
            else:
                self.cell_output(f'KernelWarning: Currently in {self.mode}, command ignored.', 'stderr')
                return self.standard_reply()
        elif code.startswith('%%start_writefile'):
            return self.start_writefile(code)
        elif code.startswith('%%end_writefile'):
            return self.end_writefile()
        elif code.startswith('%%execute_with_scorep'):
            if self.mode == KernelMode.DEFAULT:
                return await self.scorep_execute(code.split("\n", 1)[1], silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
            elif self.mode == KernelMode.MULTICELL:
                return self.append_multicellmode(magics_cleanup(code.split("\n", 1)[1]))
            elif self.mode == KernelMode.WRITEFILE:
                return self.append_writefile(magics_cleanup(code.split("\n", 1)[1]), explicit_scorep=True)
        else:
            if self.mode == KernelMode.DEFAULT:
                self.pershelper.parse(magics_cleanup(code), 'jupyter')
                return await super().do_execute(code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
            elif self.mode == KernelMode.MULTICELL:
                return self.append_multicellmode(magics_cleanup(code))
            elif self.mode == KernelMode.WRITEFILE:
                return self.append_writefile(magics_cleanup(code), explicit_scorep=False)
            self.pershelper.parse(code, 'jupyter')

            # for code without scorep, we are interested in performance data
            # start a subprocess that tracks the performance data
            proc_env = os.environ.copy()
            proc_env.update({'PYTHONUNBUFFERED': 'x'})


            if self.slurm_nodelist:
                # SLURM is available, use srun to get output for all the nodes
                # until first \n we would like to get the hostname
                perf_proc = subprocess.Popen(["srun", "hostname", "&&", "echo", "PERFDATA", "&&",
                                              sys.executable, "-m" "perfmonitor"],
                                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=proc_env)
            else:
                # SLURM is not available, sorry we support only one node
                perf_proc = subprocess.Popen([sys.executable, "-m" "perfmonitor"], stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, env=proc_env)


            start = time.perf_counter()
            parent_ret = await super().do_execute(code, silent, store_history, user_expressions, allow_stdin,
                                                  cell_id=cell_id)
            duration = time.perf_counter() - start

            perf_proc.kill()
            output, _ = perf_proc.communicate()

            stdout_data_node = []
            '''
            if self.slurm_nodelist:
                output.split(b"PERFDATA")
                for proc in node_subproc:
                    proc.kill()
                    output, _ = proc.communicate()
                    stdout_data_node.append(output)
            else:
                stdout_data_node.append(output)
            '''
            stdout_data_node.append(output)

            # parse the performance data from the stdout pipe of the subprocess and print the performance data
            if self.report_perfdata(stdout_data_node, duration, self.slurm_nodelist):
                self.code_history.append([datetime.now(), code])
            return parent_ret

    def do_shutdown(self, restart):
        self.pershelper.postprocess()
        return super().do_shutdown(restart)


if __name__ == '__main__':
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=PyPerfKernel)