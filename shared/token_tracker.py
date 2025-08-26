import tiktoken
from typing import List, Dict, Any

class TokenTracker:
    def __init__(self, model_name="gpt-4o"):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.turns = []
        self.model_name = model_name

    def estimate_tokens(self, messages: List[Any]) -> int:
        enc = tiktoken.encoding_for_model(self.model_name)

        def safe_content(msg):
            if isinstance(msg.content, str):
                return msg.content
            elif isinstance(msg.content, list):
                # Convert list of dicts to plain string
                return "\n".join(
                    block.get("text", str(block)) for block in msg.content
                )
            else:
                return str(msg.content)

        return sum(len(enc.encode(safe_content(m))) for m in messages if hasattr(m, "content"))


    def report(self) -> Dict[str, int]:
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens
        }
