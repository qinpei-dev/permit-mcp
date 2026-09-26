"""Permit-gated client for one real stdio MCP tools/call."""

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..control.errors import PolicyDenied, ReviewRequired
from ..control.models import ActionProposal, DecisionOutcome, ExecutionPermit, PolicyStatus, ToolResult
from ..control.permits import ExecutionPermitAuthority
from .sample_policy import TOOL_NAME, ReadSamplePolicy


class ReadSampleExecutor:
    """Synchronous ToolExecutor bridge into a single upstream MCP call."""

    def __init__(
        self,
        policy: ReadSamplePolicy,
        permit_authority: ExecutionPermitAuthority,
        server: StdioServerParameters | None = None,
        timeout: timedelta = timedelta(seconds=10),
    ):
        if timeout <= timedelta(0):
            raise ValueError("upstream MCP timeout must be positive")
        self.policy = policy
        self.permit_authority = permit_authority
        self.server = server or StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.upstream.sample_server"],
            cwd=Path(__file__).resolve().parents[2],
        )
        self.timeout = timeout

    def execute(self, proposal: ActionProposal, permit: ExecutionPermit) -> ToolResult:
        current = self.policy.check(proposal)
        if current.status == PolicyStatus.DENY:
            raise PolicyDenied(current.reason)
        if current.status == PolicyStatus.REVIEW and (
            permit is None or permit.decision != DecisionOutcome.REVIEW or permit.approval_source != "caller"
        ):
            raise ReviewRequired(current.reason)
        self.permit_authority.consume(proposal, permit)
        try:
            # ControlChain's ToolExecutor contract is synchronous while its
            # caller already owns an event loop. Run the MCP client in a worker.
            with ThreadPoolExecutor(max_workers=1) as worker:
                output = worker.submit(lambda: asyncio.run(self._call_upstream(proposal.arguments))).result()
        except Exception as exc:
            raise RuntimeError("upstream MCP read_sample call failed") from exc
        return ToolResult(output=output, metadata={"upstream_tool": TOOL_NAME})

    async def _call_upstream(self, arguments: dict) -> str:
        async with asyncio.timeout(self.timeout.total_seconds()):
            with open(os.devnull, "w", encoding="utf-8") as errlog:
                async with stdio_client(self.server, errlog=errlog) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=self.timeout) as session:
                        await session.initialize()
                        result = await session.call_tool(TOOL_NAME, arguments)
                        if result.isError:
                            raise RuntimeError("upstream MCP tool returned an error")
                        if len(result.content) != 1 or result.content[0].type != "text":
                            raise RuntimeError("upstream MCP tool returned an unsupported result")
                        return result.content[0].text
