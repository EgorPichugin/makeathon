from pydantic import BaseModel, Field
from services.assistant.state import Intent


class ConversationIntentResult(BaseModel):
    intent: Intent = Field(...)


class ChangeComponentUpdateResult(BaseModel):
    component_name: str | None = Field(default=None)
    product_name: str | None = Field(default=None)
    supplier_name: str | None = Field(default=None)
