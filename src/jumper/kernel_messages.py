from enum import Enum, auto


class KernelErrorCode(Enum):
    PERSISTENCE_SETUP_FAIL = auto()
    PERSISTENCE_DUMP_FAIL = auto()
    PERSISTENCE_LOAD_FAIL = auto()
    INSTRUMENTATION_PATH_UNKNOWN = auto()
    SCOREP_SUBPROCESS_FAIL = auto()
    SCOREP_NOT_AVAILABLE = auto()
    SCOREP_PYTHON_NOT_AVAILABLE = auto()


KERNEL_ERROR_MESSAGES = {
    KernelErrorCode.SCOREP_NOT_AVAILABLE: (
        "Score-P not available, cell execution skipped. "
        "Hint: Make sure Score-P is installed and available in your PATH."
    ),
    KernelErrorCode.SCOREP_PYTHON_NOT_AVAILABLE: (
        "Score-P Python bindings not available, cell execution skipped. "
        "Hint: Try installing it with `pip install scorep`."
    ),
    KernelErrorCode.PERSISTENCE_SETUP_FAIL: (
        "Failed to set up persistence communication files/pipes "
    ),
    KernelErrorCode.PERSISTENCE_DUMP_FAIL: (
        "[mode: {mode}] Failed to serialize notebook persistence ({direction}, marshaller: {marshaller})."
    ),
    KernelErrorCode.PERSISTENCE_LOAD_FAIL: (
        "[mode: {mode}] Failed to load persistence ({direction}, marshaller: {marshaller})."
    ),
    KernelErrorCode.SCOREP_SUBPROCESS_FAIL: (
        "[mode: {mode}] Subprocess terminated unexpectedly. Persistence not recorded (marshaller: {marshaller})."
    ),
}
