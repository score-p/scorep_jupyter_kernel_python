import re
import subprocess
import sys
import os
from jumper.multinode_monitor.abstract_monitor import AbstractMonitor


class Slurm_Monitor(AbstractMonitor):

    def __init__(self):
        self.perf_proc = None

    def parse_nodelist(self):
        nodelist_string = os.environ.get("SLURM_NODELIST", "")
        nodes = []
        # Regular expression to match patterns like 'node[1-3],node5,node7'
        pattern = r"(\w+\[\d+-\d+\]|\w+|\d+)"
        matches = re.findall(pattern, nodelist_string)

        for match in matches:
            # Check if the match contains a range
            if "-" in match:
                node_range = match.split("[")
                prefix = node_range[0]
                start, end = map(int, re.findall(r"\d+", node_range[1]))
                nodes.extend([f"{prefix}{i}" for i in range(start, end + 1)])
            else:
                nodes.append(match)

        return nodes

    def start_monitor(self):
        # SLURM is available, use srun to get output for all the nodes
        # until first \n we would like to get the hostname
        proc_env = os.environ.copy()
        proc_env.update({"PYTHONUNBUFFERED": "x"})
        self.perf_proc = subprocess.Popen(
            [
                "srun",
                "hostname",
                "&&",
                "echo",
                "PERFDATA",
                "&&",
                sys.executable,
                "-m" "perfmonitor",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=proc_env,
        )

    def end_monitor(self):
        output, _ = self.perf_proc.communicate()
        return output
