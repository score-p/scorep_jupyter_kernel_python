import inspect
from statistics import mean
import pickle
import codecs
import time
from datetime import datetime
import os
import subprocess
import sys
import importlib
import re


def compute_mean_across_nodes(key1, key2, metrics_across_nodes):
    # use the first list
    mean_across_nodes = []
    for i in range(0, len(metrics_across_nodes[key1][key2][0])):
        mean = metrics_across_nodes[key1][key2][0][i]
        # check the values on the other lists, compute the mean and add
        for j in range(1, len(metrics_across_nodes[key1][key2])):
            mean += metrics_across_nodes[key1][key2][j][i]
        mean_across_nodes.append(mean / len(metrics_across_nodes[key1][key2]))
    return mean_across_nodes


class PerformanceDataHandler:

    def __init__(self):
        self.code_history = []
        self.performance_data_history = []
        self.nodelist = None
        # for local it's none, otherwise points to slurm/ssh/... monitor
        self.monitor_module = None
        # the object from the monitor module
        self.monitor = None
        # local uses this proc
        self.local_perf_proc = None

        self.starttime = None

    def set_monitor(self, monitor):
        # TODO: add a check whether the monitor module has all required
        #  functions implemented
        try:
            self.monitor_module = importlib.import_module(
                "jumper.multinode_monitor." + monitor + "_monitor"
            )
            classes = inspect.getmembers(self.monitor_module, inspect.isclass)
            # just search for monitoring classes
            pattern = re.compile(".*[mM]onitor.*")
            for name, cls in classes:
                if name == "AbstractMonitor":
                    continue
                if pattern.match(name):
                    self.monitor = cls()
            if self.monitor is None:
                raise ValueError(
                    f"No class matching pattern '{pattern}' found in module "
                    f"'{self.monitor_module.__name__}'"
                )

            self.nodelist = self.monitor.parse_nodelist()
            if self.nodelist is None:
                # couldn't parse the nodelist
                self.monitor_module = None
                self.monitor = None
        except Exception:
            self.monitor_module = None
            self.monitor = None
            self.nodelist = None

    def get_nodelist(self):
        return self.nodelist

    def get_perfdata_history(self):
        return self.performance_data_history

    def get_code_history(self):
        return self.code_history

    def append_code(self, time, code):
        self.code_history.append([time, code])

    def get_perfdata_aggregated(self):
        perfdata_aggregated = []
        # for each node, initialize the list index 0 in next row indicates,
        # we are just checking the very first cell that was executed
        """
        each line in performance_data_history represents a cell (code) executed
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
        """
        time_indices = []
        for node in range(0, len(self.performance_data_history[0]) - 8):
            time_indices.append([])
            perfdata_init = self.performance_data_history[0][node]
            # for each cpu and gpu, we need an empty list to be filled
            cpu_util = (
                [[] for _ in perfdata_init[0]] if perfdata_init[0] else [[]]
            )
            gpu_util = (
                [[] for _ in perfdata_init[2]] if perfdata_init[2] else [[]]
            )
            gpu_mem = (
                [[] for _ in perfdata_init[2]] if perfdata_init[3] else [[]]
            )
            mem_util = []
            io_ops_read = []
            io_ops_write = []
            io_bytes_read = []
            io_bytes_write = []
            perfdata_aggregated.append(
                [
                    cpu_util,
                    mem_util,
                    io_ops_read,
                    io_ops_write,
                    io_bytes_read,
                    io_bytes_write,
                    gpu_util,
                    gpu_mem,
                ]
            )

        # for each cell/code (called perfdata)...
        for idx, perfdata in enumerate(self.performance_data_history):
            # for each node in this cell/code
            for node in range(0, len(perfdata) - 8):
                for cpu_index in range(0, len(perfdata[node][0])):
                    perfdata_aggregated[node][0][cpu_index].extend(
                        perfdata[node][0][cpu_index]
                    )
                perfdata_aggregated[node][1].extend(perfdata[node][1])
                perfdata_aggregated[node][2].extend(perfdata[node][2])
                perfdata_aggregated[node][3].extend(perfdata[node][3])
                perfdata_aggregated[node][4].extend(perfdata[node][4])
                perfdata_aggregated[node][5].extend(perfdata[node][5])
                for gpu_index in range(0, len(perfdata[node][6])):
                    perfdata_aggregated[node][6][gpu_index].extend(
                        perfdata[node][6][gpu_index]
                    )
                for gpu_index in range(0, len(perfdata[node][7])):
                    perfdata_aggregated[node][7][gpu_index].extend(
                        perfdata[node][7][gpu_index]
                    )

                # add cell index and the number of measurements
                # we will use that in the visualization to generate
                # a color transition in the graphs and add the cell index
                time_indices[node].append((idx, len(perfdata[node][2])))

        return perfdata_aggregated, time_indices

    def parse_perfdata_from_stdout(self, stdout_data_node):
        # might be that parent process pushes to stdout and that output gets
        # reversed couldn't find a better way than waiting for 1s and hoping
        # that outputs are in correct order in the queue now
        time.sleep(1)

        # parse the performance data
        performance_data_nodes = []
        metrics_across_nodes = {
            "CPU": {"MEANS": [], "MAXS": [], "MINS": []},
            "MEM": {"MEANS": [], "MAXS": [], "MINS": []},
            "GPU_UTIL": {"MEANS": [], "MAXS": [], "MINS": []},
            "GPU_MEM": {"MEANS": [], "MAXS": [], "MINS": []},
            "IO_OPS_READ": {"MEANS": [], "MAXS": [], "MINS": []},
            "IO_OPS_WRITE": {"MEANS": [], "MAXS": [], "MINS": []},
            "IO_BYTES_READ": {"MEANS": [], "MAXS": [], "MINS": []},
            "IO_BYTES_WRITE": {"MEANS": [], "MAXS": [], "MINS": []},
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
                init_data = pickle.loads(
                    codecs.decode(stdout_data[0], "base64")
                )
                cpu_util = [[] for _ in init_data[0]]
                gpu_util = [[] for _ in init_data[2]]
                gpu_mem = [[] for _ in init_data[3]]

                # add empty lists for mean, max, min
                for i in range(0, 3):
                    cpu_util.append([])
                    gpu_util.append([])
                    gpu_mem.append([])
            else:
                return None

            for line in stdout_data:
                if line == b"":
                    continue
                perf_data = pickle.loads(codecs.decode(line, "base64"))

                for cpu in range(0, len(perf_data[0])):
                    cpu_util[cpu].append(perf_data[0][cpu])

                last_measurements = [
                    cpu_list[-1] for cpu_list in cpu_util[:-3]
                ]
                cpu_util[-3].append(mean(last_measurements))
                cpu_util[-2].append(max(last_measurements))
                cpu_util[-1].append(min(last_measurements))

                mem_util.append(perf_data[1])
                # 0 read counts, 1 write counts, 2 read bytes, 3 write bytes
                io_ops_read.append(perf_data[4][0])
                io_ops_write.append(perf_data[4][1])
                io_bytes_read.append(perf_data[4][2])
                io_bytes_write.append(perf_data[4][3])
                for gpu in range(0, len(perf_data[2])):
                    gpu_util[gpu].append(perf_data[2][gpu])
                    gpu_mem[gpu].append(perf_data[3][gpu])

                last_measurements = [
                    gpu_list[-1] for gpu_list in gpu_util[:-3]
                ]
                if last_measurements:
                    gpu_util[-3].append(mean(last_measurements))
                    gpu_util[-2].append(max(last_measurements))
                    gpu_util[-1].append(min(last_measurements))

                last_measurements = [gpu_list[-1] for gpu_list in gpu_mem[:-3]]
                if last_measurements:
                    gpu_mem[-3].append(mean(last_measurements))
                    gpu_mem[-2].append(max(last_measurements))
                    gpu_mem[-1].append(min(last_measurements))

            # TODO: discuss whether Means of Maxs are relevant or should we
            #  consider Mean of Means only?
            metrics_across_nodes["CPU"]["MEANS"].append(cpu_util[-3])
            metrics_across_nodes["MEM"]["MEANS"].append(mem_util)
            metrics_across_nodes["IO_OPS_READ"]["MEANS"].append(io_ops_read)
            metrics_across_nodes["IO_OPS_WRITE"]["MEANS"].append(io_ops_write)
            metrics_across_nodes["IO_BYTES_READ"]["MEANS"].append(
                io_bytes_read
            )
            metrics_across_nodes["IO_BYTES_WRITE"]["MEANS"].append(
                io_bytes_write
            )
            metrics_across_nodes["GPU_UTIL"]["MEANS"].append(gpu_util[-3])
            metrics_across_nodes["GPU_MEM"]["MEANS"].append(gpu_mem[-3])
            performance_data_nodes.append(
                [
                    cpu_util,
                    mem_util,
                    io_ops_read,
                    io_ops_write,
                    io_bytes_read,
                    io_bytes_write,
                    gpu_util,
                    gpu_mem,
                ]
            )

        # compute the mean, max, min across the nodes using pure mem_util
        # lists, the mean, max and min lists of the other sensors
        performance_data_nodes.append(
            compute_mean_across_nodes("CPU", "MEANS", metrics_across_nodes)
        )
        performance_data_nodes.append(
            compute_mean_across_nodes("MEM", "MEANS", metrics_across_nodes)
        )
        performance_data_nodes.append(
            compute_mean_across_nodes(
                "IO_OPS_READ", "MEANS", metrics_across_nodes
            )
        )
        performance_data_nodes.append(
            compute_mean_across_nodes(
                "IO_OPS_WRITE", "MEANS", metrics_across_nodes
            )
        )
        performance_data_nodes.append(
            compute_mean_across_nodes(
                "IO_BYTES_READ", "MEANS", metrics_across_nodes
            )
        )
        performance_data_nodes.append(
            compute_mean_across_nodes(
                "IO_BYTES_WRITE", "MEANS", metrics_across_nodes
            )
        )
        performance_data_nodes.append(
            compute_mean_across_nodes(
                "GPU_UTIL", "MEANS", metrics_across_nodes
            )
        )
        performance_data_nodes.append(
            compute_mean_across_nodes("GPU_MEM", "MEANS", metrics_across_nodes)
        )

        self.performance_data_history.append(performance_data_nodes)
        return performance_data_nodes

    def start_perfmonitor(self, pid):
        if self.monitor_module:
            self.monitor_module.start_monitor()
        else:
            proc_env = os.environ.copy()
            proc_env.update({"PYTHONUNBUFFERED": "x"})
            # SLURM is not available, sorry we support only one node
            self.local_perf_proc = subprocess.Popen(
                [sys.executable, "-m" "perfmonitor", str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=proc_env,
            )

        self.starttime = time.perf_counter()

    def end_perfmonitor(self, code):
        duration = time.perf_counter() - self.starttime

        if self.monitor_module:
            output = self.monitor_module.end_monitor()
        else:
            self.local_perf_proc.kill()
            output, _ = self.local_perf_proc.communicate()
        stdout_data_node = []
        """
        if self.slurm_nodelist:
            output.split(b"PERFDATA")
            for proc in node_subproc:
                proc.kill()
                output, _ = proc.communicate()
                stdout_data_node.append(output)
        else:
            stdout_data_node.append(output)
        """
        stdout_data_node.append(output)

        # parse the performance data from the stdout pipe of the subprocess
        # and print the performance data
        performance_data_nodes = self.parse_perfdata_from_stdout(
            stdout_data_node
        )
        if performance_data_nodes:
            self.append_code(datetime.now(), code)
        return performance_data_nodes, duration
