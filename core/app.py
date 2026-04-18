from fastapi import FastAPI

from core.config import APP_TITLE, ASSISTANT_DB_PATH
from routers.agent import router as agent_router
from routers.companies import router as companies_router
from dotenv import load_dotenv
from services.assistant.observability import configure_observability
from services.assistant.storage import init_db

def create_app() -> FastAPI:
    load_dotenv()  # Load environment variables from .env file
    configure_observability()

    # temporary: ensure DB is initialized at /data/db.sqlite
    init_db(ASSISTANT_DB_PATH)
    app = FastAPI(title=APP_TITLE)
    app.include_router(agent_router)
    app.include_router(companies_router)
    return app
