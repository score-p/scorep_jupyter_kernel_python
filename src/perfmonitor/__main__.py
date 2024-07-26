import time
import psutil
import pickle
import codecs
import pynvml
import os
import sys


ngpus = 0
gpu_handles = []

pid = int(sys.argv[1])

if __name__ == "__main__":
    try:
        pynvml.nvmlInit()
        ngpus = pynvml.nvmlDeviceGetCount()
        gpu_handles = [
            pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(ngpus)
        ]
    except Exception:
        pass

    freq = int(os.environ.get("JUMPER_REPORT_FREQUENCY", 2))

    while True:
        try:
            gpu_util = []
            gpu_mem = []
            cpu_util = psutil.cpu_percent(percpu=True)
            # cpu affininty reflects on cgroups (e.g. if SLURM sets resources
            # for a job)
            av_cpus = psutil.Process().cpu_affinity()
            av_cpu_util = [cpu_util[i] for i in av_cpus]
            # bytes -> GB
            mem_util = (
                (
                    psutil.virtual_memory().total
                    - psutil.virtual_memory().available
                )
                / 1024
                / 1024
                / 1024
            )
            io_data = psutil.Process(pid).io_counters()
            io_data = [
                io_data[0],
                io_data[1],
                io_data[2] / 1024 / 1024,
                io_data[3] / 1024 / 1024,
            ]
            if gpu_handles:
                for handle in gpu_handles:
                    urate = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_util.append(urate.gpu)
                    gpu_mem.append(urate.memory)
            # print([av_cpu_util, mem_util, gpu_util, gpu_mem, io_data])
            print(
                codecs.encode(
                    pickle.dumps(
                        [av_cpu_util, mem_util, gpu_util, gpu_mem, io_data]
                    ),
                    "base64",
                ).decode()
            )
        except Exception:
            pass
        time.sleep(freq)
