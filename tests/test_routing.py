import asyncio
from fastapi.testclient import TestClient
from src.core.decision import DecisionEngine
from src.core.router import SkillRouter, AgentRouter
from src.jev.mock import MockJEVClient
from src.doubao.adapter import DoubaoAdapter
from src.api.routes import build_router
from src.skills import SkillExecutor, create_default_registry
from fastapi import FastAPI


def test_paper_skill_route():
    result = asyncio.run(SkillRouter(DecisionEngine(MockJEVClient())).route("帮我修改论文格式"))
    assert result.skill == "paper_skill"
    assert result.confidence >= 0.9


def test_career_skill_route():
    result = asyncio.run(SkillRouter(DecisionEngine(MockJEVClient())).route("分析这个岗位是否适合我"))
    assert result.skill == "career_skill"


def test_coding_skill_route():
    result = asyncio.run(SkillRouter(DecisionEngine(MockJEVClient())).route("分析这个 Python bug"))
    assert result.skill == "coding_skill"


def test_agent_route():
    result = asyncio.run(AgentRouter(DecisionEngine(MockJEVClient())).route("分析 GitHub issue"))
    assert result.agent == "coding_agent"


def test_adapter_contract():
    result = asyncio.run(DoubaoAdapter().execute_skill("paper_skill", "format paper"))
    assert result["status"] == "adapter_stub"


def test_default_registry_contains_all_builtin_skills():
    registry = create_default_registry()
    assert [skill.name for skill in registry.list()] == [
        "career_skill", "paper_skill", "coding_skill", "research_skill", "writing_skill"
    ]
    assert registry.get("career_skill") is not None


def test_executor_runs_decided_skill():
    result = SkillExecutor(create_default_registry()).execute("career_skill", "分析这个岗位")
    assert result == {
        "skill": "career_skill",
        "status": "completed",
        "result": "Career analysis workflow executed",
    }


def test_research_decision_executes_mock_skill():
    task = "搜索资料并生成技术报告"
    decision = asyncio.run(DecisionEngine(MockJEVClient()).decide(
        task, ["career_skill", "coding_skill", "research_skill", "writing_skill"]
    ))
    assert decision.decision == "research_skill"
    assert SkillExecutor(create_default_registry()).execute(decision, task) == {
        "skill": "research_skill",
        "status": "completed",
        "result": "Research workflow executed (mock)",
    }


def test_agent_run_api_decides_and_executes_skill(monkeypatch):
    monkeypatch.setenv("PERMITMCP_EXECUTION_TOKEN", "test-execution-only")
    monkeypatch.setenv("PERMITMCP_APPROVAL_TOKEN", "test-approval-only")
    app = FastAPI()
    app.include_router(build_router(DecisionEngine(MockJEVClient())))
    response = TestClient(app).post("/api/v1/agent/run", json={"task": "帮我分析这个招聘岗位"}, headers={"Authorization": "Bearer test-execution-only"})
    assert response.status_code == 200
    assert response.json() == {
        "decision": {"skill": "career_skill", "confidence": 0.91},
        "execution": {
            "status": "completed",
            "result": "Career analysis workflow executed",
        },
    }
