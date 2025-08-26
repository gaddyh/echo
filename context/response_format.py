from pydantic import BaseModel

class AgentResponse(BaseModel):
    followup_question: str = ""
    final_response: str = ""
    