import os


LOGGING_DIR = 'logging'
os.makedirs(LOGGING_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname[0]} {asctime} {name}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'info_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(LOGGING_DIR, 'info.log'),
            'formatter': 'verbose'
        },
        'debug_file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(LOGGING_DIR, 'debug.log'),
            'formatter': 'verbose'
        },
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': os.path.join(LOGGING_DIR, 'error.log'),
            'formatter': 'verbose'
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
        },
    },
    'root': {
        'handlers': ['console', 'debug_file'],
        'level': 'INFO',
    },
    'loggers': {
        'kernel': {
            'handlers': ['console', 'debug_file', 'info_file'],
            'level': 'INFO',
            'propagate': False,
        },
    }
}