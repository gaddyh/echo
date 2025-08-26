import time
from enum import Enum, auto
import os

class LogLevel(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()

# Global config
VERBOSE_LEVEL = LogLevel.INFO
LOG_FILE_PATH = "logs/taskflow.log"

# Ensure logs directory exists
os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)

def _write_to_file(line: str):
    with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def log(level: LogLevel, tag: str, message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"[{timestamp}][{level.name}][{tag}] {message}"
    
    if level.value >= VERBOSE_LEVEL.value:
        print(line)
        _write_to_file(line)

def log_event(tag: str, **kwargs):
    message = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    log(LogLevel.INFO, tag, message)

import traceback

def log_error(tag: str, error: Exception | str, **kwargs):
    if isinstance(error, Exception):
        trace = traceback.format_exc()
        message = f"error={str(error)} | trace={trace.strip()} | " + " | ".join(f"{k}={v}" for k, v in kwargs.items())
    else:
        message = f"error={error} | " + " | ".join(f"{k}={v}" for k, v in kwargs.items())

    log(LogLevel.ERROR, tag, message)

