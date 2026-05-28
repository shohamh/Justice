from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import health as health_routes
from app.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Call of Duty 2 API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_routes.router, prefix="/api")
    return app


app = create_app()
