from __future__ import annotations

import asyncio

from fastapi import FastAPI

from app.file_gateway.routes import SlidingWindowRateLimiter, router


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.download_semaphore = asyncio.Semaphore(8)
    app.state.download_rate_limiter = SlidingWindowRateLimiter()
    app.include_router(router)
    return app


app = create_app()
