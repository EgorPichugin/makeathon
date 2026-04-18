from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, description="Conversation thread identifier")
    message: str = Field(..., min_length=1, description="Client request to process")


class AgentResponse(BaseModel):
    answer: str
