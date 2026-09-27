"""HTTP authentication must stop work before the decision or tool path runs."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.api.routes import build_router
from src.core.decision import DecisionEngine
from src.jev.mock import MockJEVClient


EXECUTION = "test-execution-only"
APPROVAL = "test-approval-only"
RUN = "/api/v1/controlled-agent/run"
APPROVE = "/api/v1/controlled-agent/known-run/approve"


class CountingClient(MockJEVClient):
    def __init__(self):
        self.calls = 0

    async def decide(self, request):
        self.calls += 1
        return await super().decide(request)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("PERMITMCP_EXECUTION_TOKEN", raising=False)
    monkeypatch.delenv("PERMITMCP_APPROVAL_TOKEN", raising=False)
    backend = CountingClient()
    app = FastAPI()
    app.include_router(build_router(DecisionEngine(backend), sandbox_root=tmp_path))
    return TestClient(app), backend, tmp_path


@pytest.mark.parametrize("path,payload", [
    ("/decide", {"task": "task", "options": ["career_skill"]}),
    ("/route/skill", {"task": "task"}),
    ("/route/agent", {"task": "task"}),
    ("/api/v1/agent/run", {"task": "task"}),
    (RUN, {"task": "summarize README", "max_steps": 5}),
    (APPROVE, {"action_id": "known-action"}),
])
def test_unconfigured_credentials_fail_closed(api, path, payload):
    client, backend, root = api
    response = client.post(path, json=payload, headers={"Authorization": f"Bearer {EXECUTION}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert backend.calls == 0
    assert list(root.iterdir()) == []
    assert client.get("/health").status_code == 200


def test_roles_and_bad_credentials_do_not_execute(api, monkeypatch):
    client, backend, root = api
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", EXECUTION)
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", APPROVAL)
    (root / "README.md").write_text("source", encoding="utf-8")
    attempts = [None, "Bearer wrong", f"Basic {EXECUTION}",
                f"Bearer {APPROVAL}", f"Bearer {EXECUTION} trailing"]
    for value in attempts:
        headers = {} if value is None else {"Authorization": value}
        response = client.post(RUN, json={"task": "summarize README", "max_steps": 5}, headers=headers)
        assert response.status_code == 401
        assert EXECUTION not in response.text and APPROVAL not in response.text
    assert backend.calls == 0
    assert not (root / "output").exists()
    for value in (None, "Bearer wrong", f"Bearer {EXECUTION}"):
        headers = {} if value is None else {"Authorization": value}
        response = client.post(APPROVE, json={"action_id": "known-action"}, headers=headers)
        assert response.status_code == 401
    assert backend.calls == 0


def test_same_or_partial_credentials_fail_closed(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", EXECUTION)
    assert client.post("/api/v1/agent/run", json={"task": "task"}, headers={"Authorization": f"Bearer {EXECUTION}"}).status_code == 401
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", EXECUTION)
    assert client.post("/api/v1/agent/run", json={"task": "task"}, headers={"Authorization": f"Bearer {EXECUTION}"}).status_code == 401


def test_valid_execution_token_reaches_decision(api, monkeypatch):
    client, backend, _ = api
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", EXECUTION)
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", APPROVAL)
    response = client.post("/api/v1/agent/run", json={"task": "career"}, headers={"Authorization": f"Bearer {EXECUTION}"})
    assert response.status_code == 200
    assert backend.calls == 1
