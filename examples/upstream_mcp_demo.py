"""Offline proof of one permit-gated call to a separate stdio MCP server."""

import asyncio

from src.control.chain import ControlChain
from src.control.controller import DecisionController
from src.control.models import ActionProposal
from src.control.permits import ExecutionPermitAuthority
from src.upstream.sample_executor import ReadSampleExecutor
from src.upstream.sample_policy import ReadSamplePolicy


async def main() -> None:
    policy = ReadSamplePolicy()
    permits = ExecutionPermitAuthority()
    chain = ControlChain(
        DecisionController(None, policy), permits, ReadSampleExecutor(policy, permits)
    )
    proposal = ActionProposal(
        tool="read_sample", arguments={"sample_id": "greeting"},
        description="read a bundled upstream sample",
    )
    result = await chain.run(proposal)
    if result.status != "success" or result.tool_result is None:
        raise RuntimeError(result.error or result.decision.reason)
    print(result.tool_result.output)


if __name__ == "__main__":
    asyncio.run(main())
