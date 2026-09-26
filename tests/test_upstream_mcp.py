"""One real upstream MCP tools/call through the existing ControlChain."""

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from mcp import StdioServerParameters

from src.control.chain import ControlChain
from src.control.controller import DecisionController
from src.control.models import ActionProposal, ControlDecision, DecisionOutcome, PolicyResult, PolicyStatus
from src.control.permits import ExecutionPermitAuthority, PermitError
from src.upstream.sample_executor import ReadSampleExecutor
from src.upstream.sample_policy import ReadSamplePolicy


def proposal(sample_id="greeting", tool="read_sample"):
    return ActionProposal(tool=tool, arguments={"sample_id": sample_id}, description="read a fixed sample")


def build_chain(policy=None, provider=None, permits=None):
    policy = policy or ReadSamplePolicy()
    permits = permits or ExecutionPermitAuthority()
    executor = ReadSampleExecutor(policy, permits)
    return ControlChain(DecisionController(provider, policy), permits, executor)


def allowed_decision(action):
    return ControlDecision(
        action_id=action.action_id, proposal_digest=action.digest(),
        outcome=DecisionOutcome.ALLOW, reason="allowed", source="policy",
    )


def test_real_upstream_stdio_tools_call_through_chain(monkeypatch):
    import src.upstream.sample_server as local_server

    # A direct in-process call would hit this replacement. The child imports
    # its own module and must answer over stdio MCP instead.
    monkeypatch.setattr(local_server, "read_sample", lambda sample_id: pytest.fail("direct call"))
    result = asyncio.run(build_chain().run(proposal()))
    assert result.status == "success"
    assert result.tool_result.output == "Hello from upstream MCP"
    assert result.tool_result.metadata == {"upstream_tool": "read_sample"}
    assert result.permit.proposal_digest == result.decision.proposal_digest


def test_upstream_policy_projects_only_sample_id_to_provider():
    class Provider:
        task = None

        async def decide(self, task, options):
            self.task = task
            return SimpleNamespace(decision="allow", confidence=1.0, reason="allowed")

    provider = Provider()
    result = asyncio.run(build_chain(provider=provider).run(proposal()))
    assert result.status == "success"
    assert '"arguments": {"sample_id": "greeting"}' in provider.task
    assert "read a fixed sample" not in provider.task


def test_deny_prevents_upstream_call(monkeypatch):
    class DenyPolicy(ReadSamplePolicy):
        def check(self, action):
            return PolicyResult(status=PolicyStatus.DENY, reason="denied")

    chain = build_chain(DenyPolicy())
    monkeypatch.setattr(chain.executor, "_call_upstream", lambda args: pytest.fail("upstream called"))
    result = asyncio.run(chain.run(proposal()))
    assert result.status == "blocked"
    assert result.permit is None


def test_review_waits_for_approval_then_calls_upstream(monkeypatch):
    class ReviewPolicy(ReadSamplePolicy):
        def check(self, action):
            checked = super().check(action)
            if checked.status == PolicyStatus.PASS:
                return PolicyResult(status=PolicyStatus.REVIEW, reason="requires approval")
            return checked

    chain = build_chain(ReviewPolicy())
    calls = []
    real_call = chain.executor._call_upstream

    async def tracked_call(args):
        calls.append(args)
        return await real_call(args)

    monkeypatch.setattr(chain.executor, "_call_upstream", tracked_call)
    action = proposal()
    reviewed = asyncio.run(chain.run(action))
    assert reviewed.status == "review"
    assert calls == []
    approved = chain.approve(action, reviewed)
    assert approved.status == "success"
    assert calls == [{"sample_id": "greeting"}]


def test_exact_arguments_bound_before_any_upstream_call(monkeypatch):
    chain = build_chain()
    original = proposal()
    permit = chain.permits.issue(original, allowed_decision(original), "policy")
    changed = original.model_copy(update={"arguments": {"sample_id": "farewell"}})
    monkeypatch.setattr(chain.executor, "_call_upstream", lambda args: pytest.fail("upstream called"))
    with pytest.raises(PermitError, match="invalid or does not match"):
        chain.executor.execute(changed, permit)
    assert permit.proposal_digest == original.digest()
    assert permit.proposal_digest != changed.digest()


def test_expired_permit_prevents_upstream_call(monkeypatch):
    import src.control.permits as permits_module

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Clock:
        @staticmethod
        def now(tz):
            return now

    monkeypatch.setattr(permits_module, "datetime", Clock)
    chain = build_chain(permits=ExecutionPermitAuthority(ttl=timedelta(seconds=1)))
    action = proposal()
    permit = chain.permits.issue(action, allowed_decision(action), "policy")
    now += timedelta(seconds=1)
    monkeypatch.setattr(chain.executor, "_call_upstream", lambda args: pytest.fail("upstream called"))
    with pytest.raises(PermitError, match="expired"):
        chain.executor.execute(action, permit)


def test_single_use_permit_only_calls_upstream_once(monkeypatch):
    chain = build_chain()
    action = proposal()
    permit = chain.permits.issue(action, allowed_decision(action), "policy")
    calls = []

    async def call(args):
        calls.append(args)
        return "ok"

    monkeypatch.setattr(chain.executor, "_call_upstream", call)
    assert chain.executor.execute(action, permit).output == "ok"
    with pytest.raises(PermitError, match="invalid or does not match"):
        chain.executor.execute(action, permit)
    assert len(calls) == 1


def test_upstream_failure_is_structured_control_error(monkeypatch):
    chain = build_chain()
    issued = []
    real_issue = chain.permits.issue

    def capture_issue(*args):
        permit = real_issue(*args)
        issued.append(permit)
        return permit

    monkeypatch.setattr(chain.permits, "issue", capture_issue)

    async def fail(args):
        raise OSError("upstream disconnected")

    monkeypatch.setattr(chain.executor, "_call_upstream", fail)
    action = proposal()
    result = asyncio.run(chain.run(action))
    assert result.status == "error"
    assert result.tool_result is None
    assert result.error == "upstream MCP read_sample call failed"
    assert result.permit is None
    assert len(issued) == 1
    with pytest.raises(PermitError):
        chain.permits.consume(action, issued[0])


def test_upstream_process_start_failure_is_error():
    chain = build_chain()
    chain.executor.server = StdioServerParameters(
        command="permitmcp-command-that-does-not-exist", args=[]
    )
    result = asyncio.run(chain.run(proposal()))
    assert result.status == "error"
    assert result.tool_result is None
    assert result.error == "upstream MCP read_sample call failed"


def test_upstream_initialization_timeout_is_error():
    chain = build_chain()
    chain.executor.server = StdioServerParameters(
        command=sys.executable, args=["-c", "import time; time.sleep(30)"]
    )
    chain.executor.timeout = timedelta(milliseconds=200)
    start = time.monotonic()
    result = asyncio.run(chain.run(proposal()))
    assert time.monotonic() - start < 10
    assert result.status == "error"
    assert result.tool_result is None


def test_invalid_upstream_protocol_is_error():
    chain = build_chain()
    chain.executor.server = StdioServerParameters(
        command=sys.executable,
        args=["-c", "print('not-json', flush=True)"],
    )
    result = asyncio.run(chain.run(proposal()))
    assert result.status == "error"
    assert result.tool_result is None


def test_upstream_tool_error_is_not_success():
    class PermissivePolicy(ReadSamplePolicy):
        def check(self, action):
            return PolicyResult(status=PolicyStatus.PASS, reason="test only")

    result = asyncio.run(build_chain(PermissivePolicy()).run(proposal(sample_id="missing")))
    assert result.status == "error"
    assert result.tool_result is None
    assert result.error == "upstream MCP read_sample call failed"


def test_unknown_tool_cannot_use_single_tool_executor(monkeypatch):
    chain = build_chain()
    monkeypatch.setattr(chain.executor, "_call_upstream", lambda args: pytest.fail("upstream called"))
    unknown = proposal(tool="other_tool")
    assert asyncio.run(chain.run(unknown)).status == "blocked"
    permit = chain.permits.issue(unknown, allowed_decision(unknown), "policy")
    with pytest.raises(PermissionError, match="not the permitted upstream tool"):
        chain.executor.execute(unknown, permit)
