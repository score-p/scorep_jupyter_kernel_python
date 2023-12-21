import time
import psutil
import pickle
import codecs
import pynvml

if __name__ == "__main__":
    ngpus = 0
    gpu_handles = []

    try:
        pynvml.nvmlInit()
        ngpus = pynvml.nvmlDeviceGetCount()
        gpu_handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(ngpus)]
    except:
        pass

    while True:
        gpu_util = []
        gpu_mem = []
        cpu_util = psutil.cpu_percent(percpu=True)
        av_cpus = psutil.Process().cpu_affinity()
        av_cpu_util = [cpu_util[i] for i in av_cpus]
        mem_util = psutil.virtual_memory().percent
        if gpu_handles:
            for handle in gpu_handles:
                urate = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_util.append(urate.gpu)
                gpu_mem.append(urate.memory)
        #print([av_cpu_util, mem_util, gpu_util, gpu_mem])
        print(codecs.encode(pickle.dumps([av_cpu_util, mem_util, gpu_util, gpu_mem]), "base64").decode())
        time.sleep(2)