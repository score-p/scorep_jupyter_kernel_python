import logging
import os
import sys


LOGGING_DIR = "logging"
os.makedirs(LOGGING_DIR, exist_ok=True)


class JupyterLogFilter(logging.Filter):
    def filter(self, record):
        return False


class IgnoreErrorFilter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.ERROR


class scorep_jupyterKernelOnlyFilter(logging.Filter):
    def filter(self, record):
        return "scorep_jupyter" in record.pathname


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname[0]} {asctime} {name}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "info_file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": os.path.join(LOGGING_DIR, "info.log"),
            "formatter": "verbose",
        },
        "debug_file": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": os.path.join(LOGGING_DIR, "debug.log"),
            "formatter": "verbose",
        },
        "error_file": {
            "level": "ERROR",
            "class": "logging.FileHandler",
            "filename": os.path.join(LOGGING_DIR, "error.log"),
            "formatter": "verbose",
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "filters": [
                "ignore_error_filter",  # prevents from writing to jupyter
                # cell output twice
                "scorep_jupyter_kernel_only_filter",
            ],
        },
    },
    "filters": {
        "jupyter_filter": {"()": JupyterLogFilter},
        "ignore_error_filter": {"()": IgnoreErrorFilter},
        "scorep_jupyter_kernel_only_filter": {"()": scorep_jupyterKernelOnlyFilter},
    },
    "root": {
        "handlers": [],
        "level": "WARNING",
    },
    "loggers": {
        "kernel": {
            "handlers": ["console", "debug_file", "info_file", "error_file"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
