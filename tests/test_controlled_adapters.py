"""MCP and HTTP adapters for the shared controlled-agent service."""

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
import pytest

from src.api.routes import build_router
from src.core.decision import DecisionEngine
from src.core.models import DecisionRequest, DecisionResult
from src.jev.client import JEVClient
from src.mcp.tools import create_mcp_server


class AllowClient(JEVClient):
    async def decide(self, request: DecisionRequest) -> DecisionResult:
        return DecisionResult(decision="allow", confidence=0.9, reason="offline allow")


def readme(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# Adapter Demo\n\nReal source text.\n", encoding="utf-8")


def test_mcp_controlled_tool_runs_real_sandbox_work(tmp_path):
    readme(tmp_path)
    server = create_mcp_server(AllowClient(), sandbox_root=tmp_path)

    async def run():
        result = await server.call_tool(
            "controlled_agent_run", {"task": "summarize README", "max_steps": 5}
        )
        return json.loads(result[0].text)

    trace = asyncio.run(run())
    assert trace["status"] == "completed"
    assert (tmp_path / "output" / "summary.md").exists()
    assert "Real source text" not in json.dumps(trace)
    assert trace["steps"][0]["tool_result"]["output"] == "[redacted]"
    assert trace["steps"][1]["proposal"]["arguments"]["content"] == "[redacted]"


def test_mcp_approval_resumes_same_reviewed_action(tmp_path):
    readme(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    (output / "summary.md").write_text("old summary", encoding="utf-8")
    server = create_mcp_server(AllowClient(), sandbox_root=tmp_path)

    async def run_and_approve():
        pending_result = await server.call_tool(
            "controlled_agent_run", {"task": "summarize README", "max_steps": 5}
        )
        pending = json.loads(pending_result[0].text)
        assert pending["status"] == "approval_required"
        assert pending["pending_action"]["arguments"]["content"] == "[redacted]"
        with pytest.raises(ToolError, match="no pending action"):
            await server.call_tool(
                "approve_action", {"run_id": "wrong-run", "action_id": pending["pending_action"]["action_id"]}
            )
        approved_result = await server.call_tool(
            "approve_action", {"run_id": pending["run_id"], "action_id": pending["pending_action"]["action_id"]}
        )
        return pending, json.loads(approved_result[0].text)

    pending, approved = asyncio.run(run_and_approve())
    assert approved["run_id"] == pending["run_id"]
    assert approved["status"] == "completed"
    assert "Adapter Demo" in (output / "summary.md").read_text(encoding="utf-8")


def test_http_controlled_run_uses_real_executor(tmp_path, monkeypatch):
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", "test-execution-only")
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", "test-approval-only")
    readme(tmp_path)
    app = FastAPI()
    app.include_router(build_router(DecisionEngine(AllowClient()), sandbox_root=tmp_path))
    response = TestClient(app).post(
        "/api/v1/controlled-agent/run", json={"task": "summarize README", "max_steps": 5},
        headers={"Authorization": "Bearer test-execution-only"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert (tmp_path / "output" / "summary.md").exists()


def test_http_approval_and_invalid_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", "test-execution-only")
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", "test-approval-only")
    readme(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    (output / "summary.md").write_text("before", encoding="utf-8")
    app = FastAPI()
    app.include_router(build_router(DecisionEngine(AllowClient()), sandbox_root=tmp_path))
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test-execution-only"})
    pending_response = client.post(
        "/api/v1/controlled-agent/run", json={"task": "summarize README", "max_steps": 5}
    )
    pending = pending_response.json()
    assert pending_response.status_code == 200
    assert pending["status"] == "approval_required"
    assert (output / "summary.md").read_text(encoding="utf-8") == "before"
    assert client.post(
        f"/api/v1/controlled-agent/{pending['run_id']}/approve",
        json={"action_id": pending["pending_action"]["action_id"]},
    ).status_code == 401
    assert (output / "summary.md").read_text(encoding="utf-8") == "before"
    client.headers.update({"Authorization": "Bearer test-approval-only"})
    assert client.post(
        "/api/v1/controlled-agent/wrong-run/approve",
        json={"action_id": pending["pending_action"]["action_id"]},
    ).status_code == 409
    approval = client.post(
        f"/api/v1/controlled-agent/{pending['run_id']}/approve",
        json={"action_id": pending["pending_action"]["action_id"]},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "completed"
    assert client.post(
        f"/api/v1/controlled-agent/{pending['run_id']}/approve",
        json={"action_id": pending["pending_action"]["action_id"]},
    ).status_code == 409
    client.headers.update({"Authorization": "Bearer test-execution-only"})
    assert client.post(
        "/api/v1/controlled-agent/run", json={"task": " ", "max_steps": 0}
    ).status_code == 422
    client.headers.update({"Authorization": "Bearer test-approval-only"})
    assert client.post(
        f"/api/v1/controlled-agent/{pending['run_id']}/approve", json={"action_id": "wrong"}
    ).status_code == 409
