from langchain.chat_models import init_chat_model

from core.config import DEFAULT_CHAT_MODEL

def get_structured_llm(schema):
    model = init_chat_model(DEFAULT_CHAT_MODEL)
    return model.with_structured_output(schema)
