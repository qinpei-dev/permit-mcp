"""MCP tool registration backed by the existing JEV and skill components."""

import asyncio
import os
import secrets
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..agent import ControlledAgentRunner
from ..composition import create_controlled_agent
from ..control.models import ActionProposal
from ..core.decision import DecisionEngine
from ..jev.client import JEVClient
from ..skills import SkillExecutor, SkillRegistry, create_default_registry
from ..upstream.configured import ConfiguredUpstream
from .schemas import (
    AgentRunDecision,
    AgentRunInput,
    AgentRunOutput,
    JEVDecideInput,
    JEVDecision,
)


def register_tools(
    server: FastMCP,
    engine: DecisionEngine,
    registry: SkillRegistry | None = None,
    controlled_agent: ControlledAgentRunner | None = None,
) -> None:
    registry = registry or create_default_registry()
    executor = SkillExecutor(registry)
    controlled_agent = controlled_agent or create_controlled_agent(engine)

    @server.tool()
    async def jev_decide(task: str, options: list[str]) -> dict:
        """Make a constrained decision with the JEV Decision Engine."""
        request = JEVDecideInput(task=task, options=options)
        decision = await engine.decide(request.task, request.options)
        if decision.decision not in request.options:
            raise ValueError("Decision engine returned an unavailable option")
        return JEVDecision(
            decision=decision.decision, confidence=decision.confidence
        ).model_dump()

    @server.tool()
    async def agent_run(task: str) -> dict:
        """Run JEV skill selection followed by local Skill Executor execution."""
        request = AgentRunInput(task=task)
        decision = await engine.decide(
            request.task, [skill.name for skill in registry.list()]
        )
        execution = executor.execute(decision, request.task)
        return AgentRunOutput(
            decision=AgentRunDecision(
                skill=decision.decision, confidence=decision.confidence
            ),
            execution=execution,
        ).model_dump()

    @server.tool()
    def list_skills() -> list[str]:
        """List skill names supported by this PermitMCP instance."""
        return [skill.name for skill in registry.list()]

    @server.tool()
    async def controlled_agent_run(task: str, max_steps: int = 5) -> dict:
        """Run proposed local actions through policy, JEV, permits, and sandbox tools."""
        trace = await controlled_agent.run(task, max_steps=max_steps)
        return trace.public_dict()

    @server.tool()
    async def approve_action(run_id: str, action_id: str) -> dict:
        """Approve and resume one action currently waiting for caller review."""
        trace = await controlled_agent.approve_action(action_id, run_id=run_id)
        return trace.public_dict()


def create_mcp_server(
    client: JEVClient | None = None,
    sandbox_root: str | Path | None = None,
) -> FastMCP:
    """Create the MCP server, defaulting to the environment-selected JEV client."""
    from ..jev.client import JEVClient as ClientFactory

    server = FastMCP("PermitMCP")
    engine = DecisionEngine(client or ClientFactory.from_env())
    controlled_agent = create_controlled_agent(engine, sandbox_root)
    register_tools(server, engine, controlled_agent=controlled_agent)
    config_path = os.getenv("PERMITMCP_UPSTREAM_CONFIG")
    if config_path:
        upstream = ConfiguredUpstream.from_file(config_path)
        approval_token = os.getenv("PERMITMCP_UPSTREAM_APPROVAL_TOKEN")
        if not approval_token:
            raise ValueError(
                "PERMITMCP_UPSTREAM_APPROVAL_TOKEN is required for configured upstream"
            )
        pending = {}
        init_lock = asyncio.Lock()

        async def ready():
            async with init_lock:
                if upstream.chain is None:
                    await upstream.initialize()

        @server.tool()
        async def upstream_tools() -> list[str]:
            """List locally configured and discovered upstream tools."""
            await ready()
            return list(upstream.schemas)

        @server.tool()
        async def upstream_call(tool: str, arguments: dict) -> dict:
            """Run one configured upstream action through policy and a one-use permit."""
            await ready()
            proposal = ActionProposal(
                tool=tool, arguments=arguments, description="MCP client upstream call"
            )
            result = await upstream.chain.run(proposal)
            if result.status == "review":
                pending[proposal.action_id] = (proposal, result)
            return {
                "status": result.status,
                "action_id": proposal.action_id if result.status == "review" else None,
                "result": result.tool_result.output if result.tool_result else None,
                "error": result.error,
            }

        @server.tool()
        async def upstream_approve(action_id: str, approval_token: str) -> dict:
            """Approve an exact pending upstream action using the separate local approval secret."""
            if not secrets.compare_digest(
                approval_token, os.getenv("PERMITMCP_UPSTREAM_APPROVAL_TOKEN", "")
            ):
                raise PermissionError("invalid approval token")
            if action_id not in pending:
                raise ValueError("unknown pending action")
            proposal, reviewed = pending.pop(action_id)
            result = upstream.chain.approve(proposal, reviewed)
            return {
                "status": result.status,
                "result": result.tool_result.output if result.tool_result else None,
                "error": result.error,
            }

    return server
