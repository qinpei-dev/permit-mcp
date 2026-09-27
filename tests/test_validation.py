"""Input, output, and decision-boundary validation tests."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
import pytest
from pydantic import ValidationError

from src.api.routes import build_router
from src.core.decision import DecisionEngine
from src.core.models import DecisionRequest, DecisionResult, RouteRequest
from src.jev.client import JEVClient
from src.jev.mock import MockJEVClient
from src.mcp.tools import create_mcp_server
from src.skills import SkillExecutor, SkillRegistry, create_default_registry


class InvalidDecisionClient(JEVClient):
    async def decide(self, request: DecisionRequest) -> DecisionResult:
        return DecisionResult(decision="unregistered_skill", confidence=0.9, reason="test response")


def make_app(client: JEVClient) -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(DecisionEngine(client)))
    return app


@pytest.mark.parametrize(
    "kwargs",
    [
        {"task": " ", "options": ["allow"]},
        {"task": "task", "options": [" "]},
        {"task": "task", "options": ["allow", "allow"]},
        {"task": "task", "options": []},
        {"task": "task", "options": [f"option-{index}" for index in range(256)]},
    ],
)
def test_decision_request_rejects_invalid_task_or_options(kwargs):
    with pytest.raises(ValidationError):
        DecisionRequest(**kwargs)


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_decision_confidence_accepts_boundaries(confidence):
    result = DecisionResult(decision="allow", confidence=confidence, reason="boundary")
    assert result.confidence == confidence


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_decision_confidence_rejects_values_outside_boundaries(confidence):
    with pytest.raises(ValidationError):
        DecisionResult(decision="allow", confidence=confidence, reason="invalid")


def test_decision_engine_rejects_choice_outside_allowed_options():
    with pytest.raises(ValueError, match="outside the allowed options"):
        asyncio.run(DecisionEngine(InvalidDecisionClient()).decide("Select a skill", ["coding_skill"]))


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/decide", {"task": "task", "options": ["coding_skill"]}),
        ("/route/skill", {"task": "task"}),
        ("/route/agent", {"task": "task"}),
        ("/api/v1/agent/run", {"task": "task"}),
    ],
)
def test_http_api_returns_502_for_invalid_decision(path, payload, monkeypatch):
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", "test-execution-only")
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", "test-approval-only")
    response = TestClient(make_app(InvalidDecisionClient())).post(path, json=payload, headers={"Authorization": "Bearer test-execution-only"})
    assert response.status_code == 502


def test_http_api_rejects_blank_options_with_422(monkeypatch):
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", "test-execution-only")
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", "test-approval-only")
    response = TestClient(make_app(MockJEVClient())).post(
        "/decide", json={"task": "task", "options": [" "]}, headers={"Authorization": "Bearer test-execution-only"}
    )
    assert response.status_code == 422


def test_route_request_rejects_blank_task():
    with pytest.raises(ValidationError):
        RouteRequest(task="  ")


def test_mcp_tool_rejects_blank_input():
    server = create_mcp_server(MockJEVClient())
    with pytest.raises(ToolError, match="task must not be empty"):
        asyncio.run(server.call_tool("jev_decide", {"task": " ", "options": ["allow"]}))


def test_skill_route_includes_registered_research_skill(monkeypatch):
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", "test-execution-only")
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", "test-approval-only")
    response = TestClient(make_app(MockJEVClient())).post("/route/skill", json={"task": "调研 RAG 方案"}, headers={"Authorization": "Bearer test-execution-only"})
    assert response.status_code == 200
    assert response.json()["skill"] == "research_skill"


def test_executor_rejects_unknown_skill():
    with pytest.raises(ValueError, match="No skill registered"):
        SkillExecutor(create_default_registry()).execute("unknown_skill", "task")


def test_registry_rejects_duplicate_skill():
    registry = SkillRegistry()
    registry.register(create_default_registry().get("career_skill"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(create_default_registry().get("career_skill"))
