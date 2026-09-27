from fastapi import APIRouter, Depends, HTTPException
import httpx
from pathlib import Path
from ..agent import ApprovalError, ControlledAgentRunner
from ..composition import create_controlled_agent
from ..core.models import DecisionRequest, DecisionResult, RouteRequest, RouteResult, AgentRouteResult, AgentRunRequest, AgentRunResult
from ..control.models import ApprovalRequest, ControlledAgentRunRequest
from ..core.decision import DecisionEngine
from ..core.router import SkillRouter, AgentRouter
from ..skills import SkillExecutor, SkillRegistry, create_default_registry
from .auth import require_approval, require_execution


def build_router(
    engine: DecisionEngine,
    registry: SkillRegistry | None = None,
    controlled_agent: ControlledAgentRunner | None = None,
    sandbox_root: str | Path | None = None,
) -> APIRouter:
    api = APIRouter()
    registry = registry or create_default_registry()
    skills, agents = SkillRouter(engine), AgentRouter(engine)
    executor = SkillExecutor(registry)
    controlled_agent = controlled_agent or create_controlled_agent(engine, sandbox_root)

    @api.get("/health")
    async def health(): return {"status": "ok"}

    @api.post("/decide", response_model=DecisionResult, dependencies=[Depends(require_execution)])
    async def decide(body: DecisionRequest):
        try:
            return await engine.decide(body.task, body.options)
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(502, "Decision engine failed or returned an invalid decision") from exc

    @api.post("/route/skill", response_model=RouteResult, dependencies=[Depends(require_execution)])
    async def route_skill(body: RouteRequest):
        try:
            return await skills.route(body.task)
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(502, "Decision engine failed or returned an invalid decision") from exc

    @api.post("/route/agent", response_model=AgentRouteResult, dependencies=[Depends(require_execution)])
    async def route_agent(body: RouteRequest):
        try:
            return await agents.route(body.task)
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(502, "Decision engine failed or returned an invalid decision") from exc

    @api.post("/api/v1/agent/run", response_model=AgentRunResult, dependencies=[Depends(require_execution)])
    async def run_agent(body: AgentRunRequest):
        try:
            decision = await engine.decide(body.task, [skill.name for skill in registry.list()])
            execution = executor.execute(decision, body.task)
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(502, "Decision engine failed or returned an invalid decision") from exc
        return {
            "decision": {"skill": decision.decision, "confidence": decision.confidence},
            "execution": {"status": execution["status"], "result": execution["result"]},
        }

    @api.post("/api/v1/controlled-agent/run", dependencies=[Depends(require_execution)])
    async def controlled_agent_run(body: ControlledAgentRunRequest):
        trace = await controlled_agent.run(body.task, max_steps=body.max_steps)
        return trace.public_dict()

    @api.post("/api/v1/controlled-agent/{run_id}/approve", dependencies=[Depends(require_approval)])
    async def approve_controlled_action(run_id: str, body: ApprovalRequest):
        try:
            trace = await controlled_agent.approve_action(body.action_id, run_id=run_id)
        except ApprovalError as exc:
            raise HTTPException(409, str(exc)) from exc
        return trace.public_dict()

    return api
