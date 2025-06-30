import os
import stat
import multiprocessing
from parallel_marshall.balanced_distribution_iterator import (
    BalancedDistributionIterator,
)
import importlib
import logging

# mode is automatically determined by the file object that is passed for
# dumping
mode = ""
backend = str(os.environ.get("scorep_jupyter_PARALLEL_MARSHALL_BACKEND", "dill"))
if os.environ.get("scorep_jupyter_PARALLEL_MARSHALL_NWORKERS"):
    workers = min(
        int(os.environ.get("scorep_jupyter_PARALLEL_MARSHALL_NWORKERS")),
        multiprocessing.cpu_count(),
        multiprocessing.cpu_count(),
    )
else:
    workers = multiprocessing.cpu_count()
debug = int(os.environ.get("scorep_jupyter_PARALLEL_MARSHALL_DEBUG", 20))

logger = logging.getLogger(__name__)
logging.basicConfig(filename="parallel_marshall.log", level=logging.INFO)

# see https://docs.python.org/3.11/library/logging.html#levels
# 0=NOTSET, 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=CRITICAL
logger.setLevel(debug)

try:
    serializer_backend = importlib.import_module(backend)
except ModuleNotFoundError:
    print("Backend marshalling module not found. Exit.")
    logger.error("Backend marshalling module not found. Exit.")
    exit(1)


def dump(obj, file):
    global mode
    paths = [f"{file.name}_{i}" for i in range(workers)]

    if stat.S_ISREG(os.fstat(file.fileno()).st_mode):
        mode = "disk"
        for path in paths:
            open(path, "a").close()
        logger.debug("Files created")
    elif stat.S_ISFIFO(os.fstat(file.fileno()).st_mode):
        mode = "memory"
        for path in paths:
            os.mkfifo(path)
        logger.debug("Pipes spawned")
    else:
        logger.debug("Unrecognized type of file")

    # first block until loader reads filenames
    for path in paths:
        file.write(path.encode("utf-8") + b"\n")
    file.close()
    logger.debug("Writer communicated paths")

    if workers == 1:
        with os.fdopen(os.open(paths[0], os.O_WRONLY | os.O_CREAT), "wb") as f:
            serializer_backend.dump(obj, f)
        return

    # multi processing scheme
    processes = []
    # each of spawned writers is blocked until loader reads their subdict
    i = 0
    for subobj in BalancedDistributionIterator(obj, workers):
        subobj_path = paths[i]
        process = multiprocessing.Process(
            target=dump_subobj, args=(subobj, subobj_path)
        )
        processes.append(process)
        process.start()
        logger.debug(f"Writer spawned process {i}")
        i += 1

    for process in processes:
        process.join()
    logger.debug("joined")


def dump_subobj(subobj, subobj_path):
    with os.fdopen(os.open(subobj_path, os.O_WRONLY | os.O_CREAT), "wb") as f:
        serializer_backend.dump(subobj, f)


# sequential loading of parallel marshalled data
def load(file):
    logger.debug("Loader started")
    paths = file.read().decode("utf-8").splitlines()
    file.close()
    logger.debug("Loader read paths")
    data_ = {}

    # unblock spawned writers one by one
    for subdict_path in paths:
        logger.debug(f"Loader started working with {subdict_path}")
        with os.fdopen(os.open(subdict_path, os.O_RDONLY), "rb") as f:
            obj = serializer_backend.load(f)
            if isinstance(obj, dict):
                data_.update(obj)
            elif isinstance(obj, list):
                data_ = []
                data_.extend(obj)
            logger.debug("Loader loaded subdict")

    for path in paths:
        if os.path.exists(path):
            os.unlink(path)

    return data_
