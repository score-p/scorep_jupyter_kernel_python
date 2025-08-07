import os
from enum import Enum, auto

from .logging_config import LOGGING


class KernelErrorCode(Enum):
    PERSISTENCE_SETUP_FAIL = auto()
    PERSISTENCE_DUMP_FAIL = auto()
    PERSISTENCE_LOAD_FAIL = auto()
    INSTRUMENTATION_PATH_UNKNOWN = auto()
    SCOREP_SUBPROCESS_FAIL = auto()
    SCOREP_NOT_AVAILABLE = auto()
    SCOREP_PYTHON_NOT_AVAILABLE = auto()
    VAMPIR_NOT_FOUND = auto()
    VAMPIR_LAUNCH_FAILED = auto()


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
        "[mode: {mode}] Failed to serialize notebook persistence "
        "({direction}, marshaller: {marshaller})."
    ),
    KernelErrorCode.PERSISTENCE_LOAD_FAIL: (
        "[mode: {mode}] Failed to load persistence "
        "({direction}, marshaller: {marshaller}). {optional_hint}"
    ),
    KernelErrorCode.SCOREP_SUBPROCESS_FAIL: (
        "[mode: {mode}] Subprocess terminated unexpectedly. "
        "Persistence not recorded (marshaller: {marshaller})."
    ),
    KernelErrorCode.INSTRUMENTATION_PATH_UNKNOWN: (
        "Instrumentation output directory not found or missing traces.otf2 "
        "(looked in: {scorep_folder})"
    ),
    KernelErrorCode.VAMPIR_NOT_FOUND: (
        'Vampir binary not found in PATH. Add it to PATH to enable automatic launch'
        ' (e.g. in ~/.bashrc: export PATH="/path/to/vampir/bin:$PATH"' 
    ),

    KernelErrorCode.VAMPIR_LAUNCH_FAILED: (
        "Failed to launch Vampir: {exception}"
    ),
}


def get_scorep_process_error_hint():
    scorep_process_error_hint = (
        "\nHint: full error info saved to log file: "
        f"{LOGGING['handlers']['error_file']['filename']}"
    )
    return scorep_process_error_hint
