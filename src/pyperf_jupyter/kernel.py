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

    def get_perfdata_index(self, index, metrics):
        cpu_util = self.performance_data_history[index][0] if "cpu_util" in metrics else [[]]
        mem_util = self.performance_data_history[index][1] if "mem_util" in metrics else []
        gpu_util = self.performance_data_history[index][2] if "gpu_util" in metrics else [[]]
        gpu_mem = self.performance_data_history[index][3] if "gpu_mem" in metrics else [[]]

        return cpu_util, mem_util, gpu_util, gpu_mem

    def get_perfdata_aggregated(self, metrics):
        perfdata_init = self.performance_data_history[0]
        # for each cpu and gpu, we need an empty list to be filled
        cpu_util = [[] for _ in perfdata_init[0]] if perfdata_init[0] else [[]]
        gpu_util = [[] for _ in perfdata_init[2]] if perfdata_init[2] else [[]]
        gpu_mem = [[] for _ in perfdata_init[2]] if perfdata_init[3] else [[]]
        mem_util = []

        for perfdata in self.performance_data_history:
            if "cpu_util" in metrics:
                for cpu_index in range(0, len(perfdata[0])):
                    cpu_util[cpu_index].extend(perfdata[0][cpu_index])
            if "mem_util" in metrics:
                mem_util.extend(perfdata[1])
            if "gpu_util" in metrics:
                for gpu_index in range(0, len(perfdata[2])):
                    gpu_util[gpu_index].extend(perfdata[2][gpu_index])
            if "gpu_mem" in metrics:
                for gpu_index in range(0, len(perfdata[3])):
                    gpu_mem[gpu_index].extend(perfdata[3][gpu_index])

        return cpu_util, mem_util, gpu_util, gpu_mem


    def plot_graph(self, ax, metric, perfdata):
        # first 0 means first node
        ax.clear()  # Clear previous plot
        if metric == 'CPU Util':
            ax.plot(perfdata[0][0][-3], label='Mean', color=(0.20,0.47,1.00))
            ax.plot(perfdata[0][0][-2], label='Max', color=(0.20,0.47,1.00, 0.3))
            ax.plot(perfdata[0][0][-1], label='Min', color=(0.20,0.47,1.00, 0.3))
        elif metric == 'Mem':
            ax.plot(perfdata[0][1], label='Value', color=(0.12,0.70,0.00))
        elif metric == 'GPU Util':
            ax.plot(perfdata[0][2][-3], label='Mean', color=(0.90,0.30,0.00))
            ax.plot(perfdata[0][2][-2], label='Max', color=(0.90,0.30,0.00, 0.3))
            ax.plot(perfdata[0][2][-1], label='Min', color=(0.90,0.30,0.00, 0.3))
        elif metric == 'GPU Mem':
            ax.plot(perfdata[0][3][-3], label='Mean', color=(1.00,0.40,1.00))
            ax.plot(perfdata[0][3][-2], label='Max', color=(1.00,0.40,1.00, 0.3))
            ax.plot(perfdata[0][3][-1], label='Min', color=(1.00,0.40,1.00, 0.3))

        ax.set_title(f'{metric}')
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Util (%)')
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

        # Display dropdowns and plots
        display(widgets.HBox(dropdowns, layout=widgets.Layout(margin='0 0', padding='0px 15%')))
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
        metrics = ['CPU Util', 'Mem']
        if self.gpu_avail:
            metrics.extend(["GPU Util", "GPU Mem"])

        self.plot_with_dropdowns(metrics, perfdata, 0)
        if self.gpu_avail:
            self.plot_with_dropdowns(metrics, perfdata, 2)

        '''
        cpudata = perfdata[0]
        memdata = perfdata[1]
        gpudata_util = perfdata[2]
        gpudata_mem = perfdata[3]

        plt.rcParams["figure.figsize"] = (10, 2.5)

        if nmetrics == 1:
            plt.rcParams["figure.figsize"] = (5, 2.5)

        if nmetrics:
            # Create a figure and axis
            if nmetrics < 3:
                fig, axs = plt.subplots(1, nmetrics)
                if nmetrics == 1:
                    axs = [axs]
            else:
                # TODO: up to now we have max only 4, if we get more adjust here
                fig, axs = plt.subplots(2, 2)
            fig.tight_layout(w_pad=5.0)
            n = 0
            if cpudata[0]:
                axs[n].set_title('CPU Util')
                axs[n].set_xlabel('time')
                axs[n].set_ylabel('util %')

                # Plot the data
                for cpu_index in range(0, len(cpudata)):
                    axs[n].plot(cpudata[cpu_index], label="CPU" + str(cpu_index))

                axs[n].legend()
                n += 1
            if memdata:
                # Create a figure and axis
                # fig1, ax1 = plt.subplots()
                axs[n].set_title('Memory Util')
                axs[n].set_xlabel('time')
                axs[n].set_ylabel('util %')

                # Plot the data
                axs[n].plot(memdata)
                n += 1
            if gpudata_util and gpudata_util[0]:
                axs[n].set_title('GPU Util')
                axs[n].set_xlabel('time')
                axs[n].set_ylabel('util %')

                # Plot the data
                for gpu_index in range(0, len(gpudata_util)):
                    axs[n].plot(gpudata_util[gpu_index], label="GPU" + str(gpu_index))

                axs[n].legend()
                n += 1
            if gpudata_mem[0]:
                axs[n].set_title('GPU Memory')
                axs[n].set_xlabel('time')
                axs[n].set_ylabel('util %')

                # Plot the data
                for gpu_index in range(0, len(gpudata_mem)):
                    axs[n].plot(gpudata_mem[gpu_index], label="CPU" + str(gpu_index))

                axs[n].legend()
                n += 1
            plt.show()
        '''
    '''
    def draw_performance_graph(self, perfdata, nmetrics):
        cpudata = perfdata[0]
        memdata = perfdata[1]
        gpudata_util = perfdata[2]
        gpudata_mem = perfdata[3]

        plt.rcParams["figure.figsize"] = (10, 2.5)

        if nmetrics == 1:
            plt.rcParams["figure.figsize"] = (5, 2.5)

        if nmetrics:
            # Create a figure and axis
            if nmetrics < 3:
                fig, axs = plt.subplots(1, nmetrics)
                if nmetrics == 1:
                    axs = [axs]
            else:
                # TODO: up to now we have max only 4, if we get more adjust here
                fig, axs = plt.subplots(2, 2)
            fig.tight_layout(w_pad=5.0)
            n = 0
            if cpudata[0]:
                axs[n].set_title('CPU Util')
                axs[n].set_xlabel('time')
                axs[n].set_ylabel('util %')

                # Plot the data
                for cpu_index in range(0, len(cpudata)):
                    axs[n].plot(cpudata[cpu_index], label="CPU" + str(cpu_index))

                axs[n].legend()
                n += 1
            if memdata:
                # Create a figure and axis
                # fig1, ax1 = plt.subplots()
                axs[n].set_title('Memory Util')
                axs[n].set_xlabel('time')
                axs[n].set_ylabel('util %')

                # Plot the data
                axs[n].plot(memdata)
                n += 1
            if gpudata_util and gpudata_util[0]:
                axs[n].set_title('GPU Util')
                axs[n].set_xlabel('time')
                axs[n].set_ylabel('util %')

                # Plot the data
                for gpu_index in range(0, len(gpudata_util)):
                    axs[n].plot(gpudata_util[gpu_index], label="GPU" + str(gpu_index))

                axs[n].legend()
                n += 1
            if gpudata_mem[0]:
                axs[n].set_title('GPU Memory')
                axs[n].set_xlabel('time')
                axs[n].set_ylabel('util %')

                # Plot the data
                for gpu_index in range(0, len(gpudata_mem)):
                    axs[n].plot(gpudata_mem[gpu_index], label="CPU" + str(gpu_index))

                axs[n].legend()
                n += 1
            plt.show()
    '''
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

    def report_perfdata(self, stdout_data, duration):
        if nmetrics == 1:
            plt.rcParams["figure.figsize"] = (5, 2.5)

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
                         }
        for stdout_data in stdout_data_node:
            stdout_data = stdout_data.split(b"\n\n")
            # init CPU and GPU lists
            mem_util = []
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
            metrics_across_nodes["GPU_UTIL"]["MEANS"].append(gpu_util[-3])
            metrics_across_nodes["GPU_MEM"]["MEANS"].append(gpu_mem[-3])
            performance_data_nodes.append([cpu_util, mem_util, gpu_util, gpu_mem])

        # compute the mean, max, min across the nodes using pure mem_util lists, the mean, max and min lists of the other sensors
        performance_data_nodes.append(self.compute_mean_across_nodes("CPU", "MEANS", metrics_across_nodes))
        performance_data_nodes.append(self.compute_mean_across_nodes("MEM", "MEANS", metrics_across_nodes))
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

            for idx, performance_data in enumerate(performance_data_nodes[:-4]):

                if nodelist:
                    self.cell_output("--NODE " + str(nodelist[idx]) + "--\n", 'stdout')

                cpu_util = performance_data[0]
                mem_util = performance_data[1]
                gpu_util = performance_data[2]
                gpu_mem = performance_data[3]

                if cpu_util:
                    #self.cell_output("--CPU Util--\n", 'stdout')
                    self.cell_output(
                        "\n--CPU Util-- \tAVG: " + "{:.2f}".format(
                            mean(cpu_util[-3])) + "\t MIN: " + "{:.2f}".format(
                            min(cpu_util[-1])) + "\t MAX: " + "{:.2f}".format(max(cpu_util[-2])) + "\n", 'stdout')
                    '''
                    for cpu_index in range(0, len(cpu_util)):
                        self.cell_output("\tCPU" + str(cpu_index) + "\tAVG: " + "{:.2f}".format(
                            sum(cpu_util[cpu_index]) / len(cpu_util[cpu_index])) + "\t MIN: " + "{:.2f}".format(
                            min(cpu_util[cpu_index])) + "\t MAX: " + "{:.2f}".format(max(cpu_util[cpu_index])) + "\n",
                                         'stdout')
                    '''
                if len(mem_util) > 0:
                    self.cell_output(
                        "--Mem Util-- \tAVG: " + "{:.2f}".format(
                            mean(mem_util)) + "\t MIN: " + "{:.2f}".format(
                            min(mem_util)) + "\t MAX: " + "{:.2f}".format(max(mem_util)) + "\n", 'stdout')

                if gpu_util[0] and gpu_mem[0]:
                    self.gpu_avail = True
                    self.cell_output("--GPU Util and Mem per GPU--\n", 'stdout')
                    self.cell_output(
                        "--GPU Util-- \tAVG: " + "{:.2f}".format(
                            mean(gpu_util[-3])) + "\t MIN: " + "{:.2f}".format(
                            min(gpu_util[-1])) + "\t MAX: " + "{:.2f}".format(max(gpu_util[-2])) + "\n", 'stdout')
                    self.cell_output("\t    " +
                                     "\t Mem AVG: " + "{:.2f}".format(
                        mean(gpu_mem[-3])) + "\t MIN: " + "{:.2f}".format(
                        min(gpu_mem[-1])) + "\t MAX: " + "{:.2f}".format(max(gpu_mem[-2])) + "\n",
                                     'stdout')
                    '''
                    for gpu_index in range(0, len(gpu_util)):
                        self.cell_output("\tGPU" + str(gpu_index) +
                                         "\tUtil AVG: " + "{:.2f}".format(
                            sum(gpu_util[gpu_index]) / len(gpu_util[gpu_index])) + "\t MIN: " + "{:.2f}".format(
                            min(gpu_util[gpu_index])) + "\t MAX: " + "{:.2f}".format(max(gpu_util[gpu_index])) + "\n",
                                         'stdout')
                        self.cell_output("\t    " +
                                         "\t Mem AVG: " + "{:.2f}".format(
                            sum(gpu_mem[gpu_index]) / len(gpu_mem[gpu_index])) + "\t MIN: " + "{:.2f}".format(
                            min(gpu_mem[gpu_index])) + "\t MAX: " + "{:.2f}".format(max(gpu_mem[gpu_index])) + "\n",
                                         'stdout')
                    '''

            if len(performance_data_nodes[-4]) > 1:
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
                                     "\t Mem AVG: " + "{:.2f}".format(
                        mean(performance_data_nodes[-1])) + "\t MIN: " + "{:.2f}".format(
                        min(performance_data_nodes[-1])) + "\t MAX: " + "{:.2f}".format(max(performance_data_nodes[-1])) + "\n",
                                     'stdout')

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
            metrics = code.split(' ')
            nmetrics = len(metrics) - 1
            self.draw_performance_graph(self.performance_data_history[-1])
            return self.standard_reply()
        elif code.startswith('%%display_graph_for_index'):
            metrics = code.split(' ')
            nmetrics = len(metrics) - 2
            self.draw_performance_graph(self.get_perfdata_index(int(metrics[1]), metrics[2:]), nmetrics)
            return self.standard_reply()
        elif code.startswith('%%display_graph_for_all'):
            metrics = code.split(' ')
            nmetrics = len(metrics) - 1
            self.draw_performance_graph(self.get_perfdata_aggregated(metrics[1:]), nmetrics)
            return self.standard_reply()

        elif code.startswith('%%display_code_for_index'):
            index = int(code.split(' ')[1])
            self.cell_output("Cell timestamp: " + str(self.code_history[index][0]) + "\n--\n", 'stdout')
            self.cell_output(self.code_history[index][1], 'stdout')
            return self.standard_reply()
        elif code.startswith('%%display_code_history'):
            show(pd.DataFrame(self.code_history, columns=["timestamp", "code"]).reset_index())
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
            if self.slurm_nodelist:
                output.split(b"PERFDATA")
                for proc in node_subproc:
                    proc.kill()
                    output, _ = proc.communicate()
                    stdout_data_node.append(output)
            else:
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