"""Trusted local stdio MCP configuration and permit-gated upstream execution."""

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from mcp.client.stdio import stdio_client

from mcp import ClientSession, StdioServerParameters

from ..control.chain import ControlChain
from ..control.controller import DecisionController
from ..control.errors import PolicyDenied, ReviewRequired
from ..control.models import (
    ActionProposal,
    DecisionOutcome,
    ExecutionPermit,
    PolicyResult,
    PolicyStatus,
    ToolResult,
)
from ..control.permits import ExecutionPermitAuthority


class ConfiguredPolicy:
    def __init__(self, rules: dict, schemas: dict):
        self.rules = rules
        self.schemas = schemas

    def check(self, proposal: ActionProposal) -> PolicyResult:
        rule = self.rules.get(proposal.tool)
        if rule is None or proposal.tool not in self.schemas:
            return PolicyResult(
                status=PolicyStatus.DENY,
                reason="upstream tool is not configured and discovered",
            )
        try:
            Draft202012Validator(self.schemas[proposal.tool]).validate(
                proposal.arguments
            )
        except ValidationError:
            return PolicyResult(
                status=PolicyStatus.DENY, reason="invalid upstream tool arguments"
            )
        status = PolicyStatus.PASS if rule == "allow" else PolicyStatus(rule)
        return PolicyResult(status=status, reason=f"configured {rule} rule")

    @staticmethod
    def decision_arguments(proposal: ActionProposal) -> dict:
        # No upstream arguments are disclosed to optional external providers.
        return {}


class ConfiguredExecutor:
    def __init__(
        self,
        server: StdioServerParameters,
        policy: ConfiguredPolicy,
        permits: ExecutionPermitAuthority,
        timeout: timedelta = timedelta(seconds=15),
    ):
        self.server, self.policy, self.permits, self.timeout = (
            server,
            policy,
            permits,
            timeout,
        )

    def execute(self, proposal: ActionProposal, permit: ExecutionPermit) -> ToolResult:
        current = self.policy.check(proposal)
        if current.status == PolicyStatus.DENY:
            raise PolicyDenied(current.reason)
        if current.status == PolicyStatus.REVIEW and (
            permit.decision != DecisionOutcome.REVIEW
            or permit.approval_source != "caller"
        ):
            raise ReviewRequired(current.reason)
        self.permits.consume(proposal, permit)
        try:
            with ThreadPoolExecutor(max_workers=1) as worker:
                result = worker.submit(
                    lambda: asyncio.run(self._call(proposal.tool, proposal.arguments))
                ).result()
        except Exception as exc:
            raise RuntimeError("configured upstream MCP call failed") from exc
        return ToolResult(
            output=json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
            metadata={"upstream_tool": proposal.tool},
        )

    async def _call(self, name: str, arguments: dict):
        async with asyncio.timeout(self.timeout.total_seconds()):
            with open(os.devnull, "w", encoding="utf-8") as errlog:  # noqa: ASYNC230
                async with stdio_client(self.server, errlog=errlog) as (read, write):  # noqa: SIM117
                    async with ClientSession(
                        read, write, read_timeout_seconds=self.timeout
                    ) as session:
                        await session.initialize()
                        # Reconfirm the tool remains advertised by this process.
                        discovered = {
                            tool.name for tool in (await session.list_tools()).tools
                        }
                        if name not in discovered:
                            raise RuntimeError("configured tool disappeared")
                        result = await session.call_tool(name, arguments)
                        if result.isError:
                            raise RuntimeError("upstream tool returned an error")
                        return result


class ConfiguredUpstream:
    """Local owner constructs this once; remote clients can only submit proposals."""

    def __init__(self, config: dict):
        if set(config) != {"command", "args", "env", "tools"}:
            raise ValueError(
                "configuration requires command, args, env, and tools only"
            )
        command, args, env, rules = (
            config[key] for key in ("command", "args", "env", "tools")
        )
        if (
            not isinstance(command, str)
            or not command
            or not os.path.isabs(command)
            or not Path(command).is_file()
        ):
            raise ValueError("command must be an existing absolute executable path")
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise ValueError("args must be a list of strings")
        if not isinstance(env, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()
        ):
            raise ValueError(
                "env must map variable names to local environment variable names"
            )
        if (
            not isinstance(rules, dict)
            or not rules
            or any(
                not isinstance(k, str) or v not in ("allow", "review", "deny")
                for k, v in rules.items()
            )
        ):
            raise ValueError("tools must map names to allow, review, or deny")
        selected_env = {}
        for target, source in env.items():
            if (
                not target.isidentifier()
                or source not in os.environ
                or not os.environ[source]
            ):
                raise ValueError("invalid or missing configured environment variable")
            selected_env[target] = os.environ[source]
        self.server = StdioServerParameters(
            command=command, args=args, env=selected_env
        )
        self.rules = rules
        self.schemas = {}
        self.chain = None

    @classmethod
    def from_file(cls, path: str | Path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    async def initialize(self):
        with open(os.devnull, "w", encoding="utf-8") as errlog:  # noqa: ASYNC230
            async with asyncio.timeout(15):
                async with stdio_client(self.server, errlog=errlog) as (read, write):  # noqa: SIM117
                    async with ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=15)
                    ) as session:
                        await session.initialize()
                        tools = (await session.list_tools()).tools
        self.schemas = {
            tool.name: tool.inputSchema for tool in tools if tool.name in self.rules
        }
        if set(self.schemas) != set(self.rules):
            raise ValueError("configured tool was not discovered")
        for schema in self.schemas.values():
            Draft202012Validator.check_schema(schema)
        policy = ConfiguredPolicy(self.rules, self.schemas)
        permits = ExecutionPermitAuthority()
        self.chain = ControlChain(
            DecisionController(None, policy),
            permits,
            ConfiguredExecutor(self.server, policy, permits),
        )
        return list(self.schemas)
