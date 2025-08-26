# Tracing hooks (OpenTelemetry ready)

def trace_span(name):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            print(f'[TRACE] {name}')
            return fn(*args, **kwargs)
        return wrapper
    return decorator

import uuid
from shared.observability.logger import log_event, log_error

class Tracer:
    def __init__(self, trace_id: str = None):
        self.trace_id = trace_id or self._generate_trace_id()

    def _generate_trace_id(self):
        return str(uuid.uuid4())

    def log_event(self, tag: str, **kwargs):
        log_event(tag, trace_id=self.trace_id, **kwargs)

    def log_error(self, tag: str, error: Exception | str, **kwargs):
        log_error(tag, error, trace_id=self.trace_id, **kwargs)
