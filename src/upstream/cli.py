"""Local operator CLI for one configured upstream tool action."""

import argparse
import asyncio
import json

from ..control.models import ActionProposal
from .configured import ConfiguredUpstream


async def run() -> int:
    parser = argparse.ArgumentParser(
        description="Run a permit-controlled stdio MCP tool"
    )
    parser.add_argument(
        "--config", required=True, help="trusted local JSON configuration"
    )
    parser.add_argument("--tool", required=True)
    parser.add_argument("--arguments", required=True, help="JSON object")
    args = parser.parse_args()
    upstream = ConfiguredUpstream.from_file(args.config)
    discovered = await upstream.initialize()
    print("Discovered configured tools:", ", ".join(discovered))
    proposal = ActionProposal(
        tool=args.tool,
        arguments=json.loads(args.arguments),
        description="local operator call",
    )
    result = await upstream.chain.run(proposal)
    if result.status == "review":
        print(f"Review required for {proposal.tool}, action {proposal.action_id}")
        if input("Approve this exact action? Type 'approve': ").strip() == "approve":
            result = upstream.chain.approve(proposal, result)
    print(
        json.dumps(
            {
                "status": result.status,
                "result": result.tool_result.output if result.tool_result else None,
                "error": result.error,
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.status == "success" else 1


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
