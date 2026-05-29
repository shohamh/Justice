from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.rate_limit import limiter
from app.routes import auth as auth_routes
from app.routes import duty_config as duty_config_routes
from app.routes import exemptions as exemption_routes
from app.routes import health as health_routes
from app.routes import hierarchy as hierarchy_routes
from app.routes import me as me_routes
from app.routes import soldiers as soldier_routes
from app.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Call of Duty 2 API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(me_routes.router, prefix="/api")
    app.include_router(hierarchy_routes.router, prefix="/api")
    app.include_router(soldier_routes.router, prefix="/api")
    app.include_router(duty_config_routes.router, prefix="/api")
    app.include_router(exemption_routes.router, prefix="/api")
    return app


app = create_app()
