
from langgraph.checkpoint.memory import InMemorySaver

class WindowedInMemorySaver(InMemorySaver):
    def __init__(self, window_size: int = 6):
        super().__init__()
        self.window_size = window_size

    def get(self, config: dict) -> list:
        full_history = super().get(config)
        return full_history[-self.window_size:] if full_history else []