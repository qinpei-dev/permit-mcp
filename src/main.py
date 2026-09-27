from fastapi import FastAPI
from .core.decision import DecisionEngine
from .jev.client import JEVClient
from .api.routes import build_router


def create_app() -> FastAPI:
    client = JEVClient.from_env()
    app = FastAPI(
        title="PermitMCP",
        version="0.4.1",
        description="A JEV-powered decision/control layer for MCP-compatible AI Agents.",
    )
    app.include_router(build_router(DecisionEngine(client)))
    return app


app = create_app()
